import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import atom_cli_setup  # noqa: E402
import atom_status  # noqa: E402

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
NOW = 1_800_000_000.0


def plain(text: str) -> str:
    return ANSI_RE.sub("", text)


class ResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, rel: str, data: dict) -> None:
        path = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def resolve(self, payload: dict, now: float = NOW) -> dict:
        return atom_status.resolve(payload, home=self.home, now=now)

    def test_empty_payload_is_idle(self) -> None:
        self.assertEqual(self.resolve({})["state"], "idle")

    def test_busy_without_hook_state_maps_agent_state(self) -> None:
        self.assertEqual(self.resolve({"conversation_id": "c", "agent_state": "working"})["state"], "thinking")
        self.assertEqual(self.resolve({"conversation_id": "c", "agent_state": "tool_use"})["state"], "working")
        self.assertEqual(self.resolve({"conversation_id": "c", "agent_state": "reviewing"})["state"], "reviewing")

    def test_busy_uses_fresh_hook_state(self) -> None:
        self.write("convs/c.json", {"state": "running", "ts": NOW - 5})
        self.assertEqual(self.resolve({"conversation_id": "c", "agent_state": "tool_use"})["state"], "running")

    def test_stale_hook_state_ignored(self) -> None:
        self.write("convs/c.json", {"state": "running", "ts": NOW - 3600})
        self.assertEqual(self.resolve({"conversation_id": "c", "agent_state": "tool_use"})["state"], "working")

    def test_hook_state_of_other_conversation_ignored(self) -> None:
        self.write("convs/other.json", {"state": "typing", "ts": NOW})
        self.assertEqual(self.resolve({"conversation_id": "c", "agent_state": "working"})["state"], "thinking")

    def test_conversation_id_is_sanitised(self) -> None:
        self.write("convs/abc.json", {"state": "typing", "ts": NOW})
        # Same cleanup as atom_hook.py, so "../a/b/c" is the hook's "abc".
        info = self.resolve({"conversation_id": "../a/b/c", "agent_state": "working"})
        self.assertEqual(info["state"], "typing")
        self.assertEqual(os.listdir(os.path.join(self.home, "cli")), ["abc.json"])
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.home), "a")))

    def test_running_subagents(self) -> None:
        info = self.resolve({
            "conversation_id": "c",
            "agent_state": "working",
            "subagents": [{"name": "a", "status": "running"}, {"name": "b", "status": "completed"}],
        })
        self.assertEqual(info["state"], "delegating")
        self.assertEqual(info["detail"], "1 subagent running")

    def test_approval_wins(self) -> None:
        self.write("convs/c.json", {"state": "running", "ts": NOW})
        info = self.resolve({"conversation_id": "c", "agent_state": "tool_use", "tool_confirmation_pending": True})
        self.assertEqual(info["state"], "approval")

    def test_error_and_waking(self) -> None:
        self.assertEqual(self.resolve({"agent_state": "error"})["state"], "error")
        self.assertEqual(self.resolve({"agent_state": "initializing"})["state"], "waking")
        self.assertEqual(self.resolve({"agent_state": "authenticating"})["state"], "waking")

    def test_mood_carried_while_busy(self) -> None:
        self.write("convs/c.json", {"state": "thinking", "mood": "angry", "ts": NOW})
        info = self.resolve({"conversation_id": "c", "agent_state": "working"})
        self.assertEqual((info["state"], info["mood"]), ("thinking", "angry"))

    def test_happy_emotion_while_busy(self) -> None:
        self.write("emotion.json", {"emotion": "happy", "ts": NOW - 2})
        info = self.resolve({"conversation_id": "c", "agent_state": "working"})
        self.assertEqual(info["mood"], "happy")

    def test_turn_end_shows_done_then_persists(self) -> None:
        payload = {"conversation_id": "c", "agent_state": "working"}
        self.resolve(payload, now=NOW)
        payload["agent_state"] = "idle"
        self.assertEqual(self.resolve(payload, now=NOW + 1)["state"], "done")
        # A later redraw (resize etc.) keeps the reaction...
        self.assertEqual(self.resolve(payload, now=NOW + 60)["state"], "done")
        # ...until it expires.
        self.assertEqual(self.resolve(payload, now=NOW + atom_status.REACTION_TTL_SEC + 120)["state"], "idle")

    def test_turn_end_uses_fresh_hook_reaction(self) -> None:
        payload = {"conversation_id": "c", "agent_state": "working"}
        self.resolve(payload, now=NOW)
        self.write("emotion.json", {"emotion": "error", "ts": NOW + 0.5})
        payload["agent_state"] = "idle"
        self.assertEqual(self.resolve(payload, now=NOW + 1)["state"], "error")

    def test_late_stop_hook_reaction_replaces_done(self) -> None:
        payload = {"conversation_id": "c", "agent_state": "working"}
        self.resolve(payload, now=NOW)
        payload["agent_state"] = "idle"
        self.assertEqual(self.resolve(payload, now=NOW + 1)["state"], "done")
        self.write("emotion.json", {"emotion": "canceled", "ts": NOW + 2})
        self.assertEqual(self.resolve(payload, now=NOW + 3)["state"], "canceled")

    def test_idle_without_turn_stays_idle(self) -> None:
        self.write("emotion.json", {"emotion": "error", "ts": NOW})
        self.assertEqual(self.resolve({"conversation_id": "c", "agent_state": "idle"})["state"], "idle")

    def test_background_tasks(self) -> None:
        info = self.resolve({"conversation_id": "c", "agent_state": "idle", "task_count": 2})
        self.assertEqual((info["state"], info["detail"]), ("watching", "2 background tasks"))

    def test_all_quota_buckets_exhausted_sleeps(self) -> None:
        info = self.resolve({
            "conversation_id": "c",
            "agent_state": "idle",
            "quota": {
                "a": {"remaining_fraction": 0, "reset_in_seconds": 600},
                "b": {"remaining_amount": 0, "reset_in_seconds": 1200},
                "off": {"remaining_fraction": 0.5, "disabled": True},
            },
        })
        self.assertEqual(info["state"], "sleeping")
        self.assertTrue(info["detail"].startswith("back at "))

    def test_partial_quota_does_not_sleep(self) -> None:
        info = self.resolve({
            "agent_state": "idle",
            "quota": {"a": {"remaining_fraction": 0}, "b": {"remaining_fraction": 0.4}},
        })
        self.assertEqual(info["state"], "idle")

    def test_hook_limit_for_active_model_sleeps(self) -> None:
        self.write("limits.json", {
            "models": {"m": {"limited": True, "until": NOW + 300}},
            "activeKey": "m",
        })
        self.assertEqual(self.resolve({"agent_state": "idle"})["state"], "sleeping")
        # Expired limits don't.
        self.write("limits.json", {"models": {"m": {"limited": True, "until": NOW - 1}}, "activeKey": "m"})
        self.assertEqual(self.resolve({"agent_state": "idle"})["state"], "idle")

    def test_busy_never_sleeps(self) -> None:
        info = self.resolve({"agent_state": "working", "quota": {"a": {"remaining_fraction": 0}}})
        self.assertEqual(info["state"], "thinking")

    def test_bad_types_do_not_crash(self) -> None:
        info = self.resolve({
            "conversation_id": 12,
            "agent_state": None,
            "quota": [1, 2],
            "subagents": "x",
            "task_count": "3",
        })
        self.assertEqual(info["state"], "idle")

    def test_memory_file_holds_no_private_data(self) -> None:
        self.resolve({
            "conversation_id": "c",
            "agent_state": "working",
            "email": "someone@example.com",
            "conversation_title": "secret plans",
            "cwd": "/home/someone/secret",
            "transcript_path": "/tmp/t.jsonl",
        })
        stored = Path(self.home, "cli", "c.json").read_text(encoding="utf-8")
        self.assertEqual(set(json.loads(stored)), {"busy", "reaction", "reaction_ts", "ts"})
        for secret in ("someone", "example.com", "secret", "t.jsonl"):
            self.assertNotIn(secret, stored)


class RenderTests(unittest.TestCase):
    def test_every_state_renders_in_every_mode_and_skin(self) -> None:
        for skin in atom_status.SKINS:
            for state in atom_status.LOOKS:
                for style in ("sprite", "line"):
                    for mode in ("truecolor", "256", "none"):
                        info = {"state": state, "mood": None, "detail": "x"}
                        out = atom_status.render(info, 120, style, mode, skin)
                        self.assertIn("Atom", out, (skin, state, style, mode))
                        if mode == "none":
                            self.assertNotIn("\x1b", out)

    BAR = ("auto", "Gemini 4 Neon · high")

    def bar(self, state: str, width: int = 100, detail: str = "", mode: str = "truecolor") -> str:
        info = {"state": state, "mood": None, "detail": detail}
        return atom_status.render(info, width, "bar", mode, "v2", self.BAR)

    def test_bar_is_one_line_of_the_right_width(self) -> None:
        for width in (100, 60, 30):
            for state in atom_status.LOOKS:
                out = self.bar(state, width, "approve or deny the prompt above")
                self.assertNotIn("\n", out)
                self.assertLessEqual(atom_status.visible_len(out), max(10, width - atom_status.BAR_MARGIN) + 1)

    def test_bar_has_agy_info_left_and_face_at_the_end(self) -> None:
        out = plain(self.bar("thinking", mode="none"))
        self.assertTrue(out.startswith("auto · Gemini 4 Neon · high"))
        self.assertTrue(out.endswith("[" + atom_status.FACES["up"] + "]"))
        self.assertEqual(len(out), 100 - atom_status.BAR_MARGIN)
        self.assertIn("thinking…", out)

    def test_bar_face_column_is_fixed(self) -> None:
        ends = {len(plain(self.bar(state, mode="none"))) for state in ("idle", "thinking", "running", "done")}
        self.assertEqual(ends, {100 - atom_status.BAR_MARGIN})

    def test_bar_drops_detail_then_truncates_info_when_narrow(self) -> None:
        wide = plain(self.bar("approval", 120, "approve or deny the prompt above", "none"))
        self.assertIn("approve or deny", wide)
        narrow = plain(self.bar("approval", 60, "approve or deny the prompt above", "none"))
        self.assertNotIn("approve or deny", narrow)
        self.assertIn("needs your OK", narrow)
        tiny = plain(self.bar("thinking", 34, mode="none"))
        self.assertIn("…", tiny)
        self.assertTrue(tiny.endswith("]"))

    def test_agy_info_from_payload(self) -> None:
        self.assertEqual(atom_status.agy_info({}), ("auto", ""))
        payload = {"cycle_mode": "plan", "model": {"display_name": "Gemini 4 Argon (Medium)", "effort": "medium"}}
        self.assertEqual(atom_status.agy_info(payload), ("plan", "Gemini 4 Argon · medium"))
        payload = {"model": {"id": "x-model"}, "agent": {"name": "reviewer"}}
        self.assertEqual(atom_status.agy_info(payload), ("auto · reviewer", "x-model"))
        self.assertEqual(atom_status.agy_info({"model": None, "agent": "bad"}), ("auto", ""))

    def test_v2_has_no_legs(self) -> None:
        bottom = atom_status.SKINS["v2"]["grid"][-1]
        self.assertEqual(bottom.strip("."), "B" * len(bottom.strip(".")))  # one solid round bottom

    def test_big_view_is_agy_line_plus_sprite(self) -> None:
        info = {"state": "thinking", "mood": None, "detail": ""}
        out = plain(atom_status.render(info, 100, "big", "truecolor", "v2", self.BAR)).split("\n")
        self.assertEqual(out[0], "auto · Gemini 4 Neon · high")
        self.assertEqual(len(out), 8)
        self.assertTrue(any("Atom · thinking…" in line for line in out))
        # Too narrow or no colour: falls back to the bar.
        self.assertEqual(len(atom_status.render(info, 40, "big", "truecolor", "v2", self.BAR).split("\n")), 1)
        self.assertEqual(len(atom_status.render(info, 100, "big", "none", "v2", self.BAR).split("\n")), 1)

    def test_switch_follows_the_view_file(self) -> None:
        info = {"state": "idle", "mood": None, "detail": ""}
        with tempfile.TemporaryDirectory() as tmp:
            old = atom_status.HOME
            atom_status.HOME = tmp
            try:
                self.assertEqual(atom_status.read_view(), "bar")
                args = (info, 100, "switch", "truecolor", "v2", self.BAR)
                self.assertEqual(len(atom_status.render(*args).split("\n")), 1)
                atom_status.set_view("big")
                self.assertEqual(len(atom_status.render(*args).split("\n")), 8)
                atom_status.set_view("nonsense")
                self.assertEqual(atom_status.read_view(), "bar")
            finally:
                atom_status.HOME = old

    def test_v2_is_the_default_skin(self) -> None:
        self.assertEqual(atom_status.DEFAULT_SKIN, "v2")
        info = {"state": "idle", "mood": None, "detail": ""}
        self.assertEqual(atom_status.render(info, 120), atom_status.render(info, 120, skin="v2"))
        self.assertEqual(atom_status.get_skin("nope"), atom_status.SKINS["v2"])

    def test_skins_match_desktop_skin_ids(self) -> None:
        self.assertEqual(set(atom_status.SKINS), {"atom", "v2", "chibi", "base-qt"})

    def test_sprite_heights(self) -> None:
        info = {"state": "idle", "mood": None, "detail": ""}
        for skin, lines in (("v2", 7), ("atom", 5), ("chibi", 7), ("base-qt", 4)):  # v2 is 13 px, no legs
            out = atom_status.render(info, 120, "sprite", "truecolor", skin)
            self.assertEqual(len(out.split("\n")), lines, skin)

    def test_label_sits_level_with_the_eyes(self) -> None:
        info = {"state": "idle", "mood": None, "detail": "more"}
        for skin, sk in atom_status.SKINS.items():
            lines = plain(atom_status.render(info, 120, "sprite", "truecolor", skin)).split("\n")
            row = sk["eyes"][0][1] // 2
            self.assertIn("Atom · ready", lines[row], skin)

    def test_auto_style_by_width(self) -> None:
        info = {"state": "thinking", "mood": None, "detail": ""}
        self.assertGreater(len(atom_status.render(info, 120).split("\n")), 1)
        self.assertEqual(len(atom_status.render(info, 40).split("\n")), 1)

    def test_mood_changes_look_not_label(self) -> None:
        out = plain(atom_status.render({"state": "thinking", "mood": "angry", "detail": ""}, 40, "line", "none"))
        self.assertIn("thinking", out)
        self.assertIn(atom_status.FACES["angry"], out)

    def test_moods_leave_the_beanie_alone(self) -> None:
        calm = atom_status.sprite_pixels("idle", "v2")
        for mood in ("angry", "sad"):
            grid = atom_status.sprite_pixels(mood, "v2")
            self.assertEqual(grid[2], calm[2], mood)  # beanie row unchanged
            self.assertNotEqual(grid[10], calm[10], mood)  # body row tinted

    def test_256_colour_codes(self) -> None:
        out = atom_status.render({"state": "idle", "mood": None, "detail": ""}, 120, "sprite", "256")
        self.assertNotIn("38;2;", out)
        self.assertIn("38;5;", out)

    def test_grids_are_rectangular_and_use_known_letters(self) -> None:
        for skin, sk in atom_status.SKINS.items():
            widths = {len(row) for row in sk["grid"]}
            self.assertEqual(len(widths), 1, skin)
            letters = set("".join(sk["grid"])) - {"."}
            known = set(sk["palette"]) | ({"c"} if sk["crown"] else set())
            self.assertLessEqual(letters, known, skin)
            self.assertIn("B", sk["palette"], skin)

    def test_every_eye_shape_stays_on_the_face(self) -> None:
        for skin, sk in atom_status.SKINS.items():
            grid = sk["grid"]
            for name, shapes in atom_status.EYES.items():
                for (ox, oy), offsets in zip(sk["eyes"], shapes):
                    for dx, dy in offsets:
                        self.assertEqual(grid[oy + dy][ox + dx], "B", f"{skin}: {name} eye at {(ox + dx, oy + dy)}")

    def test_extras_inside_the_grid(self) -> None:
        for skin, sk in atom_status.SKINS.items():
            h, w = len(sk["grid"]), len(sk["grid"][0])
            for name in ("blush", "tear", "sweat"):
                self.assertIn(name, sk["extras"], skin)
                for x, y, _ in sk["extras"][name]:
                    self.assertTrue(0 <= x < w and 0 <= y < h, f"{skin} {name}")

    def test_skin_option_and_env(self) -> None:
        self.assertEqual(atom_status._parse_args([])["skin"], "v2")
        self.assertEqual(atom_status._parse_args(["--skin", "chibi"])["skin"], "chibi")
        self.assertEqual(atom_status._parse_args(["--skin=atom"])["skin"], "atom")
        self.assertEqual(atom_status._parse_args(["--skin", "bogus"])["skin"], "v2")
        old = os.environ.get("ATOM_SKIN")
        os.environ["ATOM_SKIN"] = "base-qt"
        try:
            self.assertEqual(atom_status._parse_args([])["skin"], "base-qt")
            self.assertEqual(atom_status._parse_args(["--skin", "atom"])["skin"], "atom")
        finally:
            if old is None:
                os.environ.pop("ATOM_SKIN", None)
            else:
                os.environ["ATOM_SKIN"] = old


class ProcessTests(unittest.TestCase):
    def run_status(self, stdin: str, *args: str, home: str | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.pop("NO_COLOR", None)
        with tempfile.TemporaryDirectory() as tmp:
            env["ATOM_HOME"] = home or tmp
            return subprocess.run(
                [sys.executable, "-S", "-I", str(ROOT / "atom_status.py"), *args],
                input=stdin, capture_output=True, text=True, encoding="utf-8", env=env, timeout=10,
            )

    def test_runs_isolated_and_exits_zero(self) -> None:
        payload = {"conversation_id": "c", "agent_state": "working", "terminal_width": 100, "email": "a@b.c"}
        proc = self.run_status(json.dumps(payload))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Atom", proc.stdout)
        self.assertIn("thinking", proc.stdout)
        self.assertNotIn("a@b.c", proc.stdout)
        self.assertEqual(proc.stderr, "")

    def test_garbage_input_prints_fallback(self) -> None:
        for stdin in ("not json", "[1,2]", "", "null"):
            proc = self.run_status(stdin)
            self.assertEqual(proc.returncode, 0, stdin)
            self.assertIn("Atom", proc.stdout, stdin)

    def test_unwritable_home_still_renders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocker = os.path.join(tmp, "file")
            Path(blocker).write_text("x", encoding="utf-8")
            proc = self.run_status(json.dumps({"conversation_id": "c", "agent_state": "idle"}), home=blocker)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("ready", proc.stdout)

    def test_demo(self) -> None:
        proc = self.run_status("", "--demo", "--color", "none")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("needs your OK", proc.stdout)
        self.assertIn("Atom V2", proc.stdout)

    def test_toggle_flips_and_prints(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            first = self.run_status("", "--toggle", home=home)
            self.assertEqual(first.returncode, 0)
            self.assertIn("big view", first.stdout)
            self.assertIn("bar view", self.run_status("", "--toggle", home=home).stdout)
            self.assertIn("big view", self.run_status("", "--view", "big", home=home).stdout)
            self.assertIn("big view", self.run_status("", "--view", "big", home=home).stdout)
            payload = json.dumps({"agent_state": "idle", "terminal_width": 100})
            out = self.run_status(payload, "--style", "switch", home=home).stdout
            self.assertGreater(len(out.strip().split("\n")), 1)

    def test_demo_all_skins(self) -> None:
        proc = self.run_status("", "--demo", "--skin", "all")
        self.assertEqual(proc.returncode, 0)
        for sk in atom_status.SKINS.values():
            self.assertIn(sk["name"], proc.stdout)


class SetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = os.path.join(self.tmp.name, "agy", "settings.json")
        self.bin = os.path.join(self.tmp.name, "bin")
        self.old_home = os.environ.get("ATOM_HOME")
        os.environ["ATOM_HOME"] = os.path.join(self.tmp.name, "atom")

    def tearDown(self) -> None:
        if self.old_home is None:
            os.environ.pop("ATOM_HOME", None)
        else:
            os.environ["ATOM_HOME"] = self.old_home
        self.tmp.cleanup()

    def read(self) -> dict:
        with open(self.settings, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def write(self, data, raw: str | None = None, bom: bool = False) -> None:
        os.makedirs(os.path.dirname(self.settings), exist_ok=True)
        text = raw if raw is not None else json.dumps(data)
        with open(self.settings, "w", encoding="utf-8-sig" if bom else "utf-8") as fh:
            fh.write(text)

    def setup(self, *args: str) -> int:
        with open(os.devnull, "w") as null:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = null
            try:
                return atom_cli_setup.main(["--settings", self.settings, "--bin", self.bin, *args])
            finally:
                sys.stdout, sys.stderr = old_out, old_err

    def test_install_creates_settings(self) -> None:
        self.assertEqual(self.setup(), 0)
        block = self.read()["statusLine"]
        self.assertEqual(block["type"], "command")
        self.assertFalse(block["stack_with_default"])  # switch replaces agy's line
        self.assertIn("--style switch", block["command"])
        self.assertIn("atom_status.py", block["command"])
        self.assertIn("-S -I", block["command"])

    @unittest.skipIf(os.name == "nt", "atom-toggle is a POSIX shell command; Windows uses atom_status.py --toggle")
    def test_install_writes_toggle_and_uninstall_removes_it(self) -> None:
        toggle = os.path.join(self.bin, "atom-toggle")
        self.assertEqual(self.setup(), 0)
        self.assertTrue(os.access(toggle, os.X_OK))
        with open(toggle, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("atom_status.py", body)
        self.assertIn("--toggle", body)
        self.assertEqual(self.setup("--uninstall"), 0)
        self.assertFalse(os.path.exists(toggle))

    def test_toggle_never_overwrites_someone_elses_command(self) -> None:
        os.makedirs(self.bin)
        toggle = os.path.join(self.bin, "atom-toggle")
        with open(toggle, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\necho mine\n")
        self.assertEqual(self.setup(), 0)
        self.assertEqual(self.setup("--uninstall"), 0)
        with open(toggle, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "#!/bin/sh\necho mine\n")

    def test_fixed_styles_skip_the_toggle(self) -> None:
        self.assertEqual(self.setup("--style", "bar"), 0)
        self.assertFalse(self.read()["statusLine"]["stack_with_default"])
        self.assertFalse(os.path.exists(os.path.join(self.bin, "atom-toggle")))

    def test_install_keeps_other_settings_and_bom(self) -> None:
        self.write({"model": "x", "nested": {"a": 1}}, bom=True)
        self.assertEqual(self.setup(), 0)
        data = self.read()
        self.assertEqual(data["model"], "x")
        self.assertEqual(data["nested"], {"a": 1})
        self.assertTrue(os.path.exists(self.settings + ".atom-backup"))

    def test_rerun_makes_no_backup(self) -> None:
        self.assertEqual(self.setup(), 0)
        self.assertEqual(self.setup(), 0)
        self.assertFalse(os.path.exists(self.settings + ".atom-backup"))

    def test_refuses_to_replace_existing_status_line(self) -> None:
        mine = {"type": "command", "command": "~/my.sh"}
        self.write({"statusLine": mine})
        self.assertEqual(self.setup(), 1)
        self.assertEqual(self.read()["statusLine"], mine)

    def test_force_then_uninstall_restores(self) -> None:
        mine = {"type": "command", "command": "~/my.sh", "padding": 1}
        self.write({"statusLine": mine})
        self.assertEqual(self.setup("--force"), 0)
        self.assertIn("atom_status.py", self.read()["statusLine"]["command"])
        self.assertEqual(self.setup("--uninstall"), 0)
        self.assertEqual(self.read()["statusLine"], mine)

    def test_uninstall_without_previous_removes_block(self) -> None:
        self.write({"model": "x"})
        self.setup()
        self.assertEqual(self.setup("--uninstall"), 0)
        self.assertEqual(self.read(), {"model": "x"})

    def test_uninstall_leaves_foreign_status_line(self) -> None:
        mine = {"type": "command", "command": "~/my.sh"}
        self.write({"statusLine": mine})
        self.assertEqual(self.setup("--uninstall"), 0)
        self.assertEqual(self.read()["statusLine"], mine)

    def test_reinstall_keeps_user_tweaks(self) -> None:
        self.setup()
        data = self.read()
        data["statusLine"]["padding"] = 2
        self.write(data)
        self.assertEqual(self.setup("--style", "sprite"), 0)
        block = self.read()["statusLine"]
        self.assertEqual(block["padding"], 2)
        self.assertTrue(block["stack_with_default"])  # sprite stacks under agy's line
        self.assertIn("--style sprite", block["command"])
        self.assertEqual(self.setup(), 0)
        self.assertFalse(self.read()["statusLine"]["stack_with_default"])

    def test_invalid_json_untouched(self) -> None:
        self.write(None, raw="{ not json")
        self.assertEqual(self.setup(), 1)
        with open(self.settings, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{ not json")

    def test_dry_run_writes_nothing(self) -> None:
        self.assertEqual(self.setup("--dry-run"), 0)
        self.assertFalse(os.path.exists(self.settings))

    def test_bad_options(self) -> None:
        self.assertEqual(self.setup("--style", "huge"), 2)
        self.assertEqual(self.setup("--nope"), 2)

    def test_windows_command_quoting(self) -> None:
        cmd = atom_cli_setup.build_command("python3", windows=True)
        self.assertRegex(cmd, r'^python3 -S -I ".*atom_status\.py"$')
        cmd = atom_cli_setup.build_command("python3", "line", "256", windows=False)
        self.assertRegex(cmd, r"atom_status\.py'? --style line --color 256$")  # quoted when the path has backslashes
        cmd = atom_cli_setup.build_command("python3", skin="chibi", windows=False)
        self.assertRegex(cmd, r"atom_status\.py'? --skin chibi$")
        self.assertNotIn("--skin", atom_cli_setup.build_command("python3", windows=False))

    def test_setup_knows_every_skin(self) -> None:
        self.assertEqual(set(atom_cli_setup.SKIN_IDS), set(atom_status.SKINS))

    def test_skin_option(self) -> None:
        self.assertEqual(self.setup("--skin", "atom"), 0)
        self.assertIn("--skin atom", self.read()["statusLine"]["command"])
        self.assertEqual(self.setup("--skin", "nope"), 2)


if __name__ == "__main__":
    unittest.main()
