"""Santa Claude: Claude as a teammate in Slack, working on the petclinic project.

1. answers  - @Santa Claude in a channel (or a DM) -> `claude -p`, one Claude session per Slack
              thread, so everyone replying in that thread talks to the same session (multiplayer).
2. acts     - code, local git, GitHub issues/CI, petclinic DB - inside the `claude-petclinic-slackbot` sbx sandbox.
3. proactive- watches channels it is in; after QUIET_SECONDS of silence it reads the recent
              conversation and speaks up only if it has something useful to add.

Runs on the subscription (`claude -p`), never on an API key.
"""
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import issues_mcp
from dotenv import load_dotenv
from slack_bolt import App
# websocket-client, not the builtin adapter: after the Mac slept, the builtin one looped on
# BrokenPipeError every 10 s for hours (10-11 Nov 2026) and never got a working socket back.
from slack_bolt.adapter.socket_mode.websocket_client import SocketModeHandler

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

WORKDIR = os.path.expanduser(os.environ.get("WORKDIR", str(HERE / "workdir")))
MODEL = os.environ.get("CLAUDE_MODEL", "sonnet")
WATCH_MODEL = os.environ.get("CLAUDE_WATCH_MODEL", "haiku")
# Every Claude turn runs INSIDE the Docker sandbox `claude-petclinic-slackbot` (sbx): it sees only WORKDIR,
# the network goes through sbx's proxy/policy, and secrets (Claude OAuth, GitHub token) are
# injected by that proxy - they never enter the sandbox.
SANDBOX = os.environ.get("SANDBOX", "claude-petclinic-slackbot")
MCP_CONFIG = "/home/agent/mcp.json"  # inside the sandbox: ONLY the petclinic Postgres MCP
TRIGGER_BUILD = "/home/agent/bin/trigger-build"  # inside the sandbox, root-owned
TOOLS = "Read,Grep,Glob,Edit,Write,Bash,WebSearch,WebFetch"
# Pre-approved. Anything else is denied, because `claude -p` cannot ask for permission.
# Edit/Write/Read are NOT listed: --permission-mode acceptEdits keeps them inside WORKDIR.
ALLOW = ",".join([
    "WebSearch", "WebFetch",
    "mcp__postgres-db",                                     # petclinic DB
    "mcp__petclinic-issues",                                # issue writes, via issues_mcp.py on the host
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
    "Bash(git add:*)", "Bash(git commit:*)", "Bash(git switch:*)", "Bash(git branch:*)",
    "Bash(gh api:*)",                                       # GitHub REST; sbx policy blocks all writes
    "Bash(gh run list:*)", "Bash(gh run view:*)",           # CI: read
    f"Bash({TRIGGER_BUILD})",                                # CI: push to claude/* only
])
PROACTIVE = os.environ.get("PROACTIVE", "1") == "1"
QUIET_SECONDS = int(os.environ.get("QUIET_SECONDS", "20"))
SESSIONS_FILE = HERE / "sessions.json"

PERSONA = (
    "You are 'Santa Claude', a teammate in a Slack workspace used for a live training demo. "
    "Several humans may talk to you in the same thread; each message is prefixed with the "
    "speaker's name. Reply in the language they use. Keep answers short and Slack-friendly "
    "(Slack mrkdwn: *bold*, `code`, bullet lists; no markdown headings or tables).\n"
    "You work on the petclinic project checked out in your working directory "
    "(github.com/victorrentea/petclinic). You can: read and edit its code, use git locally "
    "(commit on a feature branch, never on main), read GitHub issues with "
    "`gh api repos/victorrentea/petclinic/issues` / `.../issues/<n>` / `.../issues/<n>/comments` "
    "(`gh issue ...` does not work here: GraphQL is blocked), create, comment on, relabel, "
    "edit or close issues ONLY through the petclinic-issues MCP tools (any other GitHub write is "
    "blocked), "
    "read CI runs with `gh run list/view`, start a CI build by running "
    f"`{TRIGGER_BUILD}` (it pushes your current branch as claude/<branch>), "
    "and query the petclinic Postgres database through the postgres-db MCP tools. "
    "You have no access to email, other files on this machine, or anything else; if asked, say so."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)  # mcp sets up logging on import
log = logging.getLogger("santa-claude")

app = App(token=os.environ["SLACK_BOT_TOKEN"])
SANTA_USER_ID = app.client.auth_test()["user_id"]
Path(WORKDIR).mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
sessions: dict[str, str] = json.loads(SESSIONS_FILE.read_text()) if SESSIONS_FILE.exists() else {}
_names: dict[str, str] = {}


def save_sessions():
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=1))


def name_of(user_id: str) -> str:
    if user_id not in _names:
        try:
            u = app.client.users_info(user=user_id)["user"]
            _names[user_id] = u["profile"].get("display_name") or u["real_name"] or u["name"]
        except Exception:
            _names[user_id] = user_id
    return _names[user_id]


def run_claude(prompt: str, session_id: str | None = None, model: str = MODEL,
               tools: str = TOOLS, timeout: int = 300) -> tuple[str, str | None]:
    """One headless Claude turn on the subscription. Returns (text, session_id)."""
    # Defense in depth INSIDE the sandbox: no settings/CLAUDE.md/plugins/hooks, no claude.ai
    # connectors, only TOOLS, and only the ALLOW list pre-approved (`-p` denies everything else).
    cmd = ["sbx", "exec", "-w", WORKDIR, "-e", "ENABLE_CLAUDEAI_MCP_SERVERS=false", SANDBOX,
           "claude", "-p", prompt, "--output-format", "json", "--model", model,
           "--append-system-prompt", PERSONA,
           "--setting-sources", "", "--strict-mcp-config", "--tools", tools]
    if tools:  # the proactive watcher runs with tools="" : no tools, no MCP, no edits
        cmd += ["--mcp-config", MCP_CONFIG, "--permission-mode", "acceptEdits",
                "--allowedTools", ALLOW]
    if session_id:
        cmd += ["--resume", session_id]
    t0 = time.time()
    # stdin=DEVNULL: otherwise `claude -p` waits 3 s for piped stdin on every turn
    out = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                         timeout=timeout)
    log.info("claude %s in %.1fs (rc=%s)", model, time.time() - t0, out.returncode)
    try:
        res = json.loads(out.stdout)
        return res.get("result", "").strip(), res.get("session_id")
    except json.JSONDecodeError:
        return f"(error) {out.stderr.strip()[:500] or out.stdout.strip()[:500]}", session_id


def strip_mention(text: str) -> str:
    return text.replace(f"<@{SANTA_USER_ID}>", "").strip()


def answer(channel: str, thread_ts: str, user: str, text: str, msg_ts: str):
    key = f"{channel}:{thread_ts}"
    try:
        app.client.reactions_add(channel=channel, timestamp=msg_ts, name="eyes")
    except Exception:
        pass
    with _lock:
        sid = sessions.get(key)
    reply, new_sid = run_claude(f"{name_of(user)}: {strip_mention(text)}", sid)
    if new_sid:
        with _lock:
            sessions[key] = new_sid
            save_sessions()
    app.client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=reply or "(nothing to say)")


# ---------- 1+2: answer when mentioned (or when replying in a thread Claude is part of) ----------

@app.event("app_mention")
def on_mention(event):
    thread_ts = event.get("thread_ts") or event["ts"]
    threading.Thread(target=answer, args=(event["channel"], thread_ts, event["user"],
                                          event["text"], event["ts"]), daemon=True).start()


@app.event("message")
def on_message(event):
    if event.get("subtype") or event.get("bot_id") or event.get("user") == SANTA_USER_ID:
        return
    channel, text, user = event["channel"], event.get("text", ""), event["user"]
    if event.get("channel_type") == "im":  # DM: always answer, one session per DM thread
        thread_ts = event.get("thread_ts") or event["ts"]
        threading.Thread(target=answer, args=(channel, thread_ts, user, text, event["ts"]),
                         daemon=True).start()
        return
    if f"<@{SANTA_USER_ID}>" in text:
        return  # handled by app_mention
    thread_ts = event.get("thread_ts")
    if thread_ts and f"{channel}:{thread_ts}" in sessions:  # multiplayer: no need to re-tag
        threading.Thread(target=answer, args=(channel, thread_ts, user, text, event["ts"]),
                         daemon=True).start()
        return
    if PROACTIVE and not thread_ts:
        watcher.saw(channel)


# ---------- 3: proactive - speak up unprompted ----------

class Watcher:
    """Debounced channel watcher: after a quiet period, decide whether to chime in."""

    def __init__(self):
        self.timers: dict[str, threading.Timer] = {}

    def saw(self, channel: str):
        if t := self.timers.get(channel):
            t.cancel()
        t = threading.Timer(QUIET_SECONDS, self.consider, args=(channel,))
        t.daemon = True
        self.timers[channel] = t
        t.start()

    def consider(self, channel: str):
        hist = app.client.conversations_history(channel=channel, limit=15)["messages"][::-1]
        if hist and hist[-1].get("user") == SANTA_USER_ID:
            return
        # Skip join notices and @mentions: those were already answered in their own threads.
        hist = [m for m in hist if m.get("type") == "message" and not m.get("subtype")
                and f"<@{SANTA_USER_ID}>" not in m.get("text", "")]
        transcript = "\n".join(
            f"{'Santa Claude (you)' if m.get('user') == SANTA_USER_ID else name_of(m.get('user', '?'))}: {m.get('text', '')}"
            for m in hist)
        prompt = (
            "Here is the latest conversation in a Slack channel you are a member of. Nobody asked "
            "you anything. Speak up ONLY if you can add something genuinely useful: a factual "
            "correction, a risk they missed, a concrete answer to an open question, or an offer "
            "to do a task. If not, reply with exactly PASS.\n\n" + transcript)
        reply, _ = run_claude(prompt, model=WATCH_MODEL, tools="", timeout=120)
        if reply and reply.strip().upper() != "PASS" and not reply.startswith("(error)"):
            app.client.chat_postMessage(channel=channel, text=reply)


watcher = Watcher()

if __name__ == "__main__":
    log.info("Santa Claude user %s, workdir %s, proactive=%s", SANTA_USER_ID, WORKDIR, PROACTIVE)
    threading.Thread(target=issues_mcp.serve, daemon=True, name="petclinic-issues").start()
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
