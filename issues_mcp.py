"""petclinic-issues: the bot's ONLY way to write to GitHub Issues - a narrow tool, not a credential.

Runs on the HOST (started by slackbot.py), listens on 127.0.0.1:ISSUES_MCP_PORT, reached from the
sandbox as http://host.docker.internal:<port>/mcp (sbx policy: allow localhost:<port>).
Inside the sandbox every GitHub API write stays denied by sbx policy; this server holds the
GitHub App token itself and can only touch issues of ONE hardcoded repo.
"""
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

REPO = "victorrentea/petclinic"
PORT = int(os.environ.get("ISSUES_MCP_PORT", "7431"))
MINT = os.path.expanduser("~/.config/santa-claude/mint-token.sh")  # 1-hour App token, host-only
log = logging.getLogger("petclinic-issues")

mcp = MCPServer("petclinic-issues", instructions=f"Create, comment on and edit issues of {REPO}.")
_token: tuple[str, float] = ("", 0.0)


def _github(method: str, path: str, payload: dict) -> dict:
    global _token
    if time.time() > _token[1]:
        _token = (subprocess.run([MINT], capture_output=True, text=True, check=True).stdout.strip(),
                  time.time() + 50 * 60)
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}", method=method,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {_token[0]}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub {e.code}: {e.read().decode()[:300]}") from None
    log.info("%s %s -> %s", method, path, res.get("html_url"))
    return {"number": res.get("number"), "url": res.get("html_url")}


@mcp.tool()
def create_issue(title: str, body: str, labels: list[str] | None = None) -> dict:
    """Open a new issue in the petclinic repo. Returns its number and URL."""
    return _github("POST", "issues", {"title": title, "body": body, "labels": labels or []})


@mcp.tool()
def comment_on_issue(number: int, body: str) -> dict:
    """Add a comment to petclinic issue (or PR) #number."""
    return _github("POST", f"issues/{number}/comments", {"body": body})


@mcp.tool()
def update_issue(number: int, title: str | None = None, body: str | None = None,
                 state: Literal["open", "closed"] | None = None,
                 labels: list[str] | None = None) -> dict:
    """Edit petclinic issue #number. Only the fields you pass change; `labels` REPLACES all labels."""
    changes = {k: v for k, v in
               {"title": title, "body": body, "state": state, "labels": labels}.items() if v is not None}
    if not changes:
        raise ValueError("nothing to change")
    return _github("PATCH", f"issues/{number}", changes)


def serve():
    """Blocking. Accepts the Host header the sandbox sends (host.docker.internal)."""
    mcp.run("streamable-http", host="127.0.0.1", port=PORT, transport_security=TransportSecuritySettings(
        allowed_hosts=[f"host.docker.internal:{PORT}", f"127.0.0.1:{PORT}", f"localhost:{PORT}"]))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
