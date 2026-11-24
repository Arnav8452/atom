#!/usr/bin/env python3
"""Antigravity hook -> Atom mascot state (read by atom_launch.py).

Antigravity runs this (via hooks.json) for every lifecycle event, with the
event payload as JSON on stdin. Hooks block the agent loop, so this stays
stdlib-only (-S -I safe), does tiny atomic file writes plus an optional datagram
wakeup, and always exits 0.

Event -> state (order verified against Antigravity):
  SessionStart              idle
  PreInvocation             thinking  (the first one of a turn also reads
                                       the user's prompt for a reaction)
  PreToolUse                typing    for tools that edit or write files,
                            thinking  for everything else (reading, search,
                                      commands, browsing)
  PostToolUse               thinking
  Stop                      idle

State lives in ~/.antigravity-atom (override with ATOM_HOME):
  convs/<conversationId>.json  {"state", "ts"}  one file per conversation, so
                                                parallel agents don't clobber
                                                each other
  emotion.json                 {"emotion", "ts"}           latest reaction
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time

HOME = os.environ.get("ATOM_HOME") or os.path.join(os.path.expanduser("~"), ".antigravity-atom")

EVENT_STATE = {
    "SessionStart": "idle",
    "PreInvocation": "thinking",
    "PreToolUse": "typing",
    "PostToolUse": "working",
    "PostInvocation": "working",
    "Stop": "idle",
}

BUSY_STATES = frozenset({"thinking", "typing", "working", "exploring", "running", "delegating", "asking"})
LIMIT_TTL_SEC = 5 * 3600
WEEKLY_LIMIT_TTL_SEC = 7 * 24 * 3600
QUOTA_ERROR_RE = re.compile(
    r"(?:"
    r"you\s+have\s+reached\s+the\s+quota\s+limit|"
    r"quota\b.*\b(?:exhaust\w*|exceed\w*|reach\w*|limit\w*)|"
    r"(?:exhaust\w*|exceed\w*|reach\w*)\s+(?:\w+\s+){0,4}quota|"
    r"rate\s*limit(?:ed)?|usage\s+limit|"
    r"plan(?:'s)?\s+(?:baseline\s+)?quota|"
    r"(?:5[-\s]?hour|weekly)\s+(?:quota|limit)|"
    r"resume\s+using\s+this\s+model\s+at|"
    r"too\s+many\s+requests|resource[_\s-]?exhausted|\b429\b"
    r")",
    re.IGNORECASE,
)
QUOTA_TERM_RE = re.compile(r"QUOTA|RATE_LIMIT|RESOURCE_EXHAUSTED|USAGE_LIMIT", re.IGNORECASE)
WEEKLY_LIMIT_RE = re.compile(r"week(?:ly)?|baseline\s+quota|next\s+week|\b\d+\s+days?\b", re.IGNORECASE)

# Tool classification for PreToolUse.
EDIT_TOOL_RE = re.compile(
    r"write|edit|replace|create_file|delete_file|file_change|code_action|propose_code|apply_patch|apply_diff|patch_file",
    re.IGNORECASE,
)
RUN_TOOL_RE = re.compile(r"run_command|bash|shell|terminal|\bexec\b", re.IGNORECASE)
DELEGATE_TOOL_RE = re.compile(r"invoke_subagent|swarm|run_workflow", re.IGNORECASE)
ASK_TOOL_RE = re.compile(r"ask_question", re.IGNORECASE)
EXPLORE_TOOL_RE = re.compile(r"read_file|view_file|grep|find|list_dir|search_web|browser_", re.IGNORECASE)

# Insults aimed at the agent (avoid common dev terms like "garbage collector" or "worst-case").
SAD_RE = re.compile(
    r"(?:"
    r"\b(stupid(?:er|est)?(?!-simple)|dumb(?:er|est)?(?!\s+terminal)|useless|worthless|hopeless|"
    r"incompetent|clueless|idiot(?:ic)?|moron(?:ic)?|imbecile|loser|clown|pathetic|"
    r"brain\s*dead|disappoint(?:ing|ed)|hate\s+(?:u|you)|bad\s+(?:ai|bot|agent)|"
    r"(?:u|you)\s+suck)\b"
    r"|"
    r"\b(?:you(?:'re|\s+are)|u(?:'re|\s+r)?|this\s+(?:is|code\s+is)|that(?:'s|\s+is))\s+"
    r"(?:so\s+|complete\s+|total\s+|pure\s+|utter\s+)?(?:trash|garbage|rubbish|the\s+worst|"
    r"horrible|terrible|awful)\b"
    r")",
    re.IGNORECASE,
)
# Profanity, abuse, hostility, and repeated frustration.
ANGRY_RE = re.compile(
    r"(?:"
    r"\b(wtf|wth|fu+ck+\w*|fck+\w*|fuk+(?:ing|er|ed|off)?|m(?:other)?f+u+c*k\w*|mofo\w*|"
    r"sh[i1]+t+\w*|bullsh[i1]+t+\w*|b[i1]tch\w*|bastard\w*|cunt\w*|"
    r"d[i1]ck(?:head|wad|face)\w*|d[i1]psh[i1]t\w*|dumbass\w*|jackass\w*|smartass\w*|"
    r"ass(?:hole|hat|wipe|clown)\w*|prick|wanker\w*|twat\w*|douche(?:bag)?\w*|"
    r"crap+(?:y)?|ffs|goddamn\w*|damn(?:\s+(?:it|u|you))?|bloody\s+hell|"
    r"for\s+(?:god'?s|fuck'?s|fuk'?s|chr[i1]st'?s)\s+sake|"
    r"(?:what|why)\s+the\s+(?:hell|heck|fu+ck+)|"
    r"shut\s+(?:the\s+(?:fu+ck+|fck|hell)\s+|your\s+mouth|it\s+)?up|stfu|gtfo|piss\s+off|"
    r"(?:screw|damn)\s+(?:u|you|this)|go\s+to\s+hell|drop\s+dead|get\s+lost|"
    r"piece\s+of\s+(?:sh[i1]+t+|crap|trash|garbage)|"
    r"are\s+you\s+(?:kidding(?:\s+me)?|serious|insane|crazy)|"
    r"still\s+(?:broken|not\s+working|failing)|broken\s+again|nothing\s+works|ugh+|argh+)\b"
    r"|"
    r"(?<!\w)(?:f[\*_]{1,3}c?k\w*|sh[\*_]{1,2}t\w*|a(?:\$\$|\*\*)[-\s]?hole\w*|b[\*_]tch\w*)(?!\w)"
    r")",
    re.IGNORECASE,
)
# Praise. Thanks-style phrases count anywhere (unless negated/sarcastic); bare
# adjectives only when the whole message is a short reaction ("perfect!"),
# because "make the landing page look amazing" is a task, not a compliment.
THANKS_RE = re.compile(
    r"\b(thanks|thank\s+you|thx|great\s+(job|work)|nice\s+(job|work|one)|"
    r"good\s+(job|bot)|well\s+done|love\s+(it|this|you)|you\s+rock)\b",
    re.IGNORECASE,
)
PRAISE_RE = re.compile(r"\b(awesome|amazing|perfect|brilliant|excellent|nice|great|beautiful)\b", re.IGNORECASE)
NEG_PRAISE_RE = re.compile(
    r"\b(no\s+thanks|thanks\s+for\s+nothing|not\s+(?:great|nice|good|awesome|amazing|perfect|helpful))\b",
    re.IGNORECASE,
)
PRAISE_MAX_WORDS = 4

CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PATH_RE = re.compile(r"(?:^|\s)(?:~?/|(?:\./|\.\./))[A-Za-z0-9._/@-]+")
SQL_VERBS = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "WITH"})
NON_SHOUT_TOKEN_RE = re.compile(r"[_=/\\<>\{\}\[\]\d]|::")


def _is_shouting(text: str) -> bool:
    tokens = text.split()
    if not tokens:
        return False
    first = tokens[0].strip("().,;:!?\"'").upper()
    if first in SQL_VERBS:
        return False
    alpha_words = [
        tok for tok in tokens
        if not NON_SHOUT_TOKEN_RE.search(tok) and any(c.isalpha() for c in tok)
    ]
    if len(alpha_words) < 3:
        return False
    letters = [c for tok in alpha_words for c in tok if c.isalpha()]
    return len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def normalize_model_name(name: str) -> str:
    s = str(name or "").strip().lower()
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def is_quota_error(term: str, error: object) -> bool:
    if QUOTA_TERM_RE.search(str(term or "")):
        return True
    err_text = str(error or "")
    return bool(err_text and QUOTA_ERROR_RE.search(err_text))


def update_model_limits(
    home: str,
    model: str,
    limited: bool | None,
    now: float,
    ttl: float = LIMIT_TTL_SEC,
) -> dict:
    limits_path = os.path.join(home, "limits.json")
    raw: dict = {}
    if os.path.isfile(limits_path):
        try:
            with open(limits_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                raw = loaded
        except (OSError, ValueError):
            raw = {}
    models_in = raw.get("models")
    models: dict[str, dict] = {}
    if isinstance(models_in, dict):
        for k, v in models_in.items():
            if not isinstance(v, dict) or not v.get("limited"):
                continue
            try:
                until = float(v.get("until", 0))
            except (TypeError, ValueError):
                until = 0.0
            if until > now:
                models[k] = v

    clean_model = str(model or "").strip()
    key = normalize_model_name(clean_model)
    if key:
        if limited is True:
            models[key] = {
                "name": clean_model,
                "limited": True,
                "ts": now,
                "until": now + ttl,
            }
        elif limited is False:
            models.pop(key, None)

    data: dict[str, object] = {
        "models": models,
        "activeModel": clean_model or str(raw.get("activeModel") or ""),
        "activeKey": key or str(raw.get("activeKey") or ""),
        "ts": now,
    }
    write_json(limits_path, data)
    return data


def detect_emotion(text: str) -> str | None:
    text = CODE_RE.sub(" ", text or "")
    text = URL_RE.sub(" ", text)
    text = PATH_RE.sub(" ", text).strip()
    if not text:
        return None
    if ANGRY_RE.search(text) or _is_shouting(text):
        return "angry"
    if SAD_RE.search(text):
        return "sad"
    if not NEG_PRAISE_RE.search(text) and (
        THANKS_RE.search(text) or (len(text.split()) <= PRAISE_MAX_WORDS and PRAISE_RE.search(text))
    ):
        return "happy"
    return None


def write_json(path: str, data: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = os.path.join(parent, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data))
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.005)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def notify_launcher() -> None:
    if hasattr(socket, "AF_UNIX"):
        sock_path = os.path.join(HOME, "notify.sock")
        if os.path.exists(sock_path):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                sock.setblocking(False)
                sock.sendto(b"!", sock_path)
                return
            except OSError:
                pass
            finally:
                sock.close()
    port_path = os.path.join(HOME, "notify.port")
    if os.path.isfile(port_path):
        try:
            with open(port_path, "r", encoding="utf-8") as fh:
                port = int(fh.read().strip())
            if 1 <= port <= 65535:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    sock.setblocking(False)
                    sock.sendto(b"!", ("127.0.0.1", port))
                finally:
                    sock.close()
        except (OSError, ValueError):
            pass


def classify_tool(tool_call: dict) -> str:
    tool = str(tool_call.get("name") or "")
    if EDIT_TOOL_RE.search(tool):
        return "typing"
    if RUN_TOOL_RE.search(tool):
        return "running"
    if DELEGATE_TOOL_RE.search(tool):
        args = tool_call.get("args") or {}
        if isinstance(args, dict) and str(args.get("TypeName") or "").lower() in ("browser", "research"):
            return "exploring"
        return "delegating"
    if ASK_TOOL_RE.search(tool):
        return "asking"
    if EXPLORE_TOOL_RE.search(tool):
        return "exploring"
    return "working"


# --- main -------------------------------------------------------------------

def handle(payload: dict) -> None:
    event = payload.get("hookEventName", "")
    state = EVENT_STATE.get(event)
    if state is None:
        return
    now = time.time()
    conv = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("conversationId") or "default"))[:80] or "default"
    conv_path = os.path.join(HOME, "convs", f"{conv}.json")
    emotion_path = os.path.join(HOME, "emotion.json")

    prev_state = None
    prev_mood = None
    if os.path.isfile(conv_path):
        try:
            with open(conv_path, "r", encoding="utf-8") as fh:
                prev = json.load(fh)
            if isinstance(prev, dict):
                prev_state = prev.get("state")
                if prev.get("mood") in ("angry", "sad"):
                    prev_mood = prev.get("mood")
        except (OSError, ValueError):
            prev_state = None
            prev_mood = None

    if event == "PreToolUse":
        tool_call = payload.get("toolCall")
        state = classify_tool(tool_call if isinstance(tool_call, dict) else {})
    elif event == "Stop":
        state = "watching" if payload.get("fullyIdle") is False else "idle"

    mood = None
    if event == "PreInvocation" and payload.get("invocationNum") == 0:
        # invocationNum 0 = first model call after a user message.
        # Angry/sad stay attached to this turn's conv state until Stop; happy stays a one-shot.
        emotion = detect_emotion(str(payload.get("lastUserInput") or ""))
        if emotion in ("angry", "sad"):
            mood = emotion
        elif emotion:
            write_json(emotion_path, {"emotion": emotion, "ts": now})
    elif event not in ("SessionStart", "Stop"):
        mood = prev_mood

    conv_data: dict[str, object] = {"state": state, "ts": now}
    if mood:
        conv_data["mood"] = mood
    write_json(conv_path, conv_data)

    model = str(payload.get("modelName") or "").strip()
    term = str(payload.get("terminationReason") or "")
    err = payload.get("error")
    err_text = str(err or "")

    if event == "Stop":
        if is_quota_error(term, err):
            ttl = WEEKLY_LIMIT_TTL_SEC if WEEKLY_LIMIT_RE.search(err_text) else LIMIT_TTL_SEC
            update_model_limits(HOME, model or "default", True, now, ttl=ttl)
        else:
            if model and not err and term != "ERROR":
                update_model_limits(HOME, model, False, now)
            if term == "ERROR" or err:
                write_json(emotion_path, {"emotion": "error", "ts": now})
            elif term == "USER_CANCELED":
                write_json(emotion_path, {"emotion": "canceled", "ts": now})
            elif term in ("MAX_INVOCATIONS", "MAX_FORCED_INVOCATIONS", "MAX_TOKEN_BUDGET_EXCEEDED"):
                write_json(emotion_path, {"emotion": "tired", "ts": now})
            elif term == "NO_TOOL_CALL" and prev_state in BUSY_STATES and prev_mood not in ("angry", "sad"):
                write_json(emotion_path, {"emotion": "done", "ts": now})
    elif event == "PostToolUse" and err:
        if is_quota_error("", err):
            ttl = WEEKLY_LIMIT_TTL_SEC if WEEKLY_LIMIT_RE.search(err_text) else LIMIT_TTL_SEC
            update_model_limits(HOME, model or "default", True, now, ttl=ttl)
        else:
            write_json(emotion_path, {"emotion": "error", "ts": now})
    elif event in ("PreToolUse", "PostToolUse", "PostInvocation"):
        if model:
            update_model_limits(HOME, model, False, now)
    elif event in ("SessionStart", "PreInvocation"):
        if model:
            update_model_limits(HOME, model, None, now)

    notify_launcher()


def main() -> None:
    event = None
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if isinstance(payload, dict):
            event = payload.get("hookEventName")
            try:
                handle(payload)
            except Exception:
                pass
    except Exception:
        pass
    # PreToolUse: print nothing, which leaves the permission decision to
    # Antigravity (any "decision" here would override the user's settings).
    # Every other event takes an empty JSON object as "no changes".
    if event != "PreToolUse":
        sys.stdout.write("{}")


if __name__ == "__main__":
    main()
