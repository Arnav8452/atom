import json
import os
import socket
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import atom_hook  # noqa: E402
import atom_launch  # noqa: E402
from tools import trigger_state  # noqa: E402


@unittest.skipIf(os.name == "nt", "Cdp pipe transport is POSIX-only; Windows uses WsCdp")
class CdpTests(unittest.TestCase):
    def test_read_partial_multi_and_malformed(self) -> None:
        app_to_py_r, app_to_py_w = os.pipe()
        py_to_app_r, py_to_app_w = os.pipe()
        try:
            cdp = atom_launch.Cdp(py_to_app_w, app_to_py_r)
            os.write(app_to_py_w, b'{"id":1,"result":{}}\0bad-json\0{"method":"Foo"')
            msgs = cdp.read()
            self.assertEqual(msgs, [{"id": 1, "result": {}}])

            os.write(app_to_py_w, b',"params":{"x":2}}\0')
            msgs = cdp.read()
            self.assertEqual(msgs, [{"method": "Foo", "params": {"x": 2}}])

            os.close(app_to_py_w)
            app_to_py_w = -1
            self.assertIsNone(cdp.read())
        finally:
            for fd in (app_to_py_r, app_to_py_w, py_to_app_r, py_to_app_w):
                if fd >= 0:
                    os.close(fd)

    def test_nonblocking_write_buffering_and_flush(self) -> None:
        app_to_py_r, app_to_py_w = os.pipe()
        py_to_app_r, py_to_app_w = os.pipe()
        try:
            os.set_blocking(py_to_app_r, False)
            cdp = atom_launch.Cdp(py_to_app_w, app_to_py_r)
            big = "x" * 200_000
            cdp.send("Runtime.evaluate", {"expression": big})
            self.assertTrue(cdp.has_pending_write())

            received = bytearray()
            while cdp.has_pending_write():
                while True:
                    try:
                        chunk = os.read(py_to_app_r, 65536)
                    except BlockingIOError:
                        break
                    if not chunk:
                        break
                    received.extend(chunk)
                cdp.flush()

            while True:
                try:
                    chunk = os.read(py_to_app_r, 65536)
                except BlockingIOError:
                    break
                if not chunk:
                    break
                received.extend(chunk)

            self.assertFalse(cdp.has_pending_write())
            decoded = json.loads(bytes(received).rstrip(b"\0"))
            self.assertEqual(decoded["method"], "Runtime.evaluate")
            self.assertEqual(decoded["params"]["expression"], big)
        finally:
            for fd in (app_to_py_r, app_to_py_w, py_to_app_r, py_to_app_w):
                os.close(fd)


class StateReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "convs").mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_conv(self, name: str, state: str, ts: float, mood: str | None = None) -> Path:
        p = self.home / "convs" / f"{name}.json"
        data = {"state": state, "ts": ts}
        if mood is not None:
            data["mood"] = mood
        p.write_text(json.dumps(data))
        return p

    def test_ignores_pre_startup_state_and_reaction(self) -> None:
        now = time.time()
        self._write_conv("old", "typing", now - 5)
        (self.home / "emotion.json").write_text(json.dumps({"emotion": "happy", "ts": now - 2}))
        sr = atom_launch.StateReader(self.home)
        sr.started = now
        self.assertEqual(sr.base(force=True), "idle")
        self.assertIsNone(sr.reaction(force=True))

    def test_multi_conv_precedence_and_distinct_stale_timeouts(self) -> None:
        now = time.time()
        sr = atom_launch.StateReader(self.home)
        sr.started = now - 1000

        # typing older than 180s is stale; thinking 200s old is still active
        self._write_conv("c1", "typing", now - 200)
        self._write_conv("c2", "thinking", now - 200)
        self.assertEqual(sr.base(force=True), "thinking")

        # newer typing wins
        self._write_conv("c1", "typing", now - 1)
        self.assertEqual(sr.base(force=True), "typing")

    def test_sleep_and_watching_state(self) -> None:
        now = time.time()
        sr = atom_launch.StateReader(self.home)
        sr.started = now - (atom_launch.SLEEP_AFTER_SEC + 50)
        self._write_conv("c1", "idle", now - (atom_launch.SLEEP_AFTER_SEC + 20))
        self.assertEqual(sr.base(force=True), "closed")

        # watching stays active past SLEEP_AFTER_SEC up to THINKING_STALE_SEC
        self._write_conv("c2", "watching", now - (atom_launch.SLEEP_AFTER_SEC + 10))
        self.assertEqual(sr.base(force=True), "watching")

    def test_short_vs_long_stale_timeouts_for_new_busy_states(self) -> None:
        now = time.time()
        sr = atom_launch.StateReader(self.home)
        sr.started = now - 1000
        self._write_conv("c1", "exploring", now - 200)
        self._write_conv("c2", "working", now - 200)
        self.assertEqual(sr.base(force=True), "working")

    def test_sustained_turn_mood_preserves_busy_base_until_cleared(self) -> None:
        now = time.time()
        sr = atom_launch.StateReader(self.home)
        sr.started = now - 100

        self._write_conv("c1", "thinking", now - 2, mood="angry")
        self.assertEqual(sr.base(force=True), "thinking")
        self.assertEqual(sr.mood(force=True), "angry")

        self._write_conv("c1", "typing", now - 1, mood="angry")
        self.assertEqual(sr.base(force=True), "typing")
        self.assertEqual(sr.mood(force=True), "angry")

        self._write_conv("c1", "idle", now)
        self.assertEqual(sr.base(force=True), "idle")
        self.assertIsNone(sr.mood(force=True))

        self._write_conv("c2", "working", now + 1, mood="sad")
        self.assertEqual(sr.base(force=True), "working")
        self.assertEqual(sr.mood(force=True), "sad")

        # Non-busy conv with leftover mood does not stay moody once idle
        self._write_conv("c2", "idle", now + 2, mood="angry")
        self.assertEqual(sr.base(force=True), "idle")
        self.assertIsNone(sr.mood(force=True))

    def test_mtime_cache_avoids_rereading_unchanged_files(self) -> None:
        now = time.time()
        sr = atom_launch.StateReader(self.home)
        sr.started = now - 100
        p = self._write_conv("c1", "thinking", now - 10)
        ep = self.home / "emotion.json"
        ep.write_text(json.dumps({"emotion": "happy", "ts": now - 10}))
        # Backdate mtimes well past MTIME_GUARD_SEC so cache applies deterministically
        past = now - 10
        os.utime(p, (past, past))
        os.utime(ep, (past, past))
        os.utime(self.home / "convs", (past, past))

        base, mood, react = sr.snapshot()
        self.assertEqual(base, "thinking")
        self.assertIsNone(mood)
        self.assertIsNone(react)  # 10s old >= 10s limit

        with mock.patch.object(atom_launch, "read_json", side_effect=AssertionError("unexpected disk read")):
            base2, mood2, react2 = sr.snapshot()
            self.assertEqual(base2, "thinking")
            self.assertIsNone(mood2)
            self.assertIsNone(react2)

    def test_limit_info_tracks_and_expires_models(self) -> None:
        now = time.time()
        sr = atom_launch.StateReader(self.home)
        (self.home / "limits.json").write_text(json.dumps({
            "activeModel": "gemini-3-pro",
            "activeKey": "gemini-3-pro",
            "models": {
                "gemini-3-pro": {"name": "gemini-3-pro", "limited": True, "ts": now, "until": now + 3600},
                "old-model": {"name": "old-model", "limited": True, "ts": now - 999, "until": now - 10},
            },
        }))
        lim = sr.limit_info(force=True)
        self.assertEqual(lim["activeModel"], "gemini-3-pro")
        self.assertTrue(lim["activeLimited"])
        self.assertEqual(lim["limitedModels"], ["gemini-3-pro"])

        (self.home / "limits.json").write_text(json.dumps({
            "activeModel": "gemini-3-flash",
            "activeKey": "gemini-3-flash",
            "models": {
                "gemini-3-pro": {"name": "gemini-3-pro", "limited": True, "ts": now, "until": now + 3600},
            },
        }))
        lim2 = sr.limit_info(force=True)
        self.assertEqual(lim2["activeModel"], "gemini-3-flash")
        self.assertFalse(lim2["activeLimited"])
        self.assertEqual(lim2["limitedModels"], ["gemini-3-pro"])


class FakeCdp:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict, str | None, object]] = []
        self.pending: dict = {}
        self.next_id = 0

    def send(self, method: str, params: dict | None = None, session: str | None = None, then=None) -> None:
        self.next_id += 1
        if then:
            self.pending[self.next_id] = then
        self.sent.append((method, params or {}, session, self.next_id))


class AtomBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "convs").mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bootstrap_is_lightweight_and_on_demand_skin_works(self) -> None:
        cdp = FakeCdp()
        sr = atom_launch.StateReader(self.home)
        atom = atom_launch.Atom(cdp, state=sr)

        self.assertLess(len(atom.script), 36_000)
        self.assertNotIn("data:image/webp", atom.script)
        self.assertNotIn("UklGR", atom.script)

        # Unrelated external page is ignored
        atom.handle({
            "method": "Target.targetCreated",
            "params": {"targetInfo": {"targetId": "ext", "type": "page", "url": "https://example.com/"}},
        })
        self.assertEqual(cdp.sent, [])

        # Localhost candidate attaches without Runtime.enable and installs bootstrap
        atom.handle({
            "method": "Target.targetCreated",
            "params": {"targetInfo": {"targetId": "t1", "type": "page", "url": "http://127.0.0.1:43210/"}},
        })
        self.assertEqual(cdp.sent[0][0], "Target.attachToTarget")
        attach_id = cdp.sent[0][3]
        atom.handle({"id": attach_id, "result": {"sessionId": "s1"}})

        s1_msgs = [(m, p, mid) for m, p, sess, mid in cdp.sent if sess == "s1"]
        self.assertEqual(
            [m for m, _, _ in s1_msgs],
            ["Page.addScriptToEvaluateOnNewDocument", "Runtime.evaluate", "Runtime.evaluate"],
        )
        self.assertNotIn("Runtime.enable", [m for m, _, _ in s1_msgs])
        self.assertNotIn("Runtime.addBinding", [m for m, _, _ in s1_msgs])
        self.assertEqual(atom.ready_sessions, set())

        # Localhost dev server that never mounts prompt bar returns null from needSkin()
        probe_id = s1_msgs[2][2]
        cdp.sent.clear()
        atom.handle({"id": probe_id, "result": {"result": {"value": None}}})
        self.assertEqual(atom.ready_sessions, set())
        self.assertEqual(cdp.sent, [])

        # Next poll probes unready session; once prompt bar mounts, needSkin() returns "atom"
        atom.poll(force=True)
        self.assertEqual(len(cdp.sent), 1)
        self.assertIn("needSkin()", cdp.sent[0][1]["expression"])
        probe2_id = cdp.sent[0][3]
        cdp.sent.clear()

        atom.handle({"id": probe2_id, "result": {"result": {"value": "atom"}}})
        self.assertEqual(atom.ready_sessions, {"s1"})
        evals = [p["expression"] for m, p, sess, _ in cdp.sent if m == "Runtime.evaluate" and sess == "s1"]
        self.assertTrue(any('__loadState("atom","idle",' in e and '"webp"' in e for e in evals))
        self.assertTrue(any('__loadState("atom","listening",' in e for e in evals))
        self.assertFalse(any('__loadState("atom","running",' in e for e in evals))
        self.assertTrue(any('setBase("idle")' in e for e in evals))
        self.assertTrue(any('setMood(null)' in e for e in evals))
        load_id = next(mid for m, p, _, mid in cdp.sent if '__loadState("atom","idle",' in p.get("expression", ""))
        atom.handle({"id": load_id, "result": {}})

        # Switching to "running" lazily pushes "running" right before setBase("running")
        cdp.sent.clear()
        (self.home / "convs" / "c1.json").write_text(json.dumps({"state": "running", "ts": time.time()}))
        atom.poll(force=True)
        evals = [p["expression"] for m, p, sess, _ in cdp.sent if m == "Runtime.evaluate" and sess == "s1"]
        self.assertTrue(any('__loadState("atom","running",' in e for e in evals))
        self.assertTrue(any('setBase("running")' in e for e in evals))

        # Triggering "angry" reaction lazily pushes "angry" right before react("angry", ...)
        cdp.sent.clear()
        (self.home / "emotion.json").write_text(json.dumps({"emotion": "angry", "ts": time.time()}))
        atom.poll(force=True)
        evals = [p["expression"] for m, p, sess, _ in cdp.sent if m == "Runtime.evaluate" and sess == "s1"]
        self.assertTrue(any('__loadState("atom","angry",' in e for e in evals))
        self.assertTrue(any('react("angry",' in e for e in evals))

        # Idle poll trickles one unloaded state from PRELOAD_ORDER at a time
        cdp.sent.clear()
        atom.last_preload = time.monotonic() - (atom_launch.PRELOAD_INTERVAL_SEC + 1.0)
        atom.poll(force=False)
        evals = [p["expression"] for m, p, sess, _ in cdp.sent if m == "Runtime.evaluate" and sess == "s1"]
        self.assertEqual(len(evals), 1)
        self.assertIn('__loadState("atom","thinking",', evals[0])

        # Sustained turn mood syncs setMood("angry") alongside normal working states until Stop/idle
        cdp.sent.clear()
        (self.home / "convs" / "c1.json").write_text(
            json.dumps({"state": "thinking", "mood": "angry", "ts": time.time() + 1})
        )
        atom.poll(force=True)
        evals = [p["expression"] for m, p, sess, _ in cdp.sent if m == "Runtime.evaluate" and sess == "s1"]
        self.assertTrue(any('setBase("thinking")' in e for e in evals))
        self.assertTrue(any('setMood("angry")' in e for e in evals))

        cdp.sent.clear()
        (self.home / "convs" / "c1.json").write_text(
            json.dumps({"state": "typing", "mood": "angry", "ts": time.time() + 2})
        )
        atom.poll(force=True)
        evals = [p["expression"] for m, p, sess, _ in cdp.sent if m == "Runtime.evaluate" and sess == "s1"]
        self.assertTrue(any('setBase("typing")' in e for e in evals))
        self.assertFalse(any("setMood" in e for e in evals))

        cdp.sent.clear()
        (self.home / "convs" / "c1.json").write_text(
            json.dumps({"state": "idle", "ts": time.time() + 3})
        )
        atom.poll(force=True)
        evals = [p["expression"] for m, p, sess, _ in cdp.sent if m == "Runtime.evaluate" and sess == "s1"]
        self.assertTrue(any('setBase("idle")' in e for e in evals))
        self.assertTrue(any('setMood(null)' in e for e in evals))

        # Reload simulation: resync probe after RESYNC_SEC detects empty skin and reloads core states
        atom.last_resync["s1"] = time.monotonic() - (atom_launch.RESYNC_SEC + 1.0)
        cdp.sent.clear()
        atom.poll()
        resync_id = cdp.sent[0][3]
        cdp.sent.clear()
        atom.handle({"id": resync_id, "result": {"result": {"value": "atom"}}})
        self.assertTrue(any('__loadState("atom","idle",' in p["expression"] for _, p, _, _ in cdp.sent))

        # CDP error response logs cleanly and pops callback
        called = []
        cdp.pending[99] = lambda res: called.append(res)
        with mock.patch.object(atom_launch, "log") as mock_log:
            atom.handle({"id": 99, "error": {"code": -32000, "message": "oops"}})
        self.assertEqual(called, [{}])
        mock_log.assert_called_once()

        # Detach cleans up sessions, ready_sessions, and probe tracking
        atom.handle({"method": "Target.detachedFromTarget", "params": {"sessionId": "s1"}})
        self.assertEqual(atom.sessions, {})
        self.assertEqual(atom.ready_sessions, set())
        self.assertEqual(atom.probing_sessions, set())

    def test_limit_sync_loads_closed_and_clears_on_model_switch(self) -> None:
        cdp = FakeCdp()
        sr = atom_launch.StateReader(self.home)
        atom = atom_launch.Atom(cdp, state=sr)
        atom.sessions["t1"] = "s1"
        atom.session_skin["s1"] = "atom"
        atom.loaded_states["s1"] = {"idle", "listening"}
        atom.ready_sessions.add("s1")

        now = time.time()
        (self.home / "limits.json").write_text(json.dumps({
            "activeModel": "gemini-3-pro",
            "activeKey": "gemini-3-pro",
            "models": {
                "gemini-3-pro": {"name": "gemini-3-pro", "limited": True, "ts": now, "until": now + 3600},
            },
        }))
        atom.poll(force=True)
        evals = [p["expression"] for m, p, sess, _ in cdp.sent if m == "Runtime.evaluate" and sess == "s1"]
        self.assertTrue(any('__loadState("atom","closed",' in e for e in evals))
        self.assertTrue(any('__atom.setLimit(' in e and '"activeLimited": true' in e for e in evals))

        cdp.sent.clear()
        (self.home / "limits.json").write_text(json.dumps({
            "activeModel": "gemini-3-flash",
            "activeKey": "gemini-3-flash",
            "models": {
                "gemini-3-pro": {"name": "gemini-3-pro", "limited": True, "ts": now, "until": now + 3600},
            },
        }))
        atom.poll(force=True)
        evals2 = [p["expression"] for m, p, sess, _ in cdp.sent if m == "Runtime.evaluate" and sess == "s1"]
        self.assertTrue(any('__atom.setLimit(' in e and '"activeLimited": false' in e for e in evals2))

    def test_generated_assets_have_valid_loop_metadata(self) -> None:
        assets = ROOT / "assets" / "atom"
        self.assertEqual(len(atom_launch.STATES), 19)
        for state in atom_launch.STATES:
            meta_path = assets / f"{state}.json"
            webp_path = assets / f"{state}.webp"
            self.assertTrue(meta_path.is_file(), f"missing {meta_path}")
            self.assertTrue(webp_path.is_file(), f"missing {webp_path}")
            meta = json.loads(meta_path.read_text())
            self.assertEqual((meta["w"], meta["h"]), (150, 120))
            n = len(meta["durations"])
            self.assertGreater(n, 0)
            self.assertIn("loop", meta)
            lo, hi = meta["loop"]
            self.assertGreaterEqual(lo, 0)
            self.assertLessEqual(lo, hi)
            self.assertLess(hi, n)
            if state in ("angry", "sad"):
                self.assertEqual(n, 42)
                self.assertEqual([lo, hi], [6, 35])
            elif state == "dance":
                self.assertEqual(n, 40)
                self.assertEqual([lo, hi], [5, 34])
                self.assertEqual(meta["durations"][0], 65)


class WsCdpTests(unittest.TestCase):
    def test_ws_framing_masking_ping_and_close(self) -> None:
        srv_sock, cli_sock = socket.socketpair()
        srv_sock.setblocking(False)
        try:
            ws = atom_launch.WsCdp(cli_sock)
            ws.send("Target.setDiscoverTargets", {"discover": True})
            self.assertFalse(ws.has_pending_write())

            # Read masked client frame from server socket and decode it
            raw = srv_sock.recv(4096)
            self.assertEqual(raw[0], 0x81)
            self.assertTrue(raw[1] & 0x80)
            length = raw[1] & 0x7F
            mask = raw[2:6]
            payload = atom_launch._xor_mask(mask, raw[6 : 6 + length])
            self.assertEqual(json.loads(payload)["method"], "Target.setDiscoverTargets")

            # Server sends unmasked >125-byte frame (126 extended length) + ping + fragmented text
            big_msg = json.dumps({"id": 1, "result": {"data": "a" * 200}}).encode()
            srv_sock.sendall(atom_launch._encode_ws_frame(0x1, big_msg, masked=False))
            srv_sock.sendall(atom_launch._encode_ws_frame(0x9, b"hi", masked=False))
            # Fragmented JSON frame (FIN=0 text + FIN=1 continuation)
            f1 = bytearray(atom_launch._encode_ws_frame(0x1, b'{"method":"Ping"', masked=False))
            f1[0] &= 0x7F  # FIN=0
            f2 = atom_launch._encode_ws_frame(0x0, b',"params":{}}', masked=False)
            srv_sock.sendall(bytes(f1) + f2)

            msgs = ws.read()
            self.assertEqual(msgs, [
                {"id": 1, "result": {"data": "a" * 200}},
                {"method": "Ping", "params": {}},
            ])

            # Verify pong reply was emitted automatically
            pong = srv_sock.recv(64)
            self.assertEqual(pong[0], 0x8A)
            self.assertEqual(atom_launch._xor_mask(pong[2:6], pong[6:8]), b"hi")

            # Server close returns None cleanly
            srv_sock.sendall(atom_launch._encode_ws_frame(0x8, struct.pack("!H", 1000), masked=False))
            self.assertIsNone(ws.read())
        finally:
            srv_sock.close()
            cli_sock.close()


class PreviewToolsTests(unittest.TestCase):
    def test_trigger_state_supports_mood_flag_and_gallery_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orig_home = atom_hook.HOME
            atom_hook.HOME = tmp
            try:
                with mock.patch.object(atom_hook, "notify_launcher"):
                    trigger_state.trigger("typing", conv_id="p1", mood="angry")
                    conv = json.loads((Path(tmp) / "convs" / "p1.json").read_text())
                    self.assertEqual(conv["state"], "typing")
                    self.assertEqual(conv["mood"], "angry")

                    trigger_state.trigger("typing", conv_id="p1", mood="none")
                    conv2 = json.loads((Path(tmp) / "convs" / "p1.json").read_text())
                    self.assertEqual(conv2["state"], "typing")
                    self.assertNotIn("mood", conv2)

                    trigger_state.trigger("sad", conv_id="p1", mood="self")
                    conv3 = json.loads((Path(tmp) / "convs" / "p1.json").read_text())
                    self.assertEqual(conv3["state"], "thinking")
                    self.assertEqual(conv3["mood"], "sad")
            finally:
                atom_hook.HOME = orig_home
        self.assertTrue((ROOT / "tools" / "preview.html").is_file())

    def test_ensure_hooks_installed_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugins_dir = Path(tmp) / "plugins"
            first = atom_launch.ensure_hooks_installed(plugins_dir=plugins_dir)
            self.assertEqual(first, plugins_dir / "atom")
            assert first is not None
            if os.name == "nt":
                self.assertTrue((first / "hooks.json").is_file())
            else:
                self.assertTrue(first.is_symlink())
                self.assertEqual(first.resolve(), atom_launch.ROOT.resolve())
            second = atom_launch.ensure_hooks_installed(plugins_dir=plugins_dir)
            self.assertEqual(second, first)

    def test_sync_hook_copy_refreshes_stale_windows_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "atom"
            target.mkdir()
            # An older install: chosen interpreter, outdated hook and hooks.json.
            (target / "hooks.json").write_text('{"command": "py -3 -S -I ./atom_hook.py", "timeout": 5}')
            (target / "atom_hook.py").write_text("old")
            self.assertTrue(atom_launch.sync_hook_copy(atom_launch.ROOT, target))
            hooks = (target / "hooks.json").read_text()
            self.assertIn('"py -3 -S -I ./atom_hook.py PreToolUse || exit 0"', hooks)
            self.assertNotIn("python3", hooks)
            self.assertEqual((target / "atom_hook.py").read_bytes(), (atom_launch.ROOT / "atom_hook.py").read_bytes())
            self.assertTrue((target / "plugin.json").is_file())
            self.assertFalse(atom_launch.sync_hook_copy(atom_launch.ROOT, target))

    def test_trigger_state_limit_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orig_home = atom_hook.HOME
            atom_hook.HOME = tmp
            try:
                with mock.patch.object(atom_hook, "notify_launcher"):
                    trigger_state.set_limit("gemini-3-pro", True)
                    lim = json.loads((Path(tmp) / "limits.json").read_text())
                    self.assertIn("gemini-3-pro", lim["models"])
                    trigger_state.set_limit("gemini-3-pro", False)
                    lim2 = json.loads((Path(tmp) / "limits.json").read_text())
                    self.assertNotIn("gemini-3-pro", lim2["models"])
            finally:
                atom_hook.HOME = orig_home

    def test_notify_socket_permissions_owner_only(self) -> None:
        if not hasattr(socket, "AF_UNIX") or os.name == "nt":
            self.skipTest("AF_UNIX POSIX socket permissions only apply on POSIX")
        with tempfile.TemporaryDirectory() as tmp:
            sock, sock_path, _ = atom_launch._open_notify_socket(Path(tmp))
            try:
                assert sock is not None and sock_path is not None
                mode = sock_path.stat().st_mode & 0o777
                self.assertEqual(mode, 0o600)
            finally:
                if sock is not None:
                    sock.close()


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(os.name == "nt", "Linux binary lookup")
class LinuxAppBinaryTests(unittest.TestCase):
    """Finding Antigravity when it was installed by hand, not by a package."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        real_check = atom_launch._is_app_binary
        # Only accept files inside this test's folder, so the machine's own install is ignored.
        self.patches = [
            mock.patch.object(Path, "home", return_value=self.home),
            mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.home / ".local" / "share"),
                                         "XDG_DATA_DIRS": str(self.tmp / "usr-share")}),
            mock.patch.object(atom_launch.shutil, "which", return_value=None),
            mock.patch.object(atom_launch, "_is_app_binary",
                              side_effect=lambda p: str(p).startswith(str(self.tmp)) and real_check(p)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        self._tmp.cleanup()

    def _exe(self, path: Path, body: str = "#!/bin/sh\n") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        path.chmod(0o755)
        return path

    def test_finds_extracted_archive(self) -> None:
        exe = self._exe(self.home / "Apps" / "Antigravity-2.30.0" / "antigravity")
        self.assertEqual(atom_launch._linux_app_binary(), str(exe))

    def test_reads_desktop_exec_and_skips_atom_entry(self) -> None:
        exe = self._exe(self.tmp / "my apps" / "AG" / "antigravity")
        apps = self.home / ".local" / "share" / "applications"
        apps.mkdir(parents=True)
        (apps / "antigravity.desktop").write_text(
            "[Desktop Entry]\nExec=python3 /x/atom_launch.py %U\nX-Atom-Mascot=true\n")
        (apps / "antigravity-manual.desktop").write_text(
            f'[Desktop Entry]\nExec=env ELECTRON_OZONE_PLATFORM_HINT=wayland "{exe}" %U\n')
        self.assertEqual(atom_launch._linux_app_binary(), str(exe))

    def test_skips_atom_wrapper_scripts(self) -> None:
        self._exe(self.home / "Antigravity" / "antigravity", "#!/bin/sh\nexec python3 ~/atom/atom_launch.py\n")
        self.assertEqual(atom_launch._linux_app_binary(), "/opt/Antigravity/antigravity")  # not found: default
        real = self._exe(self.home / "Antigravity" / "Antigravity")
        self.assertEqual(atom_launch._linux_app_binary(), str(real))
