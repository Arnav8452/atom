#!/usr/bin/env python3
"""Start the Antigravity app with Atom on its prompt bar.

Antigravity has no extension point for the chat UI, so this launcher starts
the app itself with Chromium's --remote-debugging-pipe: a DevTools channel on
two inherited file descriptors that only this process holds (no TCP port that
other local programs could reach). Over it, it:

  * finds the app's main window (the hub page served by the local language
    server) and adds atom_inject.js to it, re-adding it on every reload;
  * watches the state written by atom_hook.py and tells the page about it.

The app's lifetime is unchanged: this exits when the app does, with its exit
code. Arguments (e.g. antigravity:// deep links) are passed straight through.
If Antigravity is already running, the new instance hands the arguments to it
and exits, and so does this.

stdlib only. Usage: atom_launch.py [antigravity args...]
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

if os.name == "nt":
    import msvcrt
    fcntl = None
else:
    import fcntl
    msvcrt = None

ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("ATOM_HOME") or Path.home() / ".antigravity-atom")
BASE_STATES = (
    "idle",
    "thinking",
    "typing",
    "working",
    "exploring",
    "running",
    "delegating",
    "asking",
    "listening",
    "watching",
    "closed",
)
REACTIONS = {"happy", "sad", "angry", "error", "canceled", "tired", "done", "dance"}
SUSTAINED_MOODS = {"angry", "sad"}
STATES = (*BASE_STATES, *sorted(REACTIONS))
BUSY_STATES = {"thinking", "typing", "working", "exploring", "running", "delegating", "asking"}
SHORT_STALE_STATES = {"typing", "exploring", "asking"}
CORE_STATES = ("idle", "listening")
PRELOAD_ORDER = (
    "thinking",
    "closed",
    "dance",
    "typing",
    "working",
    "exploring",
    "running",
    "angry",
    "sad",
    "done",
    "happy",
    "watching",
    "delegating",
    "asking",
    "error",
    "canceled",
    "tired",
)

POLL_SEC = 0.5
RESYNC_SEC = 5.0
PRELOAD_INTERVAL_SEC = 0.4
SLEEP_AFTER_SEC = 300       # nothing happening for 5 min -> closed
TYPING_STALE_SEC = 180      # typing/reading/asking stuck this long -> ignored
THINKING_STALE_SEC = 20 * 60
PRUNE_AFTER_SEC = 24 * 3600
MTIME_GUARD_SEC = 0.05
HUB_URL = re.compile(r"^https?://(127\.0\.0\.1|localhost):\d+/")


def app_binary() -> str:
    if os.environ.get("ANTIGRAVITY_BIN"):
        return os.environ["ANTIGRAVITY_BIN"]
    if sys.platform == "darwin":
        candidates = (
            "/Applications/Antigravity.app/Contents/MacOS/Antigravity",
            str(Path.home() / "Applications" / "Antigravity.app" / "Contents" / "MacOS" / "Antigravity"),
        )
        for c in candidates:
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return candidates[0]
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
        candidates = (
            os.path.join(local, "Programs", "Antigravity", "Antigravity.exe"),
            os.path.join(local, "Antigravity", "Antigravity.exe"),
            os.path.join(pf, "Antigravity", "Antigravity.exe"),
        )
        for c in candidates:
            if os.path.isfile(c):
                return c
        for exe in ("antigravity.exe", "antigravity"):
            found = shutil.which(exe)
            if found and os.path.realpath(found) != os.path.realpath(__file__):
                return found
        return candidates[0]
    candidates = (
        "/opt/Antigravity/antigravity",
        "/usr/bin/antigravity",
        "/usr/lib/antigravity/antigravity",
        "/usr/share/antigravity/antigravity",
        str(Path.home() / ".local" / "bin" / "antigravity"),
    )
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("antigravity")
    if found and os.path.realpath(found) != os.path.realpath(__file__):
        return found
    return candidates[0]


def log(msg: str) -> None:
    print(f"[atom] {msg}", file=sys.stderr, flush=True)


# --- state ------------------------------------------------------------------

def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class StateReader:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or HOME
        self.started = time.time()
        self._convs_sig: tuple[int, int] | None = None
        self._convs_cache: dict[Path, tuple[tuple[int, int], float, str, str | None]] = {}
        self._emotion_sig: tuple[int, int] | None = None
        self._emotion_data: dict = {}
        self._limits_sig: tuple[int, int] | None = None
        self._limits_data: dict = {}

    def _read_cached_json(
        self, path: Path, sig_attr: str, data_attr: str, now: float, force: bool = False
    ) -> dict:
        try:
            st = path.stat()
        except OSError:
            setattr(self, sig_attr, None)
            setattr(self, data_attr, {})
            return {}
        sig = (st.st_mtime_ns, st.st_size)
        if force or sig != getattr(self, sig_attr) or abs(now - st.st_mtime_ns / 1e9) < MTIME_GUARD_SEC:
            setattr(self, data_attr, read_json(path))
            setattr(self, sig_attr, sig)
        return getattr(self, data_attr)

    def _read_emotion(self, now: float, force: bool = False) -> dict:
        return self._read_cached_json(self.home / "emotion.json", "_emotion_sig", "_emotion_data", now, force=force)

    def _read_limits(self, now: float, force: bool = False) -> dict:
        return self._read_cached_json(self.home / "limits.json", "_limits_sig", "_limits_data", now, force=force)

    def _scan_convs(
        self, now: float, force: bool = False
    ) -> list[tuple[Path, float, str, str | None]]:
        convs_dir = self.home / "convs"
        try:
            st = convs_dir.stat()
        except OSError:
            self._convs_sig = None
            self._convs_cache.clear()
            return []
        dir_sig = (st.st_mtime_ns, st.st_ctime_ns)
        rescan_dir = (
            force
            or dir_sig != self._convs_sig
            or abs(now - st.st_mtime_ns / 1e9) < MTIME_GUARD_SEC
        )
        if rescan_dir:
            self._convs_sig = dir_sig
            paths = list(convs_dir.glob("*.json"))
            seen = set(paths)
            for stale_path in list(self._convs_cache):
                if stale_path not in seen:
                    del self._convs_cache[stale_path]
        else:
            paths = list(self._convs_cache)

        entries: list[tuple[Path, float, str, str | None]] = []
        for f in paths:
            try:
                fst = f.stat()
            except OSError:
                self._convs_cache.pop(f, None)
                continue
            fsig = (fst.st_mtime_ns, fst.st_size)
            cached = self._convs_cache.get(f)
            if (
                cached is None
                or force
                or cached[0] != fsig
                or abs(now - fst.st_mtime_ns / 1e9) < MTIME_GUARD_SEC
            ):
                data = read_json(f)
                try:
                    ts = float(data.get("ts", 0))
                except (TypeError, ValueError):
                    ts = 0.0
                state = str(data.get("state") or "")
                raw_mood = data.get("mood")
                mood = raw_mood if raw_mood in SUSTAINED_MOODS else None
                self._convs_cache[f] = (fsig, ts, state, mood)
            else:
                _, ts, state, mood = cached
            entries.append((f, ts, state, mood))
        return entries

    def _compute_state(
        self, now: float, emotion_data: dict, force: bool = False
    ) -> tuple[str, str | None]:
        last = self.started
        busy: tuple[float, str, str | None] | None = None
        watching = False
        for f, ts, state, mood in self._scan_convs(now, force=force):
            if ts >= self.started:
                last = max(last, ts)
            stale_sec = TYPING_STALE_SEC if state in SHORT_STALE_STATES else THINKING_STALE_SEC
            if state in BUSY_STATES and ts >= self.started and now - ts < stale_sec:
                if busy is None or ts > busy[0]:
                    busy = (ts, state, mood)
            elif state == "watching" and ts >= self.started and now - ts < THINKING_STALE_SEC:
                watching = True
            elif now - ts > PRUNE_AFTER_SEC:
                f.unlink(missing_ok=True)
                self._convs_cache.pop(f, None)
        if busy:
            return busy[1], busy[2]
        if watching:
            return "watching", None
        try:
            emo_ts = float(emotion_data.get("ts", 0))
        except (TypeError, ValueError):
            emo_ts = 0.0
        if emo_ts >= self.started:
            last = max(last, emo_ts)
        return ("closed" if now - last > SLEEP_AFTER_SEC else "idle"), None

    def _compute_reaction(self, now: float, data: dict) -> tuple[str, float] | None:
        try:
            ts = float(data.get("ts", 0))
        except (TypeError, ValueError):
            return None
        if data.get("emotion") in REACTIONS and ts >= self.started and now - ts < 10:
            return data["emotion"], ts
        return None

    def base(self, force: bool = False) -> str:
        """Most recently active busy conversation wins; otherwise idle/closed."""
        now = time.time()
        emotion_data = self._read_emotion(now, force=force)
        return self._compute_state(now, emotion_data, force=force)[0]

    def mood(self, force: bool = False) -> str | None:
        """Active turn mood ('angry' | 'sad' | None) for the winning busy conversation."""
        now = time.time()
        emotion_data = self._read_emotion(now, force=force)
        return self._compute_state(now, emotion_data, force=force)[1]

    def reaction(self, force: bool = False) -> tuple[str, float] | None:
        now = time.time()
        emotion_data = self._read_emotion(now, force=force)
        return self._compute_reaction(now, emotion_data)

    def limit_info(self, force: bool = False) -> dict:
        """Per-model 5h/weekly quota limit status filtered to unexpired entries."""
        now = time.time()
        data = self._read_limits(now, force=force)
        raw_models = data.get("models")
        limited_models: list[str] = []
        active_model = str(data.get("activeModel") or "")
        active_key = str(data.get("activeKey") or "")
        active_limited = False
        if isinstance(raw_models, dict):
            for key, entry in raw_models.items():
                if not isinstance(entry, dict) or not entry.get("limited"):
                    continue
                try:
                    until = float(entry.get("until", 0))
                except (TypeError, ValueError):
                    until = 0.0
                if until > now:
                    name = str(entry.get("name") or key)
                    limited_models.append(name)
                    if key == active_key or (active_model and name.lower() == active_model.lower()):
                        active_limited = True
        limited_models.sort()
        return {
            "activeModel": active_model,
            "activeLimited": active_limited,
            "limitedModels": limited_models,
        }

    def snapshot(self, force: bool = False) -> tuple[str, str | None, tuple[str, float] | None]:
        """Read emotion.json at most once and return (base_state, mood, reaction)."""
        now = time.time()
        emotion_data = self._read_emotion(now, force=force)
        base, mood = self._compute_state(now, emotion_data, force=force)
        return base, mood, self._compute_reaction(now, emotion_data)


# --- page script & skins ----------------------------------------------------

def load_skin_names(assets_dir: Path | None = None) -> list[str]:
    base_dir = assets_dir or (ROOT / "assets")
    if not base_dir.is_dir():
        return []
    names = []
    for sub in base_dir.iterdir():
        if not sub.is_dir():
            continue
        has_state = any(
            meta.stem in STATES and meta.with_suffix(".webp").exists()
            for meta in sub.glob("*.json")
        )
        if has_state:
            names.append(sub.name)
    return sorted(names, key=lambda n: (0 if n == "atom" else 1, n))


def load_state_payload(name: str, state: str, assets_dir: Path | None = None) -> dict | None:
    if state not in STATES:
        return None
    base_dir = assets_dir or (ROOT / "assets")
    meta = base_dir / name / f"{state}.json"
    sheet = meta.with_suffix(".webp")
    if not (meta.exists() and sheet.exists()):
        return None
    return {
        **json.loads(meta.read_text(encoding="utf-8")),
        "webp": base64.b64encode(sheet.read_bytes()).decode(),
    }


def load_skin_payload(name: str, assets_dir: Path | None = None) -> dict:
    base_dir = assets_dir or (ROOT / "assets")
    skin_dir = base_dir / name
    out: dict[str, dict] = {}
    if not skin_dir.is_dir():
        return out
    for meta in sorted(skin_dir.glob("*.json")):
        sheet = meta.with_suffix(".webp")
        if meta.stem in STATES and sheet.exists():
            out[meta.stem] = {
                **json.loads(meta.read_text(encoding="utf-8")),
                "webp": base64.b64encode(sheet.read_bytes()).decode(),
            }
    return out


def build_bootstrap_script(skin_names: list[str] | None = None) -> str:
    """atom_inject.js with only skin names inlined; WebP sprites load on demand."""
    names = load_skin_names() if skin_names is None else skin_names
    js = (ROOT / "atom_inject.js").read_text(encoding="utf-8")
    # Strip full-line comments, leading indentation, and blank lines for compact CDP injection.
    js = re.sub(r"^\s*//.*\n", "", js, flags=re.M)
    js = re.sub(r"^[ \t]+", "", js, flags=re.M)
    js = re.sub(r"\n{2,}", "\n", js)
    return js.replace("const SKIN_NAMES = __ATOM_SKIN_NAMES__;", f"const SKIN_NAMES = {json.dumps(names)};", 1)


# --- DevTools transports (pipe on POSIX, WebSocket on Windows) ---------------

class Cdp:
    def __init__(self, write_fd: int, read_fd: int) -> None:
        self.w, self.r = write_fd, read_fd
        os.set_blocking(self.w, False)
        os.set_blocking(self.r, False)
        self.buf = b""
        self.wbuf = bytearray()
        self._eof = False
        self.next_id = 0
        self.pending: dict[int, Callable[[dict], None]] = {}

    def read_selectable(self) -> int:
        return self.r

    def write_selectable(self) -> int:
        return self.w

    def has_pending_write(self) -> bool:
        return bool(self.wbuf)

    def flush(self) -> None:
        while self.wbuf:
            try:
                n = os.write(self.w, self.wbuf)
            except BlockingIOError:
                break
            if n <= 0:
                break
            del self.wbuf[:n]

    def send(self, method: str, params: dict | None = None, session: str | None = None, then=None) -> None:
        self.next_id += 1
        msg: dict = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        if then:
            self.pending[self.next_id] = then
        self.wbuf += json.dumps(msg).encode() + b"\0"
        self.flush()

    def read(self) -> list[dict] | None:
        """Messages available now; None once the app closed the pipe."""
        if self._eof:
            return None
        eof = False
        while True:
            try:
                chunk = os.read(self.r, 1 << 20)
            except BlockingIOError:
                break
            if not chunk:
                eof = True
                break
            self.buf += chunk

        out: list[dict] = []
        if b"\0" in self.buf:
            parts = self.buf.split(b"\0")
            self.buf = parts.pop()
            for raw in parts:
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw))
                except ValueError:
                    pass
        if eof:
            self._eof = True
            if not out:
                return None
        return out

    def close(self) -> None:
        for fd in (self.w, self.r):
            try:
                os.close(fd)
            except OSError:
                pass


def _xor_mask(mask: bytes, payload: bytes) -> bytes:
    n = len(payload)
    if not n:
        return b""
    rep = (mask * ((n // 4) + 1))[:n]
    return (int.from_bytes(payload, "big") ^ int.from_bytes(rep, "big")).to_bytes(n, "big")


def _encode_ws_frame(opcode: int, payload: bytes, masked: bool = True) -> bytes:
    n = len(payload)
    mask_bit = 0x80 if masked else 0x00
    head = bytearray([0x80 | (opcode & 0x0F)])
    if n < 126:
        head.append(mask_bit | n)
    elif n < 65536:
        head.extend((mask_bit | 126, *struct.pack("!H", n)))
    else:
        head.extend((mask_bit | 127, *struct.pack("!Q", n)))
    if masked:
        mask = os.urandom(4)
        head.extend(mask)
        return bytes(head) + _xor_mask(mask, payload)
    return bytes(head) + payload


class WsCdp:
    """Stdlib non-blocking RFC 6455 WebSocket CDP transport (used on Windows)."""

    def __init__(self, sock: socket.socket, initial_buf: bytes = b"") -> None:
        self.sock = sock
        self.sock.setblocking(False)
        self.buf = bytearray(initial_buf)
        self._frag = bytearray()
        self.wbuf = bytearray()
        self._eof = False
        self._close_sent = False
        self.next_id = 0
        self.pending: dict[int, Callable[[dict], None]] = {}

    def read_selectable(self) -> socket.socket:
        return self.sock

    def write_selectable(self) -> socket.socket:
        return self.sock

    def has_pending_write(self) -> bool:
        return bool(self.wbuf)

    def flush(self) -> None:
        while self.wbuf:
            try:
                n = self.sock.send(self.wbuf)
            except BlockingIOError:
                break
            if n <= 0:
                break
            del self.wbuf[:n]

    def send(self, method: str, params: dict | None = None, session: str | None = None, then=None) -> None:
        self.next_id += 1
        msg: dict = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        if then:
            self.pending[self.next_id] = then
        self.wbuf += _encode_ws_frame(0x1, json.dumps(msg).encode("utf-8"), masked=True)
        self.flush()

    def read(self) -> list[dict] | None:
        if self._eof:
            return None
        eof = False
        while True:
            try:
                chunk = self.sock.recv(1 << 20)
            except BlockingIOError:
                break
            if not chunk:
                eof = True
                break
            self.buf.extend(chunk)

        out: list[dict] = []
        while len(self.buf) >= 2:
            b0, b1 = self.buf[0], self.buf[1]
            fin = bool(b0 & 0x80)
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            length = b1 & 0x7F
            pos = 2
            if length == 126:
                if len(self.buf) < pos + 2:
                    break
                length = struct.unpack("!H", self.buf[pos : pos + 2])[0]
                pos += 2
            elif length == 127:
                if len(self.buf) < pos + 8:
                    break
                length = struct.unpack("!Q", self.buf[pos : pos + 8])[0]
                pos += 8
            mask = b""
            if masked:
                if len(self.buf) < pos + 4:
                    break
                mask = bytes(self.buf[pos : pos + 4])
                pos += 4
            if len(self.buf) < pos + length:
                break
            payload = bytes(self.buf[pos : pos + length])
            del self.buf[: pos + length]
            if masked and payload:
                payload = _xor_mask(mask, payload)

            if opcode == 0x8:  # close
                if not self._close_sent:
                    self._close_sent = True
                    self.wbuf += _encode_ws_frame(0x8, payload[:2], masked=True)
                    try:
                        self.flush()
                    except OSError:
                        pass
                self._eof = True
                break
            if opcode == 0x9:  # ping
                self.wbuf += _encode_ws_frame(0xA, payload, masked=True)
                self.flush()
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode in (0x0, 0x1, 0x2):
                self._frag.extend(payload)
                if fin:
                    raw = bytes(self._frag)
                    self._frag.clear()
                    try:
                        out.append(json.loads(raw))
                    except ValueError:
                        pass

        if eof or self._eof:
            self._eof = True
            if not out:
                return None
        return out

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def ws_connect(ws_url: str) -> WsCdp:
    parsed = urllib.parse.urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    sock = socket.create_connection((host, port), timeout=5.0)
    sock.settimeout(None)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode("ascii")
    sock.sendall(req)
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            sock.close()
            raise OSError("WebSocket handshake closed")
        buf += chunk
    hdr_bytes, rest = buf.split(b"\r\n\r\n", 1)
    hdr_lines = hdr_bytes.decode("latin1").splitlines()
    if not hdr_lines or "101" not in hdr_lines[0]:
        sock.close()
        raise OSError(f"WebSocket handshake failed: {hdr_lines[0] if hdr_lines else ''}")
    expected = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    ).decode("ascii")
    accept_ok = any(
        line.lower().startswith("sec-websocket-accept:")
        and line.split(":", 1)[1].strip() == expected
        for line in hdr_lines[1:]
    )
    if not accept_ok:
        sock.close()
        raise OSError("Invalid Sec-WebSocket-Accept")
    return WsCdp(sock, rest)


class Atom:
    def __init__(self, cdp: Cdp | WsCdp, state: StateReader | None = None, assets_dir: Path | None = None) -> None:
        self.cdp = cdp
        self.assets_dir = assets_dir
        self.skin_names = load_skin_names(assets_dir)
        self.skin_cache: dict[str, dict] = {}
        self.state_cache: dict[tuple[str, str], dict | None] = {}
        self.script = build_bootstrap_script(self.skin_names)
        self.sessions: dict[str, str] = {}   # targetId -> sessionId
        self.session_skin: dict[str, str] = {}
        self.loaded_states: dict[str, set[str]] = {}
        self.ready_sessions: set[str] = set()
        self.probing_sessions: set[str] = set()
        self.loading_sessions: dict[str, str] = {}
        self.last_resync: dict[str, float] = {}
        self.attaching: set[str] = set()
        self.state = state or StateReader()
        self.sent_base: str | None = None
        self.sent_mood: str | None = None
        self.sent_reaction: float | None = None
        self.sent_limit: tuple[bool, str, tuple[str, ...]] = (False, "", ())
        self.last_preload = 0.0

    def get_skin_payload(self, name: str) -> dict:
        if name not in self.skin_cache:
            self.skin_cache[name] = load_skin_payload(name, self.assets_dir)
        return self.skin_cache[name]

    def get_state_payload(self, name: str, state: str) -> dict | None:
        key = (name, state)
        if key not in self.state_cache:
            self.state_cache[key] = load_state_payload(name, state, self.assets_dir)
        return self.state_cache[key]

    def start(self) -> None:
        self.cdp.send("Target.setDiscoverTargets", {"discover": True})

    def _drop_session(self, sid: str) -> None:
        self.ready_sessions.discard(sid)
        self.probing_sessions.discard(sid)
        self.loading_sessions.pop(sid, None)
        self.last_resync.pop(sid, None)
        self.session_skin.pop(sid, None)
        self.loaded_states.pop(sid, None)

    def ensure_state(self, session: str, skin: str, state: str, then=None) -> bool:
        loaded = self.loaded_states.setdefault(session, set())
        if state in loaded:
            if then:
                then({})
            return False
        data = self.get_state_payload(skin, state)
        if not data:
            if then:
                then({})
            return False
        loaded.add(state)
        self.cdp.send(
            "Runtime.evaluate",
            {"expression": f"window.__atom&&__atom.__loadState({json.dumps(skin)},{json.dumps(state)},{json.dumps(data)})"},
            session,
            then=then,
        )
        return True

    def handle(self, msg: dict) -> None:
        if "id" in msg:
            if "error" in msg:
                log(f"cdp error: {msg['error']}")
            cb = self.cdp.pending.pop(msg["id"], None)
            if cb:
                cb(msg.get("result") or {})
            return
        method, params = msg.get("method"), msg.get("params") or {}
        if method in ("Target.targetCreated", "Target.targetInfoChanged"):
            self.maybe_attach(params.get("targetInfo") or {})
        elif method in ("Target.targetDestroyed", "Target.detachedFromTarget"):
            tid = params.get("targetId")
            sid = params.get("sessionId")
            if tid is None and sid is not None:  # detachedFromTarget names the session
                tid = next((t for t, s in self.sessions.items() if s == sid), None)
            if tid is not None:
                sid = self.sessions.pop(tid, sid)
                self.attaching.discard(tid)
            if sid is not None:
                self._drop_session(sid)

    def probe_session(self, session: str) -> None:
        if session in self.probing_sessions or session not in self.sessions.values():
            return
        self.probing_sessions.add(session)

        def on_probe(result: dict) -> None:
            self.probing_sessions.discard(session)
            if session not in self.sessions.values():
                return
            val = ((result or {}).get("result") or {}).get("value")
            now_mono = time.monotonic()
            if isinstance(val, str) and val in self.skin_names:
                if self.loading_sessions.get(session) == val:
                    return
                self.loading_sessions[session] = val
                self.session_skin[session] = val
                self.loaded_states[session] = set()

                def on_loaded(_res: dict) -> None:
                    if self.loading_sessions.get(session) == val:
                        self.loading_sessions.pop(session, None)

                base, mood, _ = self.state.snapshot()
                lim = self.state.limit_info()
                initial = list(CORE_STATES)
                if base not in initial:
                    initial.append(base)
                if lim["activeLimited"] and "closed" not in initial:
                    initial.append("closed")
                for idx, st in enumerate(initial):
                    self.ensure_state(session, val, st, then=on_loaded if idx == 0 else None)
                lim_expr = (
                    f",__atom.setLimit({json.dumps(lim)})"
                    if (lim["activeLimited"] or lim["limitedModels"] or lim["activeModel"])
                    else ""
                )
                self.cdp.send(
                    "Runtime.evaluate",
                    {"expression": f"window.__atom&&(__atom.setBase({json.dumps(base)}),__atom.setMood({json.dumps(mood)}){lim_expr})"},
                    session,
                )
                self.sent_limit = (bool(lim["activeLimited"]), lim["activeModel"], tuple(lim["limitedModels"]))
                self.ready_sessions.add(session)
                self.last_resync[session] = now_mono
            elif session in self.ready_sessions:
                self.last_resync[session] = now_mono

        self.cdp.send(
            "Runtime.evaluate",
            {"expression": "window.__atom?__atom.needSkin():null", "returnByValue": True},
            session,
            then=on_probe,
        )

    def probe_sessions(self) -> None:
        now_mono = time.monotonic()
        for session in list(self.sessions.values()):
            if session not in self.ready_sessions:
                self.probe_session(session)
            elif now_mono - self.last_resync.get(session, 0.0) >= RESYNC_SEC:
                self.probe_session(session)

    def maybe_attach(self, info: dict) -> None:
        tid = info.get("targetId")
        if (
            info.get("type") != "page"
            or not HUB_URL.match(info.get("url", ""))
            or tid in self.sessions
            or tid in self.attaching
        ):
            return
        self.attaching.add(tid)

        def attached(result: dict) -> None:
            self.attaching.discard(tid)
            session = result.get("sessionId")
            if not session:
                return
            self.sessions[tid] = session
            self.cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": self.script}, session)
            self.cdp.send("Runtime.evaluate", {"expression": self.script}, session)
            self.probe_session(session)
            log(f"on the prompt bar of {info.get('url', '').split('#')[0]}")

        self.cdp.send("Target.attachToTarget", {"targetId": tid, "flatten": True}, then=attached)

    def eval_all(self, expr: str, ensure: str | None = None) -> None:
        for session in list(self.ready_sessions):
            if ensure:
                skin = self.session_skin.get(session)
                if skin:
                    self.ensure_state(session, skin, ensure)
            self.cdp.send("Runtime.evaluate", {"expression": expr}, session)

    def trickle_preload(self) -> None:
        now_mono = time.monotonic()
        if now_mono - self.last_preload < PRELOAD_INTERVAL_SEC:
            return
        pending_fn = getattr(self.cdp, "has_pending_write", None)
        if pending_fn and pending_fn():
            return
        for session in list(self.ready_sessions):
            skin = self.session_skin.get(session)
            if not skin:
                continue
            loaded = self.loaded_states.get(session, set())
            for st in PRELOAD_ORDER:
                if st not in loaded and self.get_state_payload(skin, st) is not None:
                    self.ensure_state(session, skin, st)
                    self.last_preload = now_mono
                    return

    def poll(self, force: bool = False) -> None:
        if self.sessions:
            self.probe_sessions()
        if not self.ready_sessions:
            return
        base, mood, reaction = self.state.snapshot(force=force)
        changed = False
        if base != self.sent_base:
            self.eval_all(f"window.__atom&&__atom.setBase({json.dumps(base)})", ensure=base)
            self.sent_base = base
            changed = True
        if mood != self.sent_mood:
            self.eval_all(f"window.__atom&&__atom.setMood({json.dumps(mood)})")
            self.sent_mood = mood
            changed = True
        lim = self.state.limit_info(force=force)
        lim_key = (bool(lim["activeLimited"]), lim["activeModel"], tuple(lim["limitedModels"]))
        if lim_key != self.sent_limit:
            self.eval_all(
                f"window.__atom&&__atom.setLimit({json.dumps(lim)})",
                ensure="closed" if lim["activeLimited"] else None,
            )
            self.sent_limit = lim_key
            changed = True
        if reaction and reaction[1] != self.sent_reaction:
            self.eval_all(
                f"window.__atom&&__atom.react({json.dumps(reaction[0])},{json.dumps(reaction[1])})",
                ensure=reaction[0],
            )
            self.sent_reaction = reaction[1]
            changed = True
        if not changed:
            self.trickle_preload()


# --- main -------------------------------------------------------------------

def _acquire_lock(lock_file) -> bool:
    fd = lock_file.fileno()
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False
    if msvcrt is not None:
        try:
            os.lseek(fd, 0, os.SEEK_END)
            if os.lseek(fd, 0, os.SEEK_CUR) == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    return True


def _release_lock(lock_file) -> None:
    fd = lock_file.fileno()
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
    elif msvcrt is not None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


def _open_notify_socket(home: Path) -> tuple[socket.socket | None, Path | None, Path | None]:
    if hasattr(socket, "AF_UNIX") and os.name != "nt":
        sock_path = home / "notify.sock"
        sock_path.unlink(missing_ok=True)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            sock.bind(str(sock_path))
            os.chmod(sock_path, 0o600)
            return sock, sock_path, None
        except OSError as e:
            log(f"notify socket disabled: {e!r}")
            sock.close()
            return None, None, None
    port_path = home / "notify.port"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        port_path.write_text(str(port), encoding="utf-8")
        return sock, None, port_path
    except OSError as e:
        log(f"notify port disabled: {e!r}")
        sock.close()
        return None, None, None


def _pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _discover_ws_url(port: int, app: subprocess.Popen, timeout: float = 15.0) -> str | None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/json/version"
    while time.monotonic() < deadline:
        if app.poll() is not None:
            return None
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ws_url = data.get("webSocketDebuggerUrl")
                if ws_url:
                    return ws_url
        except Exception:
            pass
        time.sleep(0.1)
    return None


def _launch_posix(binary: str, args: list[str]) -> tuple[subprocess.Popen, Cdp]:
    to_app_r, to_app_w = os.pipe()
    from_app_r, from_app_w = os.pipe()

    def wire_fds() -> None:
        a = fcntl.fcntl(to_app_r, fcntl.F_DUPFD_CLOEXEC, 10)
        b = fcntl.fcntl(from_app_w, fcntl.F_DUPFD_CLOEXEC, 10)
        os.dup2(a, 3)
        os.dup2(b, 4)
        os.close(a)
        os.close(b)

    try:
        app = subprocess.Popen(
            [binary, "--remote-debugging-pipe", *args],
            pass_fds=(3, 4),
            preexec_fn=wire_fds,
        )
    except Exception:
        for fd in (to_app_r, to_app_w, from_app_r, from_app_w):
            try:
                os.close(fd)
            except OSError:
                pass
        raise
    os.close(to_app_r)
    os.close(from_app_w)
    return app, Cdp(to_app_w, from_app_r)


def _launch_windows(binary: str, args: list[str]) -> tuple[subprocess.Popen, WsCdp | None]:
    port = _pick_free_port()
    app = subprocess.Popen([binary, f"--remote-debugging-port={port}", *args])
    ws_url = _discover_ws_url(port, app)
    if not ws_url:
        return app, None
    return app, ws_connect(ws_url)


def ensure_hooks_installed(plugins_dir: Path | None = None, root: Path | None = None) -> Path | None:
    """Link or copy the hooks plugin into Antigravity's plugins dir if missing."""
    src = root or ROOT
    if not ((src / "plugin.json").is_file() and (src / "hooks.json").is_file()):
        return None
    base_dir = plugins_dir or Path(
        os.environ.get("ANTIGRAVITY_PLUGINS_DIR") or Path.home() / ".gemini" / "config" / "plugins"
    )
    target = base_dir / "atom"
    try:
        if os.name != "nt":
            if target.exists() or target.is_symlink():
                return target
            base_dir.mkdir(parents=True, exist_ok=True)
            target.symlink_to(src)
        else:
            if (target / "hooks.json").is_file():
                return target
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / "plugin.json", target / "plugin.json")
            shutil.copy2(src / "atom_hook.py", target / "atom_hook.py")
            hook_py = "py -3" if shutil.which("py") else "python"
            hooks_raw = (src / "hooks.json").read_text(encoding="utf-8")
            (target / "hooks.json").write_text(
                hooks_raw.replace("python3 -S -I ./atom_hook.py", f"{hook_py} -S -I ./atom_hook.py"),
                encoding="utf-8",
            )
        log(f"installed hooks plugin -> {target}")
        return target
    except OSError as e:
        log(f"hooks auto-setup skipped: {e!r}")
        return None


def main() -> int:
    # Launched from a desktop entry, stdio may be closed; make sure pipes
    # don't land on fds 0-2.
    if os.name != "nt":
        for fd in (0, 1, 2):
            try:
                os.fstat(fd)
            except OSError:
                os.open(os.devnull, os.O_RDWR)

    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(HOME, 0o700)
        except OSError:
            pass
    ensure_hooks_installed()
    lock_file = open(HOME / "launcher.lock", "a+", encoding="utf-8")
    is_primary = _acquire_lock(lock_file)

    notify_sock: socket.socket | None = None
    sock_path: Path | None = None
    port_path: Path | None = None
    if is_primary:
        notify_sock, sock_path, port_path = _open_notify_socket(HOME)

    binary = app_binary()
    cdp: Cdp | WsCdp | None = None
    try:
        try:
            if sys.platform == "win32":
                app, cdp = _launch_windows(binary, sys.argv[1:])
            else:
                app, cdp = _launch_posix(binary, sys.argv[1:])
        except FileNotFoundError:
            log(f"Antigravity binary not found at {binary}; set ANTIGRAVITY_BIN and retry.")
            return 1

        def forward_signal(sig: int, _frame) -> None:
            try:
                if os.name == "nt":
                    app.terminate()
                else:
                    app.send_signal(sig)
            except (ProcessLookupError, OSError):
                pass

        sigs = [signal.SIGTERM, signal.SIGINT]
        if hasattr(signal, "SIGHUP"):
            sigs.append(signal.SIGHUP)
        for sig in sigs:
            signal.signal(sig, forward_signal)

        if cdp is None:
            return app.wait()

        atom = Atom(cdp)
        try:
            atom.start()
        except OSError:
            pass  # app exited immediately (already running); fall through to wait()

        read_sel = cdp.read_selectable()
        write_sel = cdp.write_selectable()
        last_poll = 0.0
        while True:
            if app.poll() is not None:
                break
            rlist: list = [read_sel]
            if notify_sock is not None:
                rlist.append(notify_sock)
            wlist = [write_sel] if cdp.has_pending_write() else []
            try:
                readable, writable, _ = select.select(rlist, wlist, [], POLL_SEC)
            except InterruptedError:
                continue

            if write_sel in writable:
                try:
                    cdp.flush()
                except OSError:
                    break

            if read_sel in readable:
                try:
                    msgs = cdp.read()
                except OSError:
                    msgs = None
                if msgs is None:
                    break  # app closed the channel: it is exiting
                for msg in msgs:
                    try:
                        atom.handle(msg)
                    except Exception as e:  # never let a bad message take the app's pipe down
                        log(f"ignored message: {e!r}")
                try:
                    cdp.flush()
                except OSError:
                    break

            woke = False
            if notify_sock is not None and notify_sock in readable:
                while True:
                    try:
                        notify_sock.recv(1024)
                        woke = True
                    except BlockingIOError:
                        break
                    except OSError:
                        break

            if woke or time.monotonic() - last_poll >= POLL_SEC:
                last_poll = time.monotonic()
                try:
                    atom.poll(force=woke)
                except OSError:
                    break
                except Exception as e:
                    log(f"state poll failed: {e!r}")
        return app.wait()
    finally:
        if cdp is not None:
            cdp.close()
        if notify_sock is not None:
            notify_sock.close()
        if sock_path is not None:
            sock_path.unlink(missing_ok=True)
        if port_path is not None:
            port_path.unlink(missing_ok=True)
        if is_primary:
            _release_lock(lock_file)
        lock_file.close()


if __name__ == "__main__":
    sys.exit(main())
