#!/usr/bin/env python3
"""Turn Atom on (or off) in Antigravity CLI.

Adds Atom as the CLI's custom status line, using the documented `statusLine`
block in ~/.gemini/antigravity-cli/settings.json
(https://antigravity.google/docs/cli/statusline/), stacked under the CLI's
own status line. Nothing else in settings.json changes.

Atom's reactions come from its plugin hooks. If the plugin isn't installed
yet, this prints the `agy plugin install` command to run; it doesn't run it.

Usage:
  python3 atom_cli_setup.py                 turn Atom on
  python3 atom_cli_setup.py --uninstall     turn Atom off (restores any
                                            status line Atom replaced)
  python3 atom_cli_setup.py --dry-run       show what would be written
Options:
  --force               replace a status line you already have (it is saved
                        and put back by --uninstall)
  --skin v2|atom|chibi|base-qt   (default v2)
  --style auto|sprite|line   --color truecolor|256|none
  --python CMD          interpreter to run (default: python3)
  --settings PATH       settings.json to edit (default: the CLI's)

Stdlib only.
"""

from __future__ import annotations

import json
import os
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS_SCRIPT = os.path.join(HERE, "atom_status.py")
MARKER = "atom_status.py"
# Same ids as atom_status.SKINS (v2 is the default, so it needs no flag).
SKIN_IDS = ("v2", "atom", "chibi", "base-qt")


def default_settings_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".gemini", "antigravity-cli", "settings.json")


def atom_home() -> str:
    return os.environ.get("ATOM_HOME") or os.path.join(os.path.expanduser("~"), ".antigravity-atom")


def plugin_installed() -> bool:
    plugin = os.path.join(os.path.expanduser("~"), ".gemini", "config", "plugins", "atom")
    return os.path.isfile(os.path.join(plugin, "hooks.json")) and os.path.isfile(os.path.join(plugin, "atom_hook.py"))


def build_command(
    python: str = "python3", style: str = "auto", color: str = "", skin: str = "", windows: bool | None = None
) -> str:
    windows = os.name == "nt" if windows is None else windows
    if windows:
        # The CLI runs the command with `cmd /c`; double quotes are what cmd understands.
        script = f'"{STATUS_SCRIPT}"'
    else:
        script = shlex.quote(STATUS_SCRIPT)
    cmd = f"{python} -S -I {script}"
    if style and style != "auto":
        cmd += f" --style {style}"
    if color:
        cmd += f" --color {color}"
    if skin:
        cmd += f" --skin {skin}"
    return cmd


def is_atom_block(block: object) -> bool:
    return isinstance(block, dict) and MARKER in str(block.get("command") or "")


def load_settings(path: str) -> dict:
    """The parsed settings, {} when the file doesn't exist. Raises ValueError
    on a file that isn't a JSON object, so it is never overwritten."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as fh:
        text = fh.read()
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("settings.json is not a JSON object")
    return data


def save_settings(path: str, data: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.atom-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def backup_once(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    backup = f"{path}.atom-backup"
    if not os.path.exists(backup):
        with open(path, "rb") as src, open(backup, "wb") as dst:
            dst.write(src.read())
    return backup


def _previous_path() -> str:
    return os.path.join(atom_home(), "cli", "previous_statusline.json")


def install(path: str, command: str, force: bool = False, dry_run: bool = False) -> int:
    try:
        data = load_settings(path)
    except (OSError, ValueError) as exc:
        print(f"Can't read {path}: {exc}\nFix or move it, then run this again. Nothing was changed.", file=sys.stderr)
        return 1

    existing = data.get("statusLine")
    block = {"type": "command", "command": command, "stack_with_default": True}
    if is_atom_block(existing):
        # Keep the user's own tweaks (padding, enabled...) but refresh the command.
        block = {**existing, **{"type": "command", "command": command}}
        block.setdefault("stack_with_default", True)
    elif existing not in (None, {}) and not force:
        print(
            "You already have a custom status line:\n"
            f"  {json.dumps(existing)}\n"
            "Atom didn't touch it. Run again with --force to replace it; it will be saved\n"
            "and `--uninstall` puts it back.",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        print(json.dumps({"statusLine": block}, indent=2))
        return 0

    if existing not in (None, {}) and not is_atom_block(existing):
        prev = _previous_path()
        os.makedirs(os.path.dirname(prev), mode=0o700, exist_ok=True)
        with open(prev, "w", encoding="utf-8") as fh:
            json.dump({"statusLine": existing}, fh)

    # A re-run only refreshes Atom's own block, so there's nothing of yours to back up.
    backup = None if is_atom_block(existing) else backup_once(path)
    data["statusLine"] = block
    save_settings(path, data)
    print(f"Atom is now the status line in {path}")
    if backup:
        print(f"(backup of your previous settings: {backup})")
    if not plugin_installed():
        print(
            "\nAtom's reactions come from its plugin hooks, which aren't installed yet. Run:\n"
            f"  agy plugin install {HERE}"
        )
    print("\nRestart agy (or run /statusline enable) to see Atom.")
    return 0


def uninstall(path: str, dry_run: bool = False) -> int:
    try:
        data = load_settings(path)
    except (OSError, ValueError) as exc:
        print(f"Can't read {path}: {exc}. Nothing was changed.", file=sys.stderr)
        return 1
    if not is_atom_block(data.get("statusLine")):
        print("Atom isn't the status line; nothing to do.")
        return 0

    prev_path = _previous_path()
    previous = None
    try:
        with open(prev_path, "r", encoding="utf-8") as fh:
            previous = json.load(fh).get("statusLine")
    except (OSError, ValueError, AttributeError):
        previous = None

    if dry_run:
        print(json.dumps({"statusLine": previous}, indent=2) if previous else "statusLine would be removed")
        return 0

    if previous:
        data["statusLine"] = previous
    else:
        data.pop("statusLine", None)
    save_settings(path, data)
    if previous:
        try:
            os.unlink(prev_path)
        except OSError:
            pass
        print("Atom is off; your previous status line is back.")
    else:
        print("Atom is off; the CLI's default status line is back.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    opts = {"settings": default_settings_path(), "python": "python3", "style": "auto", "color": "", "skin": ""}
    flags = set()
    it = iter(args)
    for arg in it:
        if arg in ("-h", "--help"):
            print(__doc__)
            return 0
        if arg in ("--uninstall", "--force", "--dry-run"):
            flags.add(arg)
        elif arg in ("--settings", "--python", "--style", "--color", "--skin"):
            value = next(it, None)
            if value is None:
                print(f"{arg} needs a value", file=sys.stderr)
                return 2
            opts[arg[2:]] = value
        else:
            print(f"Unknown option: {arg} (see --help)", file=sys.stderr)
            return 2
    if opts["style"] not in ("auto", "sprite", "line"):
        print("--style must be auto, sprite or line", file=sys.stderr)
        return 2
    if opts["color"] not in ("", "truecolor", "256", "none"):
        print("--color must be truecolor, 256 or none", file=sys.stderr)
        return 2
    if opts["skin"] not in ("",) + SKIN_IDS:
        print(f"--skin must be one of: {', '.join(SKIN_IDS)}", file=sys.stderr)
        return 2

    path = os.path.expanduser(opts["settings"])
    if "--uninstall" in flags:
        return uninstall(path, dry_run="--dry-run" in flags)
    command = build_command(opts["python"], opts["style"], opts["color"], opts["skin"])
    return install(path, command, force="--force" in flags, dry_run="--dry-run" in flags)


if __name__ == "__main__":
    sys.exit(main())
