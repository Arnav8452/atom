#!/usr/bin/env python3
"""Atom for Antigravity CLI: a custom status line command.

Antigravity CLI runs this through its documented `statusLine` setting
(https://antigravity.google/docs/cli/statusline/) whenever the agent state
changes, with the session state as JSON on stdin. Whatever this prints to
stdout is shown under the CLI's own status line (`stack_with_default`).

It only uses documented extension points: the status line payload and the
state files that Atom's own plugin hooks (atom_hook.py) already write. It
never wraps, launches or modifies `agy`.

Rules (same spirit as atom_hook.py):
  * stdlib only, safe under `python3 -S -I`, always exits 0;
  * prints a fallback line instead of failing, because the CLI disables a
    status line after 30 consecutive failures;
  * never stores or prints the payload's `email`, title, paths or prompts.
    The only thing written to disk is ATOM_HOME/cli/<conversation>.json
    holding the last shown state and a timestamp.

Usage:
  atom_status.py                     read the payload on stdin (what agy does)
  atom_status.py --style line        always a single line
  atom_status.py --color 256         for terminals without truecolor
  atom_status.py --demo              print every state, for trying it out
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time

HOME = os.environ.get("ATOM_HOME") or os.path.join(os.path.expanduser("~"), ".antigravity-atom")

WATCHDOG_SEC = 3.0  # the CLI stops a status line command after 5 s
SPRITE_MIN_WIDTH = 50  # below this terminal width, use the one-line style
HOOK_STATE_TTL_SEC = 15 * 60  # hook state older than this is ignored
EMOTION_TTL_SEC = 45  # how long an emotion.json reaction counts as fresh
REACTION_TTL_SEC = 15 * 60  # how long "done"/"error"/... stays after a turn

BUSY_HOOK_STATES = frozenset({"thinking", "typing", "working", "exploring", "running", "delegating", "asking"})
BUSY_AGENT_STATES = frozenset({"working", "tool_use", "reviewing", "thinking"})
REACTIONS = frozenset({"done", "error", "canceled", "tired"})

# --- art --------------------------------------------------------------------
# 16x10 pixels, drawn with half blocks (2 pixels per row) -> 5 lines.
#   c crown (rainbow by column)   B body   D body shade   . transparent
BASE = (
    "..cccccccccccc..",
    "..BBBBBBBBBBBB..",
    "..BBBBBBBBBBBB..",
    "..BBBBBBBBBBBB..",
    "..BBBBBBBBBBBB..",
    ".BBBBBBBBBBBBBB.",
    "BB.BBBBBBBBBB.BB",
    "...DDDDDDDDDD...",
    "...DDD....DDD...",
    "...DDD....DDD...",
)
SPRITE_W = len(BASE[0])
SPRITE_H = len(BASE)
LEFT_EYE = (4, 2)
RIGHT_EYE = (10, 2)

# Eye shapes as (dx, dy) offsets from each eye's origin, for (left, right).
_OPEN = ((0, 0), (1, 0), (0, 1), (1, 1))
EYES = {
    "open": (_OPEN, _OPEN),
    "up": (((0, -1), (1, -1), (0, 0), (1, 0)),) * 2,
    "down": (((0, 1), (1, 1), (0, 2), (1, 2)),) * 2,
    "left": (((-1, 0), (0, 0), (-1, 1), (0, 1)),) * 2,
    "right": (((1, 0), (2, 0), (1, 1), (2, 1)),) * 2,
    "closed": (((0, 1), (1, 1)),) * 2,
    "sleepy": (((-1, 1), (0, 1), (1, 1), (2, 1)),) * 2,
    "happy": (((-1, 1), (0, 0), (1, 0), (2, 1)),) * 2,
    "x": (((-1, 0), (1, 0), (0, 1), (-1, 2), (1, 2)), ((0, 0), (2, 0), (1, 1), (0, 2), (2, 2))),
    # Inner brows pulled down.
    "angry": (_OPEN + ((1, -1), (2, -1)), _OPEN + ((0, -1), (-1, -1))),
    # Outer brows down, eyes low.
    "sad": (((0, 1), (1, 1), (0, 2), (1, 2), (-1, 0)), ((0, 1), (1, 1), (0, 2), (1, 2), (2, 0))),
    "wide": (((0, -1), (1, -1), (0, 0), (1, 0), (0, 1), (1, 1)),) * 2,
}
# Extra pixels in a colour of their own: (x, y, rgb).
EXTRAS = {
    "blush": ((3, 4, (255, 140, 180)), (12, 4, (255, 140, 180))),
    "tear": ((4, 5, (150, 220, 255)),),
    "sweat": ((14, 1, (150, 220, 255)), (14, 2, (150, 220, 255))),
}

EYE_RGB = (10, 14, 20)
BODY_RGB = (44, 140, 232)
SHADE_RGB = (30, 104, 196)
RAINBOW = (
    (255, 84, 84),
    (255, 150, 60),
    (250, 214, 70),
    (96, 214, 120),
    (60, 196, 232),
    (112, 124, 255),
    (196, 96, 232),
)


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def _crown(col: int) -> tuple:
    span = 11  # crown runs over columns 2..13
    pos = max(0.0, min(1.0, (col - 2) / span)) * (len(RAINBOW) - 1)
    i = min(int(pos), len(RAINBOW) - 2)
    return _mix(RAINBOW[i], RAINBOW[i + 1], pos - i)


# --- looks for each state ---------------------------------------------------
# state -> (eyes, extras, tint, label colour)
LOOKS = {
    "idle": ("open", (), None, (150, 200, 255)),
    "thinking": ("up", (), None, (190, 160, 255)),
    "typing": ("down", (), None, (110, 220, 160)),
    "running": ("right", (), None, (110, 220, 160)),
    "exploring": ("left", (), None, (90, 200, 240)),
    "working": ("open", (), None, (110, 220, 160)),
    "reviewing": ("down", (), None, (190, 160, 255)),
    "delegating": ("right", (), None, (90, 200, 240)),
    "watching": ("left", (), None, (150, 200, 255)),
    "approval": ("wide", ("sweat",), "approval", (250, 214, 70)),
    "asking": ("wide", (), "approval", (250, 214, 70)),
    "waking": ("sleepy", (), "dim", (150, 160, 180)),
    "sleeping": ("closed", (), "sleep", (150, 160, 180)),
    "done": ("happy", ("blush",), None, (96, 214, 120)),
    "happy": ("happy", ("blush",), None, (255, 140, 180)),
    "error": ("x", (), "error", (255, 96, 96)),
    "canceled": ("closed", (), None, (150, 160, 180)),
    "tired": ("sleepy", ("sweat",), "dim", (250, 170, 80)),
    "angry": ("angry", (), "angry", (255, 96, 96)),
    "sad": ("sad", ("tear",), "sad", (150, 170, 220)),
}

LABELS = {
    "idle": "ready",
    "thinking": "thinking…",
    "typing": "writing code…",
    "running": "running a command…",
    "exploring": "looking around…",
    "working": "working…",
    "reviewing": "reviewing…",
    "delegating": "delegating…",
    "watching": "keeping watch…",
    "approval": "needs your OK",
    "asking": "has a question",
    "waking": "waking up…",
    "sleeping": "out of quota · zzz",
    "done": "done!",
    "happy": "aw, thanks!",
    "error": "hit an error",
    "canceled": "stopped",
    "tired": "hit the step limit",
    "angry": "…",
    "sad": "…",
}

# Short faces for the one-line style.
FACES = {
    "open": "■ ■",
    "up": "▀ ▀",
    "down": "▄ ▄",
    "left": "■  ",
    "right": "  ■",
    "closed": "– –",
    "sleepy": "─ ─",
    "happy": "^ ^",
    "x": "× ×",
    "angry": "╲ ╱",
    "sad": "╥ ╥",
    "wide": "◼ ◼",
}


def _tinted(rgb: tuple, tint: str | None, part: str) -> tuple:
    if tint is None:
        return rgb
    if tint == "angry":
        return _mix(rgb, (230, 60, 70), 0.45)
    if tint == "sad":
        grey = (sum(rgb) // 3,) * 3
        return _mix(_mix(rgb, grey, 0.6), (70, 90, 140), 0.2)
    if tint in ("sleep", "dim"):
        return _mix(rgb, (20, 24, 34), 0.5 if tint == "sleep" else 0.3)
    if tint == "error":
        return (235, 70, 70) if part == "crown" else _mix(rgb, (120, 40, 60), 0.25)
    if tint == "approval":
        return (250, 214, 70) if part == "crown" else rgb
    return rgb


def sprite_pixels(state: str) -> list[list[tuple | None]]:
    eyes, extras, tint, _ = LOOKS.get(state, LOOKS["idle"])
    grid: list[list[tuple | None]] = []
    for y, row in enumerate(BASE):
        line: list[tuple | None] = []
        for x, ch in enumerate(row):
            if ch == "c":
                line.append(_tinted(_crown(x), tint, "crown"))
            elif ch == "B":
                line.append(_tinted(BODY_RGB, tint, "body"))
            elif ch == "D":
                line.append(_tinted(SHADE_RGB, tint, "body"))
            else:
                line.append(None)
        grid.append(line)
    left, right = EYES[eyes]
    for (ox, oy), offsets in ((LEFT_EYE, left), (RIGHT_EYE, right)):
        for dx, dy in offsets:
            x, y = ox + dx, oy + dy
            if 0 <= y < SPRITE_H and 0 <= x < SPRITE_W and grid[y][x] is not None:
                grid[y][x] = EYE_RGB
    for name in extras:
        for x, y, rgb in EXTRAS[name]:
            if 0 <= y < SPRITE_H and 0 <= x < SPRITE_W:
                grid[y][x] = rgb
    return grid


# --- colour output ----------------------------------------------------------

RESET = "\x1b[0m"


def _rgb_to_256(rgb: tuple) -> int:
    r, g, b = rgb
    if abs(r - g) < 10 and abs(g - b) < 10:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + round((r - 8) / 247 * 24)

    def q(v: int) -> int:
        return 0 if v < 48 else 1 if v < 115 else (v - 35) // 40

    return 16 + 36 * q(r) + 6 * q(g) + q(b)


def fg(rgb: tuple, mode: str) -> str:
    if mode == "none":
        return ""
    if mode == "256":
        return f"\x1b[38;5;{_rgb_to_256(rgb)}m"
    return "\x1b[38;2;{};{};{}m".format(*rgb)


def bg(rgb: tuple, mode: str) -> str:
    if mode == "none":
        return ""
    if mode == "256":
        return f"\x1b[48;5;{_rgb_to_256(rgb)}m"
    return "\x1b[48;2;{};{};{}m".format(*rgb)


def sprite_lines(state: str, mode: str) -> list[str]:
    grid = sprite_pixels(state)
    out = []
    for y in range(0, SPRITE_H, 2):
        top, bottom = grid[y], grid[y + 1] if y + 1 < SPRITE_H else [None] * SPRITE_W
        line = ""
        for t, b in zip(top, bottom):
            if t is None and b is None:
                line += RESET + " "
            elif b is None:
                line += RESET + fg(t, mode) + "▀"
            elif t is None:
                line += RESET + fg(b, mode) + "▄"
            else:
                line += fg(t, mode) + bg(b, mode) + "▀"
        out.append(line + RESET)
    return out


# --- state ------------------------------------------------------------------

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


def _safe_conv(value: object) -> str:
    return _SAFE_ID.sub("", str(value or ""))[:80]


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: str, data: dict) -> None:
    parent = os.path.dirname(path)
    tmp = os.path.join(parent, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    try:
        os.makedirs(parent, mode=0o700, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data))
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def quota_status(payload: dict, home: str, now: float) -> tuple[bool, float | None]:
    """(out of quota?, when it comes back as a unix time or None).

    Out of quota when every enabled bucket in the payload is used up, or when
    the hook recorded a quota error for the active model (limits.json).
    """
    resets: list[float] = []
    buckets = payload.get("quota")
    enabled = exhausted = 0
    if isinstance(buckets, dict):
        for bucket in buckets.values():
            if not isinstance(bucket, dict) or bucket.get("disabled") is True:
                continue
            left = _num(bucket.get("remaining_fraction"))
            if left is None:
                left = _num(bucket.get("remaining_amount"))
            if left is None:
                continue
            enabled += 1
            if left <= 0:
                exhausted += 1
                secs = _num(bucket.get("reset_in_seconds"))
                if secs is not None and secs > 0:
                    resets.append(now + secs)
    if enabled and exhausted == enabled:
        return True, max(resets) if resets else None

    limits = _read_json(os.path.join(home, "limits.json"))
    models = limits.get("models")
    key = str(limits.get("activeKey") or "")
    if isinstance(models, dict) and key and isinstance(models.get(key), dict):
        entry = models[key]
        until = _num(entry.get("until"))
        if entry.get("limited") and until is not None and until > now:
            return True, until
    return False, None


def _fmt_time(when: float, now: float) -> str:
    t = time.localtime(when)
    if when - now < 20 * 3600:
        return time.strftime("%H:%M", t)
    return time.strftime("%a %H:%M", t)


def resolve(payload: dict, home: str = HOME, now: float | None = None, remember: bool = True) -> dict:
    """Pick Atom's state, mood and detail text from the payload + hook files."""
    now = time.time() if now is None else now
    conv = _safe_conv(payload.get("conversation_id") or payload.get("session_id"))
    agent_state = str(payload.get("agent_state") or "idle")
    busy = agent_state in BUSY_AGENT_STATES

    hook = _read_json(os.path.join(home, "convs", f"{conv}.json")) if conv else {}
    hook_ts = _num(hook.get("ts")) or 0.0
    hook_fresh = now - hook_ts < HOOK_STATE_TTL_SEC
    hook_state = str(hook.get("state") or "") if hook_fresh else ""
    mood = hook.get("mood") if hook_fresh and hook.get("mood") in ("angry", "sad") else None

    emotion = _read_json(os.path.join(home, "emotion.json"))
    emo = str(emotion.get("emotion") or "")
    emo_ts = _num(emotion.get("ts")) or 0.0
    emo_fresh = now - emo_ts < EMOTION_TTL_SEC

    mem_path = os.path.join(home, "cli", f"{conv}.json") if conv else ""
    memory = _read_json(mem_path) if mem_path else {}
    was_busy = bool(memory.get("busy"))
    reaction = str(memory.get("reaction") or "")
    reaction_ts = _num(memory.get("reaction_ts")) or 0.0

    subagents = payload.get("subagents")
    running_subagents = 0
    if isinstance(subagents, list):
        running_subagents = sum(1 for s in subagents if isinstance(s, dict) and s.get("status") == "running")
    tasks = int(_num(payload.get("task_count")) or 0)

    state, detail = "idle", ""
    if payload.get("tool_confirmation_pending") is True:
        state, detail = "approval", "approve or deny the prompt above"
    elif agent_state == "error":
        state = "error"
    elif agent_state in ("authenticating", "initializing"):
        state = "waking"
    elif busy:
        if hook_state in BUSY_HOOK_STATES:
            state = hook_state
        elif running_subagents:
            state = "delegating"
        elif agent_state == "tool_use":
            state = "working"
        elif agent_state == "reviewing":
            state = "reviewing"
        else:
            state = "thinking"
        if state == "delegating" and running_subagents:
            detail = f"{running_subagents} subagent{'s' if running_subagents != 1 else ''} running"
        if emo == "happy" and emo_fresh and not mood:
            mood = "happy"
    else:
        # Idle. A turn that just ended gets a reaction that sticks around
        # until the next turn: the status line only redraws on state changes.
        if was_busy:
            reaction = emo if emo in REACTIONS and emo_fresh else "done"
            reaction_ts = now
        elif reaction and emo in REACTIONS and emo_fresh and emo_ts > reaction_ts:
            # The Stop hook can land just after the status line first redrew.
            reaction, reaction_ts = emo, now
        if reaction and now - reaction_ts > REACTION_TTL_SEC:
            reaction = ""
        if reaction in REACTIONS:
            state = reaction
        elif tasks or hook_state == "watching":
            state = "watching"
        if tasks:
            detail = f"{tasks} background task{'s' if tasks != 1 else ''}"

    out_of_quota, back_at = quota_status(payload, home, now)
    if out_of_quota and not busy and state not in ("approval", "error"):
        state = "sleeping"
        detail = f"back at {_fmt_time(back_at, now)}" if back_at else "waiting for quota to reset"

    if remember and mem_path:
        _write_json(mem_path, {
            "busy": busy,
            "reaction": "" if busy else reaction,
            "reaction_ts": 0 if busy else reaction_ts,
            "ts": now,
        })

    return {"state": state, "mood": mood, "detail": detail}


def _look_state(info: dict) -> str:
    """Which LOOKS entry to draw: mood wins over plain busy/idle looks."""
    state, mood = info["state"], info.get("mood")
    if mood and state not in ("approval", "error", "sleeping", "waking"):
        return mood
    return state


def render(info: dict, width: int, style: str = "auto", mode: str = "truecolor") -> str:
    state = info["state"]
    look = _look_state(info)
    label = LABELS.get(state, state)
    if look in ("angry", "sad") and state == "idle":
        label = LABELS[look]
    detail = info.get("detail") or ""
    colour = LOOKS.get(look, LOOKS["idle"])[3]
    bold = "" if mode == "none" else "\x1b[1m"
    dim = "" if mode == "none" else "\x1b[2m"
    reset = "" if mode == "none" else RESET

    if style == "auto":
        style = "sprite" if width >= SPRITE_MIN_WIDTH else "line"
    if mode == "none":
        style = "line"  # the sprite is made of colour

    if style == "line":
        eyes = LOOKS.get(look, LOOKS["idle"])[0]
        body = _tinted(BODY_RGB, LOOKS.get(look, LOOKS["idle"])[2], "body")
        face = FACES.get(eyes, FACES["open"])
        if mode == "none":
            head = f"[{face}]"
        else:
            head = bg(body, mode) + fg(EYE_RGB, mode) + f" {face} " + reset
        text = f"{head} {bold}Atom{reset} · {fg(colour, mode)}{label}{reset}"
        if detail:
            text += f" {dim}· {detail}{reset}"
        return text

    lines = sprite_lines(look, mode)
    text = [""] * len(lines)
    text[1] = f"  {bold}Atom{reset} · {fg(colour, mode)}{label}{reset}"
    if detail:
        text[2] = f"  {dim}{detail}{reset}"
    return "\n".join((s + t).rstrip() for s, t in zip(lines, text))


# --- entry point ------------------------------------------------------------

def _parse_args(argv: list[str]) -> dict:
    opts = {"style": "auto", "color": "", "demo": False}
    it = iter(argv)
    for arg in it:
        if arg == "--demo":
            opts["demo"] = True
        elif arg in ("--style", "--color"):
            opts[arg[2:]] = next(it, "")
        elif arg.startswith("--style="):
            opts["style"] = arg.split("=", 1)[1]
        elif arg.startswith("--color="):
            opts["color"] = arg.split("=", 1)[1]
    if opts["style"] not in ("auto", "sprite", "line"):
        opts["style"] = "auto"
    if opts["color"] not in ("truecolor", "256", "none"):
        opts["color"] = os.environ.get("ATOM_COLOR", "") or "truecolor"
        if opts["color"] not in ("truecolor", "256", "none"):
            opts["color"] = "truecolor"
    if os.environ.get("NO_COLOR"):
        opts["color"] = "none"
    return opts


def demo(opts: dict) -> str:
    blocks = []
    examples = [
        ("idle", None, ""), ("thinking", None, ""), ("typing", None, ""),
        ("running", None, ""), ("exploring", None, ""), ("delegating", None, "2 subagents running"),
        ("approval", None, "approve or deny the prompt above"), ("asking", None, ""),
        ("done", None, ""), ("thinking", "happy", ""), ("error", None, ""), ("canceled", None, ""),
        ("tired", None, ""), ("thinking", "angry", ""), ("thinking", "sad", ""),
        ("waking", None, ""), ("sleeping", None, "back at 14:30"), ("watching", None, "1 background task"),
    ]
    for state, mood, detail in examples:
        blocks.append(render({"state": state, "mood": mood, "detail": detail}, 120, opts["style"], opts["color"]))
    return "\n\n".join(blocks)


def main(argv: list[str] | None = None) -> None:
    opts = _parse_args(sys.argv[1:] if argv is None else argv)
    if opts["demo"]:
        sys.stdout.write(demo(opts) + "\n")
        return

    fallback = "Atom"

    def bail() -> None:
        try:
            sys.stdout.write(fallback + "\n")
            sys.stdout.flush()
        finally:
            os._exit(0)

    watchdog = threading.Timer(WATCHDOG_SEC, bail)
    watchdog.daemon = True
    watchdog.start()
    out = fallback
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
        width = int(_num(payload.get("terminal_width")) or 80)
        out = render(resolve(payload), width, opts["style"], opts["color"])
    except Exception:
        out = fallback
    finally:
        watchdog.cancel()
    sys.stdout.write(out + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
