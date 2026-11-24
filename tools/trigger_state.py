#!/usr/bin/env python3
"""Trigger or preview any Atom mascot state (and mood combinations).

Usage:
  python3 tools/trigger_state.py angry
  python3 tools/trigger_state.py angry --mood             # angry thinking mood until idle
  python3 tools/trigger_state.py typing --mood angry      # live angry typing in Antigravity
  python3 tools/trigger_state.py thinking --mood sad      # live sad thinking in Antigravity
  python3 tools/trigger_state.py --tour                   # cycle through all 19 states
  python3 tools/trigger_state.py --tour --mood angry      # cycle all work states in angry mood
  python3 tools/trigger_state.py --tour-all               # normal -> angry work -> sad work
  python3 tools/trigger_state.py --gallery                # open browser grid of all 19 states x moods
  python3 tools/trigger_state.py --limit gemini-3-pro     # simulate 5h/weekly limit sleep
  python3 tools/trigger_state.py --clear-limit gemini-3-pro
  python3 tools/trigger_state.py --list                   # list all 19 supported states

Writes directly to ~/.antigravity-atom (or ATOM_HOME) and sends a wakeup ping
over notify.sock / notify.port so Atom reacts instantaneously.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import atom_hook  # noqa: E402
import atom_launch  # noqa: E402

WORK_STATES = ("thinking", "working", "exploring", "typing", "running", "delegating", "asking")


def trigger(state: str, conv_id: str = "preview", mood: str | None = None) -> None:
    now = time.time()
    home = Path(atom_hook.HOME)
    resolved_mood = state if (mood == "self" and state in atom_launch.SUSTAINED_MOODS) else mood
    if resolved_mood == "none":
        resolved_mood = None

    if mood == "self" and state in atom_launch.SUSTAINED_MOODS:
        atom_hook.write_json(
            str(home / "convs" / f"{conv_id}.json"),
            {"state": "thinking", "mood": state, "ts": now},
        )
    elif state == "closed":
        old = now - (atom_launch.SLEEP_AFTER_SEC + 30)
        for p in (home / "convs").glob("*.json"):
            atom_hook.write_json(str(p), {"state": "idle", "ts": old})
        atom_hook.write_json(str(home / "convs" / f"{conv_id}.json"), {"state": "idle", "ts": old})
        atom_hook.write_json(str(home / "emotion.json"), {"emotion": "none", "ts": old})
    elif state in atom_launch.BASE_STATES:
        data: dict[str, object] = {"state": state, "ts": now}
        if resolved_mood in atom_launch.SUSTAINED_MOODS:
            data["mood"] = resolved_mood
        atom_hook.write_json(str(home / "convs" / f"{conv_id}.json"), data)
    elif state in atom_launch.REACTIONS:
        atom_hook.write_json(str(home / "emotion.json"), {"emotion": state, "ts": now})
    else:
        raise SystemExit(f"Unknown state {state!r}. Valid: {', '.join(atom_launch.STATES)}")
    atom_hook.notify_launcher()
    suffix = f" (mood: {resolved_mood})" if resolved_mood in atom_launch.SUSTAINED_MOODS else ""
    print(f"[atom] triggered: {state}{suffix}")


def set_limit(model: str, limited: bool) -> None:
    atom_hook.update_model_limits(atom_hook.HOME, model, limited, time.time())
    atom_hook.notify_launcher()
    verb = "set" if limited else "cleared"
    print(f"[atom] limit {verb}: {model}")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def serve_gallery(port: int = 0, open_browser: bool = True) -> None:
    handler = functools.partial(_QuietHandler, directory=str(ROOT))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    actual_port = srv.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/tools/preview.html"
    print(f"[atom] gallery running at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[atom] gallery stopped")
    finally:
        srv.server_close()


def _run_steps(steps: list[tuple[str, str | None]], conv_id: str, delay: float) -> None:
    for st, md in steps:
        trigger(st, conv_id, mood=md)
        time.sleep(delay)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("state", nargs="?", help="State name to trigger")
    ap.add_argument("--conv", default="preview", help="Conversation file name to update")
    ap.add_argument(
        "--mood",
        nargs="?",
        const="self",
        choices=("self", "angry", "sad", "none"),
        help="Attach angry/sad turn mood (e.g. --mood angry, or --mood on angry/sad)",
    )
    ap.add_argument("--list", action="store_true", help="List all supported states")
    ap.add_argument("--tour", action="store_true", help="Cycle through states for live visual inspection")
    ap.add_argument("--tour-all", action="store_true", help="Cycle normal states, angry work states, and sad work states")
    ap.add_argument("--gallery", action="store_true", help="Serve interactive browser gallery of all 19 states x moods")
    ap.add_argument("--port", type=int, default=0, help="Port for --gallery (default: random free port)")
    ap.add_argument("--no-open", action="store_true", help="Do not open web browser automatically with --gallery")
    ap.add_argument("--limit", help="Simulate 5h/weekly quota limit reached on MODEL (puts Atom to sleep)")
    ap.add_argument("--clear-limit", help="Clear simulated quota limit for MODEL")
    ap.add_argument("--delay", type=float, default=2.5, help="Seconds per state during --tour/--tour-all")
    args = ap.parse_args()

    if args.list:
        print("Base states:", ", ".join(atom_launch.BASE_STATES))
        print("Reactions:  ", ", ".join(sorted(atom_launch.REACTIONS)))
        return

    if args.limit:
        set_limit(args.limit, True)
        return

    if args.clear_limit:
        set_limit(args.clear_limit, False)
        return

    if args.gallery:
        serve_gallery(port=args.port, open_browser=not args.no_open)
        return

    normal_tour: list[tuple[str, str | None]] = [
        (st, None)
        for st in (
            "idle", "thinking", "working", "exploring", "typing", "running",
            "delegating", "asking", "watching", "dance", "done", "happy", "sad",
            "angry", "error", "canceled", "tired", "idle",
        )
    ]

    if args.tour_all:
        steps = (
            normal_tour[:-1]
            + [(st, "angry") for st in WORK_STATES]
            + [(st, "sad") for st in WORK_STATES]
            + [("idle", None)]
        )
        _run_steps(steps, args.conv, args.delay)
        return

    if args.tour:
        if args.mood in atom_launch.SUSTAINED_MOODS:
            steps = [(st, args.mood) for st in WORK_STATES] + [("idle", None)]
        else:
            steps = normal_tour
        _run_steps(steps, args.conv, args.delay)
        return

    if not args.state:
        ap.error("Provide a state name, --tour, --tour-all, --gallery, or --list")
    trigger(args.state, args.conv, mood=args.mood)


if __name__ == "__main__":
    main()
