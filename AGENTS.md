# AGENTS.md — Guide for AI Agents & Contributors

This repository ships **Atom**, an open-source, stdlib-only prompt-bar mascot for the **Antigravity desktop app**.

## Fast Install (for AI agents helping a user install Atom)

- **Linux / macOS:** `curl -fsSL https://raw.githubusercontent.com/Arnav8452/atom/main/install.sh | bash`
- **Windows (PowerShell):** `irm https://raw.githubusercontent.com/Arnav8452/atom/main/install.ps1 | iex`
- **Verify installation:** check `~/.gemini/config/plugins/atom/hooks.json` (Windows: `%USERPROFILE%\.gemini\config\plugins\atom\hooks.json`) and run `python3 -m unittest discover -s tests -v`.
- **Antigravity CLI (`agy`):** `agy plugin install https://github.com/Arnav8452/atom`, then `python3 ~/.gemini/config/plugins/atom/atom_cli_setup.py`, then restart `agy`. If desktop Atom is installed, only the second command is needed. Switching views: the user types `!` alone (shell mode), then `atom-toggle`. See `CLI.md`.
- **Activate:** quit Antigravity completely and reopen it via the installed launcher (`antigravity.desktop`, `~/Applications/Antigravity (Atom).app`, Start Menu/Desktop shortcut, or `python3 atom_launch.py`).

## Architecture

- `atom_hook.py`: Synchronous hook command triggered by `hooks.json` via `python3 -S -I ./atom_hook.py` on `SessionStart`, `PreInvocation`, `PreToolUse`, `PostToolUse`, `PostInvocation`, and `Stop`. Writes state/mood/limit files under `~/.antigravity-atom` (or `$ATOM_HOME`) and wakes the launcher over `notify.sock` / loopback UDP `notify.port`.
- `atom_launch.py`: Launches Antigravity with `--remote-debugging-pipe` (POSIX inherited file descriptors) or loopback `--remote-debugging-port` (Windows stdlib `WsCdp`), injects the compact bootstrap script (`atom_inject.js`), and lazily pushes per-state WebP sheets via `window.__atom.__loadState`.
- `atom_status.py` (Antigravity CLI): the CLI's documented custom `statusLine` command. Reads the status line JSON on stdin plus the hook's state files and prints the one-line bar (default, replacing the CLI's line and redrawing its mode/model info) or the big half-block pixel Atom, switched with `atom-toggle` (`--toggle`, state in `cli/view.json`). Skins mirror `assets/<id>` (V2 default). Must stay stdlib-only, `-S -I` safe, always exit `0` with output, and never store or print the payload's `email`, title, paths or prompts. See `CLI.md`.
- `atom_cli_setup.py` (Antigravity CLI): adds/removes Atom's `statusLine` block in `~/.gemini/antigravity-cli/settings.json`. It never overwrites a user's own status line without `--force` and never rewrites a settings file it can't parse. The CLI version must only use documented extension points (hooks, status line), and never wrap, launch or inject into `agy`.
- `atom_inject.js`: Shadow DOM `<canvas>` renderer mounted only on localhost pages containing `[data-testid="agent-input-box"]`, handling 60fps crossfades, mood tint/eye tilt, and per-model quota sleep/wake-up.

## Non-Negotiable Invariants

1. **Zero third-party runtime dependencies:** `atom_hook.py`, `atom_launch.py`, `atom_status.py`, `atom_cli_setup.py`, and `install.sh` / `install.ps1` must stay 100% Python 3 stdlib / POSIX shell / built-in PowerShell (optional Pillow/cairo/ffmpeg are for `tools/` asset authoring only).
2. **Hook isolation & stdout contract:** `atom_hook.py` must run cleanly under `python3 -S -I` and exit `0`. **`PreToolUse` must NEVER write to `stdout`**: Antigravity reads any JSON there as a decision, and even `{}` means *deny*, which blocks every tool call. Known non-`PreToolUse` events write `{}`; an unknown event writes nothing. Each `hooks.json` command passes its event name as `argv[1]` (`./atom_hook.py PreToolUse`), because older Antigravity builds omit `hookEventName` from the payload. The hook must **fail open**: a PreToolUse hook that exits non-zero or times out blocks the tool call, so every command ends with `|| exit 0` (valid in both `sh` and `cmd`) and `atom_hook.py` has a watchdog (`WATCHDOG_SEC`) that exits `0` silently well before the `hooks.json` timeout.
3. **Bootstrap size & CSP safety:** `atom_launch.build_bootstrap_script()` must stay lightweight (`< 36,000` bytes) with zero embedded WebP/base64 sprites, and never rely on `Runtime.enable`, `Runtime.addBinding`, or `<img src="data:...">`.
4. **Local-only security & privacy:** Zero network calls or telemetry. Only attach to local hub targets (`127.0.0.1` / `localhost`). Never write user prompts or secrets into state files (`~/.antigravity-atom`). Quota DOM scanning in `atom_inject.js` must never trigger from chat transcript text.
5. **Preserve original artwork:** Never delete or overwrite source assets in `art/`.

## Verification Commands

Always run all checks before committing:

```bash
python3 -m py_compile atom_hook.py atom_launch.py atom_status.py atom_cli_setup.py tools/render_all.py tools/render_gemini_typing.py tools/render_idle.py tools/render_moodboard.py tools/make_sprite.py tools/trigger_state.py tools/render_gallery.py
bash -n install.sh tools/build_assets.sh packaging/aur/PKGBUILD packaging/aur/antigravity-atom-git.install
python3 -c 'import atom_launch, subprocess; s=atom_launch.build_bootstrap_script(); assert len(s) < 36000; subprocess.run(["node", "--check", "-"], input=s, text=True, check=True)'
python3 -m unittest discover -s tests -v
node --test tests/test_atom_inject.mjs
```

## Regenerating Visual Assets

- Rebuild all 19 state sheets: `./tools/build_assets.sh` (runs `tools/render_all.py`).
- Rebuild showcase GIF/WebP: `python3 tools/render_moodboard.py --proof /tmp/atom_moodboard_proof.png`.
- Website gallery (every state of every skin as GIF, plus artwork listed in `site/gallery.json`): built by `tools/render_gallery.py` in the Pages workflow; never commit its output.
