#!/usr/bin/env python3
"""Atom for Antigravity CLI: a custom status line command.

Antigravity CLI runs this through its documented `statusLine` setting
(https://antigravity.google/docs/cli/statusline/) whenever the agent state
changes, with the session state as JSON on stdin. Whatever this prints to
stdout is shown as the status line: with `--style bar` it replaces the CLI's
own line (rebuilding its mode/model info) with Atom at the end; the other
styles stack under it (`stack_with_default`).

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
  atom_status.py --style bar         one line that replaces agy's status line:
                                     its mode/model on the left, Atom at the end
  atom_status.py --style big         agy's mode/model line with the pixel Atom
                                     under it
  atom_status.py --style switch      big or bar, whichever was picked last:
  atom_status.py --toggle            switch between them (atom-toggle runs this)
  atom_status.py --view big|bar      pick one
  atom_status.py --style line        always a single line
  atom_status.py --color 256         for terminals without truecolor
  atom_status.py --skin atom         another skin: v2 (default), atom, chibi,
                                     base-qt (or set ATOM_SKIN)
  atom_status.py --demo              print every state, for trying it out
  atom_status.py --demo --skin all   print every skin
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
BAR_MARGIN = 2  # columns left free at the right end in the `bar` style
HOOK_STATE_TTL_SEC = 15 * 60  # hook state older than this is ignored
EMOTION_TTL_SEC = 45  # how long an emotion.json reaction counts as fresh
REACTION_TTL_SEC = 15 * 60  # how long "done"/"error"/... stays after a turn

BUSY_HOOK_STATES = frozenset({"thinking", "typing", "working", "exploring", "running", "delegating", "asking"})
BUSY_AGENT_STATES = frozenset({"working", "tool_use", "reviewing", "thinking"})
REACTIONS = frozenset({"done", "error", "canceled", "tired"})

# --- art --------------------------------------------------------------------
# Each skin is a small pixel grid drawn with half blocks (2 pixels per line).
# Skin ids match the desktop skins in assets/<id>/. Grid characters:
#   . transparent   c crown/beanie (rainbow by column)   any other letter:
#   a colour from the skin's palette. Letters in "body" take mood tints
#   (like the desktop's blue-only recolour); the rest only dim when asleep.
ATOM_RAINBOW = (
    (255, 84, 84),
    (255, 150, 60),
    (250, 214, 70),
    (96, 214, 120),
    (60, 196, 232),
    (112, 124, 255),
    (196, 96, 232),
)
# V2 / Chibi beanie stripes, left to right (from assets/v2).
BEANIE_RAINBOW = (
    (146, 148, 251),
    (62, 224, 236),
    (84, 240, 154),
    (252, 228, 104),
    (254, 150, 88),
    (254, 118, 148),
    (220, 110, 220),
)
PINK = (255, 140, 180)
WATER = (150, 220, 255)

SKINS = {
    "v2": {
        "name": "Atom V2",
        "grid": (
            ".......PP.......",
            ".....cccccc.....",
            "...cccccccccc...",
            "..cccccccccccc..",
            "..KKKKKKKKKKKK..",
            "..BBBBBBBBBBBB..",
            "..BBBBBBBBBBBB..",
            "..BBBBBBBBBBBB..",
            ".DBBBBBBBBBBBBD.",
            ".DBBBBBBBBBBBBD.",
            "..BBBBBBBBBBBB..",
            "...BBBBBBBBBB...",
            "....BBBBBBBB....",
        ),
        "palette": {"B": (40, 186, 248), "D": (32, 108, 168), "K": (32, 108, 168), "P": (100, 248, 255)},
        "body": "BD",
        "crown": BEANIE_RAINBOW,
        "eyes": ((4, 6), (10, 6)),
        "extras": {
            "blush": ((3, 8, PINK), (12, 8, PINK)),
            "tear": ((4, 9, WATER),),
            "sweat": ((14, 2, WATER), (14, 3, WATER)),
        },
    },
    "atom": {
        "name": "Atom",
        "grid": (
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
        ),
        "palette": {"B": (44, 140, 232), "D": (30, 104, 196)},
        "body": "BD",
        "crown": ATOM_RAINBOW,
        "eyes": ((4, 2), (10, 2)),
        "extras": {
            "blush": ((3, 4, PINK), (12, 4, PINK)),
            "tear": ((4, 5, WATER),),
            "sweat": ((14, 1, WATER), (14, 2, WATER)),
        },
    },
    "chibi": {
        "name": "Cozy Chibi",
        "grid": (
            ".......PP.......",
            "..E..cccccc..E..",
            "..EEcccccccccEE.",
            "..cccccccccccc..",
            "..KKKKKKKKKKKK..",
            ".WWWBBBBBBBBWWW.",
            ".WWBBBBBBBBBBWW.",
            ".WWBBBBBBBBBBWW.",
            ".WWWBBBBBBBBWWW.",
            "..CCCCCCCCCCCC..",
            ".CCCCCCCCCCCCCC.",
            ".BCCCGGGGGGCCCB.",
            "..CCCCCCCCCCCC..",
            "...DD......DD...",
        ),
        "palette": {
            "B": (40, 186, 248), "D": (32, 108, 168), "K": (40, 120, 150), "P": (100, 248, 255),
            "E": (205, 210, 222), "W": (226, 230, 240), "C": (250, 236, 200), "G": (226, 206, 160),
        },
        "body": "BD",
        "crown": BEANIE_RAINBOW,
        "eyes": ((5, 6), (9, 6)),
        "extras": {
            "blush": ((4, 8, PINK), (11, 8, PINK)),
            "tear": ((4, 8, WATER),),
            "sweat": ((15, 3, WATER), (15, 4, WATER)),
        },
    },
    "base-qt": {
        "name": "base qt.",
        "grid": (
            "..BBBBBBBBBBBB..",
            "..BBBBBBBBBBBB..",
            "..BBBBBBBBBBBB..",
            "..BBBBBBBBBBBB..",
            ".BBBBBBBBBBBBBB.",
            "BB.BBBBBBBBBB.BB",
            "...BBBBBBBBBB...",
            "...DDDDDDDDDD...",
        ),
        "palette": {"B": (44, 140, 232), "D": (30, 104, 196)},
        "body": "BD",
        "crown": (),
        "eyes": ((4, 1), (10, 1)),
        "extras": {
            "blush": ((3, 3, PINK), (12, 3, PINK)),
            "tear": ((4, 4, WATER),),
            "sweat": ((14, 0, WATER), (14, 1, WATER)),
        },
    },
}
DEFAULT_SKIN = "v2"

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
EYE_RGB = (10, 14, 20)


def get_skin(name: object) -> dict:
    return SKINS.get(str(name or ""), SKINS[DEFAULT_SKIN])


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def _crown(colours: tuple, col: int, first: int, last: int) -> tuple:
    span = max(1, last - first)
    pos = max(0.0, min(1.0, (col - first) / span)) * (len(colours) - 1)
    i = min(int(pos), len(colours) - 2)
    return _mix(colours[i], colours[i + 1], pos - i)


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
    if tint in ("sleep", "dim"):
        return _mix(rgb, (20, 24, 34), 0.5 if tint == "sleep" else 0.3)
    if part == "other" or (part == "crown" and tint in ("angry", "sad")):
        return rgb  # like the desktop: moods recolour the blue body only
    if tint == "angry":
        return _mix(rgb, (230, 60, 70), 0.45)
    if tint == "sad":
        grey = (sum(rgb) // 3,) * 3
        return _mix(_mix(rgb, grey, 0.6), (70, 90, 140), 0.2)
    if tint == "error":
        return (235, 70, 70) if part == "crown" else _mix(rgb, (120, 40, 60), 0.25)
    if tint == "approval":
        return (250, 214, 70) if part == "crown" else rgb
    return rgb


def sprite_pixels(state: str, skin: str = DEFAULT_SKIN) -> list[list[tuple | None]]:
    sk = get_skin(skin)
    rows = sk["grid"]
    width, height = len(rows[0]), len(rows)
    eyes, extras, tint, _ = LOOKS.get(state, LOOKS["idle"])
    crown_cols = [x for row in rows for x, ch in enumerate(row) if ch == "c"]
    first, last = (min(crown_cols), max(crown_cols)) if crown_cols else (0, 0)
    grid: list[list[tuple | None]] = []
    for row in rows:
        line: list[tuple | None] = []
        for x, ch in enumerate(row):
            if ch == "c" and sk["crown"]:
                line.append(_tinted(_crown(sk["crown"], x, first, last), tint, "crown"))
            elif ch in sk["palette"]:
                part = "body" if ch in sk["body"] else "other"
                line.append(_tinted(sk["palette"][ch], tint, part))
            else:
                line.append(None)
        grid.append(line)
    left, right = EYES[eyes]
    for (ox, oy), offsets in zip(sk["eyes"], (left, right)):
        for dx, dy in offsets:
            x, y = ox + dx, oy + dy
            if 0 <= y < height and 0 <= x < width and grid[y][x] is not None:
                grid[y][x] = EYE_RGB
    for name in extras:
        for x, y, rgb in sk["extras"].get(name, ()):
            if 0 <= y < height and 0 <= x < width:
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


def sprite_lines(state: str, mode: str, skin: str = DEFAULT_SKIN) -> list[str]:
    grid = sprite_pixels(state, skin)
    height, width = len(grid), len(grid[0])
    out = []
    for y in range(0, height, 2):
        top, bottom = grid[y], grid[y + 1] if y + 1 < height else [None] * width
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


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_EFFORT_SUFFIX = re.compile(r"\s*\(([^()]*)\)\s*$")


def visible_len(text: str) -> int:
    return len(_ANSI.sub("", text))


def agy_info(payload: dict) -> tuple[str, str]:
    """(mode, "model · effort"): what agy's own status line shows, rebuilt
    from the documented payload, for the `bar` style that replaces it."""
    mode = str(payload.get("cycle_mode") or "auto")
    agent = payload.get("agent")
    if isinstance(agent, dict) and agent.get("name"):
        mode = f"{mode} · {agent['name']}"
    model = payload.get("model")
    parts = []
    if isinstance(model, dict):
        name = str(model.get("display_name") or model.get("id") or "")
        effort = str(model.get("effort") or "")
        m = _EFFORT_SUFFIX.search(name)
        if m and effort and m.group(1).strip().lower() == effort.lower():
            name = name[: m.start()]
        if name:
            parts.append(name)
        if effort:
            parts.append(effort)
    return mode, " · ".join(parts)


def _truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _agy_left(bar_info: tuple[str, str], room: int, mode: str) -> str:
    """agy's "auto · Model · effort", cut to `room` columns: mode coloured
    like agy does, the rest dim."""
    agy_mode, _ = bar_info
    text = _truncate(" · ".join(p for p in bar_info if p), room)
    if not text:
        return ""
    if mode == "none":
        return text
    if agy_mode and text.startswith(agy_mode):
        return f"{fg((250, 170, 80), mode)}{agy_mode}{RESET}\x1b[2m{text[len(agy_mode):]}{RESET}"
    return f"\x1b[2m{text}{RESET}"


# --- big/bar view switch ----------------------------------------------------
VIEWS = ("bar", "big")
DEFAULT_VIEW = "bar"


def _view_path(home: str) -> str:
    return os.path.join(home, "cli", "view.json")


def read_view(home: str | None = None) -> str:
    view = _read_json(_view_path(home or HOME)).get("view")
    return view if view in VIEWS else DEFAULT_VIEW


def set_view(view: str, home: str | None = None) -> str:
    view = view if view in VIEWS else DEFAULT_VIEW
    _write_json(_view_path(home or HOME), {"view": view})
    return view


def render(
    info: dict,
    width: int,
    style: str = "auto",
    mode: str = "truecolor",
    skin: str = DEFAULT_SKIN,
    bar_info: tuple[str, str] = ("", ""),
) -> str:
    sk = get_skin(skin)
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

    if style == "switch":
        style = read_view()
    if style == "big":
        # agy's mode/model line, then the pixel Atom under it.
        if mode == "none" or width < SPRITE_MIN_WIDTH:
            style = "bar"
        else:
            agy_line = _agy_left(bar_info, max(10, width - BAR_MARGIN), mode)
            sprite = render(info, width, "sprite", mode, skin)
            return (agy_line + "\n" + sprite) if agy_line else sprite
    if style == "auto":
        style = "sprite" if width >= SPRITE_MIN_WIDTH else "line"
    if mode == "none" and style == "sprite":
        style = "line"  # the sprite is made of colour

    if style == "bar":
        # One line in place of agy's own status line: its mode/model info on
        # the left, a small Atom face at the right end.
        eyes = LOOKS.get(look, LOOKS["idle"])[0]
        body = _tinted(sk["palette"]["B"], LOOKS.get(look, LOOKS["idle"])[2], "body")
        face = FACES.get(eyes, FACES["open"])
        if mode == "none":
            head = f"[{face}]"
        else:
            head = fg(body, mode) + "▐" + bg(body, mode) + fg(EYE_RGB, mode) + face + reset + fg(body, mode) + "▌" + reset
        avail = max(10, width - BAR_MARGIN)
        # Label first, so the face stays pinned to the end of the line.
        right = f"{fg(colour, mode)}{label}{reset} {head}"
        with_detail = (f"{dim}{detail} ·{reset} " if detail else "") + right
        left_plain = " · ".join(p for p in bar_info if p)
        if visible_len(with_detail) + len(left_plain) + 2 <= avail:
            right = with_detail
        left = _agy_left(bar_info, avail - visible_len(right) - 2, mode)
        gap = max(1, avail - visible_len(left) - visible_len(right))
        return left + " " * gap + right

    if style == "line":
        eyes = LOOKS.get(look, LOOKS["idle"])[0]
        body = _tinted(sk["palette"]["B"], LOOKS.get(look, LOOKS["idle"])[2], "body")
        face = FACES.get(eyes, FACES["open"])
        if mode == "none":
            head = f"[{face}]"
        else:
            head = bg(body, mode) + fg(EYE_RGB, mode) + f" {face} " + reset
        text = f"{head} {bold}Atom{reset} · {fg(colour, mode)}{label}{reset}"
        if detail:
            text += f" {dim}· {detail}{reset}"
        return text

    lines = sprite_lines(look, mode, skin)
    text = [""] * len(lines)
    row = min(len(lines) - 1, sk["eyes"][0][1] // 2)  # label level with the eyes
    text[row] = f"  {bold}Atom{reset} · {fg(colour, mode)}{label}{reset}"
    if detail and row + 1 < len(text):
        text[row + 1] = f"  {dim}{detail}{reset}"
    return "\n".join((s + t).rstrip() for s, t in zip(lines, text))


# --- entry point ------------------------------------------------------------

def _parse_args(argv: list[str]) -> dict:
    opts = {"style": "auto", "color": "", "skin": "", "demo": False, "toggle": False, "view": ""}
    it = iter(argv)
    for arg in it:
        if arg in ("--demo", "--toggle"):
            opts[arg[2:]] = True
        elif arg in ("--style", "--color", "--skin", "--view"):
            opts[arg[2:]] = next(it, "")
        elif arg.startswith(("--style=", "--color=", "--skin=", "--view=")):
            key, value = arg[2:].split("=", 1)
            opts[key] = value
    if opts["skin"] not in SKINS and not (opts["demo"] and opts["skin"] == "all"):
        opts["skin"] = os.environ.get("ATOM_SKIN", "")
        if opts["skin"] not in SKINS:
            opts["skin"] = DEFAULT_SKIN
    if opts["style"] not in ("auto", "sprite", "line", "bar", "big", "switch"):
        opts["style"] = "auto"
    if opts["color"] not in ("truecolor", "256", "none"):
        opts["color"] = os.environ.get("ATOM_COLOR", "") or "truecolor"
        if opts["color"] not in ("truecolor", "256", "none"):
            opts["color"] = "truecolor"
    if os.environ.get("NO_COLOR"):
        opts["color"] = "none"
    return opts


def demo(opts: dict) -> str:
    if opts["skin"] == "all":
        blocks = []
        for name, sk in SKINS.items():
            blocks.append(f"── {sk['name']} ({name}){' · default' if name == DEFAULT_SKIN else ''}")
            blocks.append(render({"state": "idle", "mood": None, "detail": ""}, 120, opts["style"], opts["color"], name))
        return "\n\n".join(blocks)
    blocks = [f"── {SKINS[opts['skin']]['name']} ({opts['skin']})"]
    examples = [
        ("idle", None, ""), ("thinking", None, ""), ("typing", None, ""),
        ("running", None, ""), ("exploring", None, ""), ("delegating", None, "2 subagents running"),
        ("approval", None, "approve or deny the prompt above"), ("asking", None, ""),
        ("done", None, ""), ("thinking", "happy", ""), ("error", None, ""), ("canceled", None, ""),
        ("tired", None, ""), ("thinking", "angry", ""), ("thinking", "sad", ""),
        ("waking", None, ""), ("sleeping", None, "back at 14:30"), ("watching", None, "1 background task"),
    ]
    for state, mood, detail in examples:
        info = {"state": state, "mood": mood, "detail": detail}
        bar = ("auto", "Gemini 4 Neon · high")
        blocks.append(render(info, 100, opts["style"], opts["color"], opts["skin"], bar))
    return "\n\n".join(blocks)


def main(argv: list[str] | None = None) -> None:
    opts = _parse_args(sys.argv[1:] if argv is None else argv)
    if opts["toggle"] or opts["view"]:
        # Run by you (e.g. `! atom-toggle` inside agy), not by the CLI.
        if opts["view"] in VIEWS:
            view = set_view(opts["view"])
        else:
            view = set_view("big" if read_view() == "bar" else "bar")
        sys.stdout.write(f"Atom: {view} view. It shows the next time agy redraws its status line.\n")
        return
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
        out = render(resolve(payload), width, opts["style"], opts["color"], opts["skin"], agy_info(payload))
    except Exception:
        out = fallback
    finally:
        watchdog.cancel()
    sys.stdout.write(out + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
