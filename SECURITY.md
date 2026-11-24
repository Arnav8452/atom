# Security Policy

## Supported Versions

| Version / Branch | Supported |
| ---------------- | --------- |
| `main` (`1.x`)   | Yes       |

## Reporting a Vulnerability

Please **do not** report security vulnerabilities in public GitHub issues or pull requests.

Use GitHub's private advisory workflow:
- https://github.com/Arnav8452/atom/security/advisories/new

Include:
1. A clear description of the vulnerability and affected files (`atom_hook.py`, `atom_launch.py`, `atom_inject.js`, `install.sh`, `install.ps1`).
2. Steps to reproduce cleanly.
3. Impact assessment (what an attacker could read, overwrite, or execute).

You can expect an acknowledgment within **72 hours** and status updates until a fix and advisory are released.

## Security & Privacy Architecture

Atom is designed with minimal privilege and zero network footprint:

- **Zero network / telemetry:** Runtime components make no outbound HTTP/socket calls and collect no usage data or prompt history.
- **No third-party dependencies:** `atom_hook.py`, `atom_launch.py`, and the installers use only Python 3's standard library and built-in OS tools.
- **Isolated hook execution:** `hooks.json` invokes `python3 -S -I ./atom_hook.py` (user site-packages disabled, isolated mode). `PreToolUse` prints nothing to `stdout`, preserving Antigravity's built-in tool permission gates.
- **Local-only DevTools transport:**
  - **Linux & macOS:** Uses Chromium `--remote-debugging-pipe` over two inherited file descriptors held exclusively by the launcher process (no TCP port opened).
  - **Windows:** Uses loopback `--remote-debugging-port` bound locally via a stdlib WebSocket client (`WsCdp`).
- **Scoped DOM injection:** `atom_inject.js` attaches only to `http(s)://127.0.0.1:<port>/` or `http(s)://localhost:<port>/` hub pages, activates only when `[data-testid="agent-input-box"]` is present, renders inside a `closed` Shadow DOM, never uses `Runtime.enable` / `Runtime.addBinding`, and ignores chat transcript text during quota banner checks.
- **User-private local state:** `~/.antigravity-atom` (or `$ATOM_HOME`) directories and POSIX wakeup socket `notify.sock` are created with owner-only permissions (`0700` dirs / `0600` socket) and never store raw user messages.
