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

        # Idle poll trickles one unloaded state from PRELOAD_ORDER at a time, then atom_lab.js
        cdp.sent.clear()
        atom.last_preload = time.monotonic() - (atom_launch.PRELOAD_INTERVAL_SEC + 1.0)
        atom.poll(force=False)
        evals = [p["expression"] for m, p, sess, _ in cdp.sent if m == "Runtime.evaluate" and sess == "s1"]
        self.assertEqual(len(evals), 1)
        self.assertIn('__loadState("atom","thinking",', evals[0])

        cdp.sent.clear()
        atom.last_preload = time.monotonic() - (atom_launch.PRELOAD_INTERVAL_SEC + 1.0)
        atom.poll(force=False)
        evals = [p["expression"] for m, p, sess, _ in cdp.sent if m == "Runtime.evaluate" and sess == "s1"]
        self.assertEqual(len(evals), 1)
        self.assertIn("__mountLab(", evals[0])
        self.assertIn("s1", atom.lab_sessions)

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
        self.assertEqual(len(atom_launch.STATES), 19)
        self.assertEqual(atom_launch.load_skin_names(), ["atom", "base-qt", "chibi", "v2", "v2-wardrobe"])
        catalog = atom_launch.load_skin_catalog()
        self.assertEqual([(c["id"], c["name"], c["states"]) for c in catalog], [
            ("atom", "Atom", 19),
            ("base-qt", "base qt.", 19),
            ("v2", "Atom V2", 19),
            ("chibi", "Cozy Chibi", 19),
            ("v2-wardrobe", "Nobility Outfits", 19),
        ])
        wardrobe_entry = next(c for c in catalog if c["id"] == "v2-wardrobe")
        self.assertEqual(wardrobe_entry["variants"], ["carbon", "neon", "hydrogen", "orchestrator"])
        asset_dirs = [ROOT / "assets" / s for s in ("atom", "base-qt", "v2", "chibi", "v2-wardrobe")]
        asset_dirs.extend(ROOT / "assets" / "v2-wardrobe" / "variants" / v for v in ("neon", "hydrogen", "orchestrator"))
        for assets in asset_dirs:
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

    def test_lab_catalog_preview_and_skin_switch_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            for skin, extra in (("atom", None), ("cyber", {"name": "Cyber Atom", "tagline": "Neon visor", "accent": "#22d3ee"})):
                sdir = assets / skin
                sdir.mkdir(parents=True)
                for st in ("idle", "listening"):
                    (sdir / f"{st}.json").write_text(json.dumps({"w": 150, "h": 120, "cols": 1, "durations": [80], "loop": [0, 0]}))
                    (sdir / f"{st}.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
                if extra:
                    (sdir / "skin.json").write_text(json.dumps(extra))

            catalog = atom_launch.load_skin_catalog(assets)
            self.assertEqual([c["id"] for c in catalog], ["atom", "cyber"])
            self.assertEqual(catalog[1]["name"], "Cyber Atom")
            self.assertEqual(catalog[1]["tagline"], "Neon visor")
            self.assertEqual(catalog[1]["states"], 2)

            lab_js = atom_launch.build_lab_script(assets)
            self.assertIn('"Cyber Atom"', lab_js)

            cdp = FakeCdp()
            sr = atom_launch.StateReader(self.home)
            atom = atom_launch.Atom(cdp, state=sr, assets_dir=assets)
            atom.sessions["t1"] = "s1"
            atom.ready_sessions.add("s1")
            atom.session_skin["s1"] = "atom"
            atom.loaded_states["s1"] = {"idle", "listening"}

            # Page opened Atom Lab while lab wasn't mounted and "cyber" preview was missing
            atom.last_resync["s1"] = time.monotonic() - (atom_launch.RESYNC_SEC + 1.0)
            atom.poll()
            probe_id = cdp.sent[0][3]
            cdp.sent.clear()
            atom.handle({"id": probe_id, "result": {"result": {"value": {"lab": True, "previews": ["cyber"]}}}})
            evals = [p["expression"] for _, p, _, _ in cdp.sent]
            self.assertTrue(any("__mountLab(" in e for e in evals))
            self.assertTrue(any('__loadState("cyber","idle",' in e and ",true)" in e for e in evals))

            # User switches active skin to "cyber": idle preview isn't re-pushed, listening + __markSynced are
            atom.last_resync["s1"] = time.monotonic() - (atom_launch.RESYNC_SEC + 1.0)
            cdp.sent.clear()
            atom.poll()
            probe2_id = cdp.sent[0][3]
            cdp.sent.clear()
            atom.handle({"id": probe2_id, "result": {"result": {"value": "cyber"}}})
            evals2 = [p["expression"] for _, p, _, _ in cdp.sent]
            self.assertFalse(any('__loadState("cyber","idle",' in e for e in evals2))
            self.assertTrue(any('__loadState("cyber","listening",' in e for e in evals2))
            self.assertTrue(any('__atom.__markSynced("cyber")' in e for e in evals2))

            # Restarting Atom remembers "cyber" in prefs.json and inlines it as DEFAULT_SKIN
            self.assertEqual(atom_launch.load_prefs(self.home).get("skin"), "cyber")
            atom2 = atom_launch.Atom(FakeCdp(), state=atom_launch.StateReader(self.home), assets_dir=assets)
            self.assertEqual(atom2.saved_skin, "cyber")
            self.assertIn('const DEFAULT_SKIN="cyber";', atom2.script)

            # Switching back to "atom" updates prefs.json and build_bootstrap_script
            atom2.sessions["t1"] = "s2"
            atom2.ready_sessions.add("s2")
            atom2.last_resync["s2"] = time.monotonic() - (atom_launch.RESYNC_SEC + 1.0)
            atom2.poll()
            p_back = atom2.cdp.sent[0][3]
            atom2.handle({"id": p_back, "result": {"result": {"value": "atom"}}})
            self.assertEqual(atom_launch.load_prefs(self.home).get("skin"), "atom")
            self.assertEqual(atom2.saved_skin, "atom")


    def test_first_run_skin_is_v2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            for skin in ("atom", "v2"):
                sdir = assets / skin
                sdir.mkdir(parents=True)
                for st in ("idle", "listening"):
                    (sdir / f"{st}.json").write_text(json.dumps({"w": 150, "h": 120, "cols": 1, "durations": [80], "loop": [0, 0]}))
                    (sdir / f"{st}.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
            atom = atom_launch.Atom(FakeCdp(), state=atom_launch.StateReader(self.home), assets_dir=assets)
            self.assertEqual(atom_launch.FIRST_RUN_SKIN, "v2")
            self.assertEqual(atom.first_skin, "v2")
            self.assertIsNone(atom.saved_skin)
            # The injected script uses the same first-run skin
            self.assertIn('const FIRST_SKIN = "v2";', (atom_launch.ROOT / "atom_inject.js").read_text(encoding="utf-8"))

            only_atom = Path(tmp) / "only"
            (only_atom / "atom").mkdir(parents=True)
            for st in ("idle", "listening"):
                (only_atom / "atom" / f"{st}.json").write_text(json.dumps({"w": 150, "h": 120, "cols": 1, "durations": [80], "loop": [0, 0]}))
                (only_atom / "atom" / f"{st}.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
            atom2 = atom_launch.Atom(FakeCdp(), state=atom_launch.StateReader(self.home), assets_dir=only_atom)
            self.assertEqual(atom2.first_skin, "atom")


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
    def test_resolve_model_variant_and_live_wardrobe_switching(self) -> None:
        variants = ["carbon", "neon", "hydrogen", "orchestrator"]
        self.assertEqual(atom_launch.resolve_model_variant("Carbon (Heavy)", variants, "carbon"), "carbon")
        self.assertEqual(atom_launch.resolve_model_variant("Neon", variants, "carbon"), "neon")
        self.assertEqual(atom_launch.resolve_model_variant("Hydrogen 1.5", variants, "carbon"), "hydrogen")
        self.assertEqual(atom_launch.resolve_model_variant("Orchestrator", variants, "carbon"), "orchestrator")
        self.assertEqual(atom_launch.resolve_model_variant("gemini-3-flash", variants, "carbon"), "hydrogen")
        self.assertEqual(atom_launch.resolve_model_variant("claude-sonnet-4", variants, "carbon"), "neon")
        self.assertEqual(atom_launch.resolve_model_variant("claude-opus", variants, "carbon"), "carbon")
        self.assertEqual(atom_launch.resolve_model_variant("auto-planner", variants, "carbon"), "orchestrator")
        self.assertEqual(atom_launch.resolve_model_variant("", variants, "carbon"), "carbon")

        import base64
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            wdir = assets / "v2-wardrobe"
            raw_bytes = {
                v: b"RIFF00" + tag.encode() + b"00WEBPVP8 "
                for v, tag in (("carbon", "CARB"), ("neon", "NEON"), ("hydrogen", "HYDR"), ("orchestrator", "ORCH"))
            }
            for v, payload in raw_bytes.items():
                vdir = wdir if v == "carbon" else (wdir / "variants" / v)
                vdir.mkdir(parents=True)
                for st in ("idle", "listening"):
                    (vdir / f"{st}.json").write_text(json.dumps({"w": 150, "h": 120, "cols": 1, "durations": [80], "loop": [0, 0]}))
                    (vdir / f"{st}.webp").write_bytes(payload)
            b64 = {v: base64.b64encode(p).decode() for v, p in raw_bytes.items()}
            (wdir / "skin.json").write_text(json.dumps({
                "name": "Atom V2 Wardrobe",
                "tagline": "Per-model outfits",
                "accent": "#fbbf24",
                "defaultVariant": "carbon",
                "variants": variants,
            }))

            lab_js = atom_launch.build_lab_script(assets)
            self.assertIn('"variants":', lab_js)

            cdp = FakeCdp()
            home = Path(tmp) / "home"
            (home / "convs").mkdir(parents=True)
            sr = atom_launch.StateReader(home)
            atom = atom_launch.Atom(cdp, state=sr, assets_dir=assets)
            atom.sessions["t1"] = "s1"

            # Initial sync picks up activeSkin="v2-wardrobe" and defaults to "carbon"
            atom.probe_session("s1")
            p1 = cdp.sent[0][3]
            cdp.sent.clear()
            atom.handle({"id": p1, "result": {"result": {"value": "v2-wardrobe"}}})
            self.assertEqual(atom.session_variant["s1"], "carbon")
            evals1 = [p["expression"] for _, p, _, _ in cdp.sent]
            self.assertTrue(any('__loadState("v2-wardrobe","idle",' in e and b64["carbon"] in e for e in evals1))

            # UI model changes to Neon on resync -> triggers __resetSkin + neon idle sprite
            atom.last_resync["s1"] = time.monotonic() - (atom_launch.RESYNC_SEC + 1.0)
            cdp.sent.clear()
            atom.poll()
            self.assertIn("uiModel", cdp.sent[0][1]["expression"])
            p2 = cdp.sent[0][3]
            cdp.sent.clear()
            atom.handle({"id": p2, "result": {"result": {"value": {"n": None, "m": "Neon"}}}})
            self.assertEqual(atom.session_variant["s1"], "neon")
            evals2 = [p["expression"] for _, p, _, _ in cdp.sent]
            self.assertTrue(any('__resetSkin("v2-wardrobe")' in e for e in evals2))
            self.assertTrue(any('__loadState("v2-wardrobe","idle",' in e and b64["neon"] in e for e in evals2))

            # Hook / trigger_state --model changes activeModel to Orchestrator -> switches live!
            cdp.sent.clear()
            (home / "limits.json").write_text(json.dumps({
                "activeModel": "Orchestrator",
                "activeKey": "orchestrator",
                "models": {},
            }))
            atom.poll(force=True)
            self.assertEqual(atom.session_variant["s1"], "orchestrator")
            evals3 = [p["expression"] for _, p, _, _ in cdp.sent]
            self.assertTrue(any('__resetSkin("v2-wardrobe")' in e for e in evals3))
            self.assertTrue(any('__loadState("v2-wardrobe","idle",' in e and b64["orchestrator"] in e for e in evals3))

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
                    trigger_state.set_model("hydrogen")
                    lim3 = json.loads((Path(tmp) / "limits.json").read_text())
                    self.assertEqual(lim3["activeModel"], "hydrogen")
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

    def test_log_with_none_stderr_does_not_raise(self) -> None:
        with mock.patch("sys.stderr", None):
            atom_launch.log("test message", color="33")

    def test_launch_warns_when_app_exits_early_without_cdp(self) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(atom_launch, "HOME", Path(tmp)), \
                 mock.patch("atom_launch.signal.signal"), \
                 mock.patch("atom_launch._launch_windows", return_value=(mock_proc, None)), \
                 mock.patch("atom_launch._launch_posix", return_value=(mock_proc, None)), \
                 mock.patch("atom_launch.ensure_hooks_installed", return_value=None), \
                 mock.patch("atom_launch._acquire_lock", return_value=True), \
                 mock.patch("atom_launch._open_notify_socket", return_value=(None, None, None)), \
                 mock.patch("atom_launch.log") as mock_log:
                ret = atom_launch.main()
                self.assertEqual(ret, 0)
                mock_log.assert_called_with(atom_launch.EARLY_EXIT_MSG, color="33")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux binary lookup")
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
        real = self._exe(self.home / "Antigravity-2.30" / "Antigravity")
        self.assertEqual(atom_launch._linux_app_binary(), str(real))
