#!/usr/bin/env python3
"""Turn Atom on (or off) in Antigravity CLI.

Adds Atom as the CLI's custom status line, using the documented `statusLine`
block in ~/.gemini/antigravity-cli/settings.json
(https://antigravity.google/docs/cli/statusline/). Nothing else in
settings.json changes.

By default Atom takes over the CLI's status line (redrawing its mode/model
info) and can switch between a one-line "bar" view and a "big" pixel view.
Setup installs a small `atom-toggle` command (in ~/.local/bin) for that, so
inside agy you can type `! atom-toggle`.

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
  --style switch        (default) bar or big view, switched with atom-toggle
  --style bar|big       always the one-line bar / always the big view
  --style auto|sprite|line   pixel Atom / one line, stacked under agy's line
  --bin DIR             where to put atom-toggle (default ~/.local/bin)
  --color truecolor|256|none
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
STYLES = ("switch", "bar", "big", "auto", "sprite", "line")
# Styles that replace agy's own status line (they redraw its info).
REPLACING_STYLES = ("switch", "bar", "big")
TOGGLE_NAME = "atom-toggle"


def default_bin_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".local", "bin")


def _is_our_toggle(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return MARKER in fh.read(4096)
    except (OSError, UnicodeDecodeError):
        return False


def install_toggle(bin_dir: str, python: str = "python3") -> str | None:
    """Write `atom-toggle` into bin_dir. Returns its path, or None when it
    wasn't written (Windows, or a different program already has the name)."""
    if os.name == "nt":
        return None
    path = os.path.join(bin_dir, TOGGLE_NAME)
    if os.path.exists(path) and not _is_our_toggle(path):
        return None
    os.makedirs(bin_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "#!/bin/sh\n"
            "# Switch Atom between its big and bar views in Antigravity CLI.\n"
            "# Written by atom_cli_setup.py; removed by atom_cli_setup.py --uninstall.\n"
            f"exec {python} -S -I {shlex.quote(STATUS_SCRIPT)} --toggle \"$@\"\n"
        )
    os.chmod(path, 0o755)
    return path


def remove_toggle(bin_dir: str) -> bool:
    path = os.path.join(bin_dir, TOGGLE_NAME)
    if os.path.isfile(path) and _is_our_toggle(path):
        os.unlink(path)
        return True
    return False


def _on_path(directory: str) -> bool:
    target = os.path.normcase(os.path.abspath(directory))
    return any(
        os.path.normcase(os.path.abspath(os.path.expanduser(p))) == target
        for p in os.environ.get("PATH", "").split(os.pathsep) if p
    )


def toggle_command(python: str = "python3") -> str:
    script = f'"{STATUS_SCRIPT}"' if os.name == "nt" else shlex.quote(STATUS_SCRIPT)
    return f"{python} -S -I {script} --toggle"


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


def install(
    path: str,
    command: str,
    force: bool = False,
    dry_run: bool = False,
    stack: bool = False,
    bin_dir: str | None = None,
    python: str = "python3",
) -> int:
    try:
        data = load_settings(path)
    except (OSError, ValueError) as exc:
        print(f"Can't read {path}: {exc}\nFix or move it, then run this again. Nothing was changed.", file=sys.stderr)
        return 1

    existing = data.get("statusLine")
    block = {"type": "command", "command": command, "stack_with_default": stack}
    if is_atom_block(existing):
        # Keep the user's own tweaks (padding, enabled...) but refresh the command.
        block = {**existing, **block}
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
    if bin_dir:
        toggle = install_toggle(bin_dir, python)
        if toggle and _on_path(bin_dir):
            print(
                "\nSwitch between the bar and the big Atom inside agy: type ! on its own (the\n"
                f"prompt turns into a blue !), then {TOGGLE_NAME} and Enter."
            )
        else:
            if toggle:
                print(f"\n(wrote {toggle}, but {bin_dir} isn't on your PATH)")
            print(
                "\nSwitch between the bar and the big Atom inside agy: type ! on its own (the\n"
                f"prompt turns into a blue !), then:\n  {toggle_command(python)}"
            )
    print("\nRestart agy (or run /statusline enable) to see Atom.")
    return 0


def uninstall(path: str, dry_run: bool = False, bin_dir: str | None = None) -> int:
    try:
        data = load_settings(path)
    except (OSError, ValueError) as exc:
        print(f"Can't read {path}: {exc}. Nothing was changed.", file=sys.stderr)
        return 1
    if bin_dir and not dry_run and remove_toggle(bin_dir):
        print(f"Removed {os.path.join(bin_dir, TOGGLE_NAME)}")
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
    opts = {
        "settings": default_settings_path(), "python": "python3", "style": "switch",
        "color": "", "skin": "", "bin": default_bin_dir(),
    }
    flags = set()
    it = iter(args)
    for arg in it:
        if arg in ("-h", "--help"):
            print(__doc__)
            return 0
        if arg in ("--uninstall", "--force", "--dry-run"):
            flags.add(arg)
        elif arg in ("--settings", "--python", "--style", "--color", "--skin", "--bin"):
            value = next(it, None)
            if value is None:
                print(f"{arg} needs a value", file=sys.stderr)
                return 2
            opts[arg[2:]] = value
        else:
            print(f"Unknown option: {arg} (see --help)", file=sys.stderr)
            return 2
    if opts["style"] not in STYLES:
        print(f"--style must be one of: {', '.join(STYLES)}", file=sys.stderr)
        return 2
    if opts["color"] not in ("", "truecolor", "256", "none"):
        print("--color must be truecolor, 256 or none", file=sys.stderr)
        return 2
    if opts["skin"] not in ("",) + SKIN_IDS:
        print(f"--skin must be one of: {', '.join(SKIN_IDS)}", file=sys.stderr)
        return 2

    path = os.path.expanduser(opts["settings"])
    bin_dir = os.path.expanduser(opts["bin"])
    if "--uninstall" in flags:
        return uninstall(path, dry_run="--dry-run" in flags, bin_dir=bin_dir)
    style = opts["style"]
    command = build_command(opts["python"], style, opts["color"], opts["skin"])
    return install(
        path,
        command,
        force="--force" in flags,
        dry_run="--dry-run" in flags,
        stack=style not in REPLACING_STYLES,
        bin_dir=bin_dir if style == "switch" else None,
        python=opts["python"],
    )


if __name__ == "__main__":
    sys.exit(main())
