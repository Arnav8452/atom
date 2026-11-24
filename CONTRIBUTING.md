# Contributing to Atom

Thanks for helping improve **Atom**! Bug reports, performance improvements, packaging fixes, new animations, and extra skins are all welcome.

## Development Setup

No third-party packages are needed to run Atom or its test suites (only **Python 3** and **Node.js** for running `tests/test_atom_inject.mjs`).

```bash
git clone https://github.com/Arnav8452/atom.git atom
cd atom
```

If you want to modify or regenerate the rendered WebP sprite sheets or showcase GIF under `assets/`, install **cairo** (`pycairo`) and **ffmpeg** (`tools/build_assets.sh` / `tools/render_moodboard.py`), or Pillow for custom artwork (`tools/make_sprite.py`).

## Coding & Architecture Rules

Please keep these invariants intact (also summarized in [`AGENTS.md`](AGENTS.md)):

1. **Stdlib-only runtime:** Keep `atom_hook.py`, `atom_launch.py`, `install.sh`, and `install.ps1` free of external packages.
2. **Hook safety (`atom_hook.py`):** Must execute cleanly under `python3 -S -I`, always exit `0`, never print anything to `stdout` on `PreToolUse`, and write `{}` on other hook events.
3. **Lightweight bootstrap (`atom_inject.js`):** Keep `atom_launch.build_bootstrap_script()` under `36,000` bytes with zero embedded sprites or CSP-violating `<img src="data:...">` URLs.
4. **Localhost-only & privacy:** Never add telemetry, outbound network requests, or prompt logging to `~/.antigravity-atom`.
5. **Preserve original artwork:** Never delete or overwrite reference files in `art/`.

## Running Tests & Checks

Run the full check suite locally before submitting a pull request:

```bash
python3 -m py_compile atom_hook.py atom_launch.py tools/render_all.py tools/render_gemini_typing.py tools/render_idle.py tools/render_moodboard.py tools/make_sprite.py tools/trigger_state.py
bash -n install.sh tools/build_assets.sh packaging/aur/PKGBUILD packaging/aur/antigravity-atom-git.install
python3 -c 'import atom_launch, subprocess; s=atom_launch.build_bootstrap_script(); print(len(s)); assert len(s) < 36000; subprocess.run(["node", "--check", "-"], input=s, text=True, check=True)'
python3 -m unittest discover -s tests -v
node --test tests/test_atom_inject.mjs
```

## Pull Request Checklist

- Add or update unit tests in `tests/` matching your behavior change.
- Update `README.md` if you add or change user-facing states, CLI flags, or install steps.
- If changing sprite sheets, regenerate them with `./tools/build_assets.sh` and inspect visually.
- Fill out the PR template clearly (and link any related issue).

## Security Issues

Do **not** report security vulnerabilities in public issues. See [`SECURITY.md`](SECURITY.md).
