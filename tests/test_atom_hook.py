import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import atom_hook  # noqa: E402


class DetectEmotionTests(unittest.TestCase):
    def test_positive_emotions(self) -> None:
        self.assertEqual(atom_hook.detect_emotion("you are useless"), "sad")
        self.assertEqual(atom_hook.detect_emotion("you idiot"), "sad")
        self.assertEqual(atom_hook.detect_emotion("you are worthless"), "sad")
        self.assertEqual(atom_hook.detect_emotion("this code is awful"), "sad")
        self.assertEqual(atom_hook.detect_emotion("this code is complete garbage"), "sad")
        self.assertEqual(atom_hook.detect_emotion("you're trash"), "sad")
        self.assertEqual(atom_hook.detect_emotion("that's the worst"), "sad")

        self.assertEqual(atom_hook.detect_emotion("wtf is happening"), "angry")
        self.assertEqual(atom_hook.detect_emotion("fuck u"), "angry")
        self.assertEqual(atom_hook.detect_emotion("shut up"), "angry")
        self.assertEqual(atom_hook.detect_emotion("stfu and fix this"), "angry")
        self.assertEqual(atom_hook.detect_emotion("what an asshole"), "angry")
        self.assertEqual(atom_hook.detect_emotion("stop being a dumbass"), "angry")
        self.assertEqual(atom_hook.detect_emotion("wtf you idiot"), "angry")
        self.assertEqual(atom_hook.detect_emotion("it is still broken"), "angry")
        self.assertEqual(atom_hook.detect_emotion("what bullshit"), "angry")
        self.assertEqual(atom_hook.detect_emotion("WHY IS THIS STILL NOT WORKING"), "angry")

        self.assertEqual(atom_hook.detect_emotion("thanks for the quick fix!"), "happy")
        self.assertEqual(atom_hook.detect_emotion("perfect!"), "happy")
        self.assertEqual(atom_hook.detect_emotion("nice work"), "happy")

    def test_technical_false_positives_ignored(self) -> None:
        cases = [
            "explain how the garbage collector works in Python",
            "move the temp files to the trash bin",
            "what is the worst-case time complexity here?",
            "keep the API stupid-simple please",
            "emulate a dumb terminal over PTY",
            "SELECT ID, NAME FROM USERS WHERE ACTIVE = 1",
            "INSERT INTO LOGS VALUES (1, 2, 3)",
            "MY_ENV_VAR=FOO API_KEY=BAR DB_HOST=LOCALHOST",
            "no thanks, skip that change",
            "thanks for nothing",
            "that is not great",
            "make the landing page look amazing and responsive everywhere",
            "check `wtf` in ```SELECT * FROM TRASH```",
            "see https://example.com/STUPID/PATH and /var/log/TRASH/ERROR.log",
            "you assign the value here and build the assets directory",
            "read the Fukushima documentation",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(atom_hook.detect_emotion(text))


class HookLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_home = atom_hook.HOME
        atom_hook.HOME = self.tmp.name

    def tearDown(self) -> None:
        atom_hook.HOME = self.orig_home
        self.tmp.cleanup()

    def _run_main(self, payload: dict) -> str:
        buf = io.StringIO()
        with (
            mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
            mock.patch.object(sys, "stdout", buf),
        ):
            atom_hook.main()
        return buf.getvalue()

    def test_events_and_stdout_contract(self) -> None:
        out = self._run_main({"hookEventName": "SessionStart", "conversationId": "conv-1"})
        self.assertEqual(out, "{}")
        conv = json.loads((Path(self.tmp.name) / "convs" / "conv-1.json").read_text())
        self.assertEqual(conv["state"], "idle")

        out = self._run_main({
            "hookEventName": "PreInvocation",
            "conversationId": "conv-1",
            "invocationNum": 0,
            "lastUserInput": "thanks!",
        })
        self.assertEqual(out, "{}")
        conv = json.loads((Path(self.tmp.name) / "convs" / "conv-1.json").read_text())
        emo = json.loads((Path(self.tmp.name) / "emotion.json").read_text())
        self.assertEqual(conv["state"], "thinking")
        self.assertEqual(emo["emotion"], "happy")

        for tool, expected in (
            ("write_file", "typing"),
            ("edit_file", "typing"),
            ("apply_patch", "typing"),
            ("delete_file", "typing"),
            ("run_command", "running"),
            ("bash", "running"),
            ("read_file", "exploring"),
            ("view_file", "exploring"),
            ("grep_search", "exploring"),
            ("search_web", "exploring"),
            ("browser_click", "exploring"),
            ("swarm", "delegating"),
            ("run_workflow", "delegating"),
            ("ask_question", "asking"),
            ("custom_unknown_tool", "working"),
        ):
            out = self._run_main({
                "hookEventName": "PreToolUse",
                "conversationId": "conv-1",
                "toolCall": {"name": tool},
            })
            self.assertEqual(out, "")
            conv = json.loads((Path(self.tmp.name) / "convs" / "conv-1.json").read_text())
            self.assertEqual(conv["state"], expected)

        # invoke_subagent browser/research -> exploring; other subagent -> delegating
        self._run_main({
            "hookEventName": "PreToolUse",
            "conversationId": "conv-1",
            "toolCall": {"name": "invoke_subagent", "args": {"TypeName": "browser"}},
        })
        conv = json.loads((Path(self.tmp.name) / "convs" / "conv-1.json").read_text())
        self.assertEqual(conv["state"], "exploring")

        self._run_main({
            "hookEventName": "PreToolUse",
            "conversationId": "conv-1",
            "toolCall": {"name": "invoke_subagent", "args": {"TypeName": "research"}},
        })
        conv = json.loads((Path(self.tmp.name) / "convs" / "conv-1.json").read_text())
        self.assertEqual(conv["state"], "exploring")

        self._run_main({
            "hookEventName": "PreToolUse",
            "conversationId": "conv-1",
            "toolCall": {"name": "invoke_subagent", "args": {"TypeName": "self"}},
        })
        conv = json.loads((Path(self.tmp.name) / "convs" / "conv-1.json").read_text())
        self.assertEqual(conv["state"], "delegating")

        out = self._run_main({"hookEventName": "PostToolUse", "conversationId": "conv-1"})
        self.assertEqual(out, "{}")
        conv = json.loads((Path(self.tmp.name) / "convs" / "conv-1.json").read_text())
        self.assertEqual(conv["state"], "working")

        out = self._run_main({"hookEventName": "PostInvocation", "conversationId": "conv-1"})
        self.assertEqual(out, "{}")
        conv = json.loads((Path(self.tmp.name) / "convs" / "conv-1.json").read_text())
        self.assertEqual(conv["state"], "working")

        out = self._run_main({
            "hookEventName": "Stop",
            "conversationId": "conv-1",
            "terminationReason": "NO_TOOL_CALL",
        })
        self.assertEqual(out, "{}")
        conv = json.loads((Path(self.tmp.name) / "convs" / "conv-1.json").read_text())
        emo = json.loads((Path(self.tmp.name) / "emotion.json").read_text())
        self.assertEqual(conv["state"], "idle")
        self.assertEqual(emo["emotion"], "done")

    def test_posttooluse_error_and_stop_reasons(self) -> None:
        emo_path = Path(self.tmp.name) / "emotion.json"

        self._run_main({
            "hookEventName": "PostToolUse",
            "conversationId": "c-err",
            "error": "exit status 1",
        })
        self.assertEqual(json.loads(emo_path.read_text())["emotion"], "error")

        # Stop from idle does not fire "done"
        emo_path.unlink()
        self._run_main({
            "hookEventName": "SessionStart",
            "conversationId": "c-idle",
        })
        self._run_main({
            "hookEventName": "Stop",
            "conversationId": "c-idle",
            "terminationReason": "NO_TOOL_CALL",
        })
        self.assertFalse(emo_path.exists())

        for reason, expected_emo in (
            ("ERROR", "error"),
            ("USER_CANCELED", "canceled"),
            ("MAX_INVOCATIONS", "tired"),
            ("MAX_TOKEN_BUDGET_EXCEEDED", "tired"),
        ):
            self._run_main({
                "hookEventName": "Stop",
                "conversationId": "c-stop",
                "terminationReason": reason,
            })
            self.assertEqual(json.loads(emo_path.read_text())["emotion"], expected_emo)

        # fullyIdle: False sets watching
        self._run_main({
            "hookEventName": "Stop",
            "conversationId": "c-watch",
            "fullyIdle": False,
        })
        conv = json.loads((Path(self.tmp.name) / "convs" / "c-watch.json").read_text())
        self.assertEqual(conv["state"], "watching")

    def test_sustained_angry_and_sad_turn_moods(self) -> None:
        conv_path = Path(self.tmp.name) / "convs" / "c-mood.json"
        emo_path = Path(self.tmp.name) / "emotion.json"

        # Angry message attaches mood="angry" to conv without emitting one-shot emotion.json
        self._run_main({
            "hookEventName": "PreInvocation",
            "conversationId": "c-mood",
            "invocationNum": 0,
            "lastUserInput": "fuck u fix this bug",
        })
        conv = json.loads(conv_path.read_text())
        self.assertEqual(conv["state"], "thinking")
        self.assertEqual(conv.get("mood"), "angry")
        self.assertFalse(emo_path.exists())

        # Mood persists through tools and intermediate invocations
        for payload in (
            {"hookEventName": "PreToolUse", "conversationId": "c-mood", "toolCall": {"name": "edit_file"}},
            {"hookEventName": "PostToolUse", "conversationId": "c-mood"},
            {"hookEventName": "PreInvocation", "conversationId": "c-mood", "invocationNum": 1},
            {"hookEventName": "PreToolUse", "conversationId": "c-mood", "toolCall": {"name": "run_command"}},
        ):
            self._run_main(payload)
            conv = json.loads(conv_path.read_text())
            self.assertEqual(conv.get("mood"), "angry")

        # Stop clears mood and suppresses "done" confetti so angry cools back to idle
        self._run_main({
            "hookEventName": "Stop",
            "conversationId": "c-mood",
            "terminationReason": "NO_TOOL_CALL",
        })
        conv = json.loads(conv_path.read_text())
        self.assertEqual(conv["state"], "idle")
        self.assertNotIn("mood", conv)
        self.assertFalse(emo_path.exists())

        # Sad insult persists until next user message clears mood (or triggers happy)
        self._run_main({
            "hookEventName": "PreInvocation",
            "conversationId": "c-mood",
            "invocationNum": 0,
            "lastUserInput": "you idiot",
        })
        self.assertEqual(json.loads(conv_path.read_text()).get("mood"), "sad")
        self._run_main({"hookEventName": "PostToolUse", "conversationId": "c-mood"})
        self.assertEqual(json.loads(conv_path.read_text()).get("mood"), "sad")

        self._run_main({
            "hookEventName": "PreInvocation",
            "conversationId": "c-mood",
            "invocationNum": 0,
            "lastUserInput": "thanks, looks good!",
        })
        conv = json.loads(conv_path.read_text())
        self.assertNotIn("mood", conv)
        self.assertEqual(json.loads(emo_path.read_text())["emotion"], "happy")

    def test_pretooluse_error_never_prints_stdout(self) -> None:
        buf = io.StringIO()
        with (
            mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"hookEventName": "PreToolUse"}))),
            mock.patch.object(sys, "stdout", buf),
            mock.patch.object(atom_hook, "handle", side_effect=OSError("disk full")),
        ):
            atom_hook.main()
        self.assertEqual(buf.getvalue(), "")

        buf2 = io.StringIO()
        with (
            mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"hookEventName": "PostToolUse"}))),
            mock.patch.object(sys, "stdout", buf2),
            mock.patch.object(atom_hook, "handle", side_effect=OSError("disk full")),
        ):
            atom_hook.main()
        self.assertEqual(buf2.getvalue(), "{}")

    def test_notify_socket_datagram(self) -> None:
        sock_path = os.path.join(self.tmp.name, "notify.sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        srv.settimeout(1.0)
        try:
            srv.bind(sock_path)
            atom_hook.handle({"hookEventName": "PostToolUse", "conversationId": "c1"})
            data = srv.recv(16)
            self.assertEqual(data, b"!")
        finally:
            srv.close()

    def test_notify_udp_port_fallback(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv.settimeout(1.0)
        try:
            srv.bind(("127.0.0.1", 0))
            port = srv.getsockname()[1]
            (Path(self.tmp.name) / "notify.port").write_text(str(port))
            atom_hook.notify_launcher()
            self.assertEqual(srv.recv(16), b"!")
        finally:
            srv.close()

    def test_isolated_subprocess_execution(self) -> None:
        env = {"ATOM_HOME": self.tmp.name, "PATH": os.environ.get("PATH", "")}
        proc = subprocess.run(
            [sys.executable, "-S", "-I", str(ROOT / "atom_hook.py")],
            input=json.dumps({"hookEventName": "PostToolUse", "conversationId": "sub1"}),
            text=True,
            capture_output=True,
            env=env,
            check=True,
        )
        self.assertEqual(proc.stdout, "{}")
        conv = json.loads((Path(self.tmp.name) / "convs" / "sub1.json").read_text())
        self.assertEqual(conv["state"], "working")

    def test_quota_limits_and_model_switch(self) -> None:
        lim_path = Path(self.tmp.name) / "limits.json"
        emo_path = Path(self.tmp.name) / "emotion.json"

        # 5-hour quota limit on Stop -> records model in limits.json without writing emotion="error"
        self._run_main({
            "hookEventName": "Stop",
            "conversationId": "c-lim",
            "modelName": "gemini-3-pro",
            "terminationReason": "ERROR",
            "error": "You have reached the quota limit for Gemini 3 Pro (5-hour quota).",
        })
        self.assertFalse(emo_path.exists())
        lim = json.loads(lim_path.read_text())
        self.assertEqual(lim["activeKey"], "gemini-3-pro")
        self.assertIn("gemini-3-pro", lim["models"])
        pro_entry = lim["models"]["gemini-3-pro"]
        self.assertTrue(pro_entry["limited"])
        self.assertAlmostEqual(pro_entry["until"] - pro_entry["ts"], atom_hook.LIMIT_TTL_SEC, delta=5.0)

        # Weekly limit on another model records ~7 day TTL independently
        self._run_main({
            "hookEventName": "Stop",
            "conversationId": "c-lim",
            "modelName": "claude-sonnet-4.5",
            "terminationReason": "ERROR",
            "error": "Weekly quota exhausted for Claude Sonnet 4.5. Refreshes in 6 days.",
        })
        lim = json.loads(lim_path.read_text())
        self.assertIn("gemini-3-pro", lim["models"])
        self.assertIn("claude-sonnet-4-5", lim["models"])
        claude_entry = lim["models"]["claude-sonnet-4-5"]
        self.assertAlmostEqual(claude_entry["until"] - claude_entry["ts"], atom_hook.WEEKLY_LIMIT_TTL_SEC, delta=5.0)

        # Switching to an available model updates activeModel without erasing existing limits
        self._run_main({
            "hookEventName": "SessionStart",
            "conversationId": "c-lim",
            "modelName": "gemini-3-flash",
        })
        lim = json.loads(lim_path.read_text())
        self.assertEqual(lim["activeModel"], "gemini-3-flash")
        self.assertIn("gemini-3-pro", lim["models"])
        self.assertIn("claude-sonnet-4-5", lim["models"])

        # Successful turn on claude-sonnet-4.5 clears its limit while leaving gemini-3-pro intact
        self._run_main({
            "hookEventName": "PreInvocation",
            "conversationId": "c-lim",
            "modelName": "claude-sonnet-4.5",
            "invocationNum": 0,
            "lastUserInput": "hi",
        })
        self.assertIn("claude-sonnet-4-5", json.loads(lim_path.read_text())["models"])
        self._run_main({
            "hookEventName": "Stop",
            "conversationId": "c-lim",
            "modelName": "claude-sonnet-4.5",
            "terminationReason": "NO_TOOL_CALL",
        })
        lim = json.loads(lim_path.read_text())
        self.assertNotIn("claude-sonnet-4-5", lim["models"])
        self.assertIn("gemini-3-pro", lim["models"])


if __name__ == "__main__":
    unittest.main()
