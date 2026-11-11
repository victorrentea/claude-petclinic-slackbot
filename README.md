# claude-petclinic-slackbot — "Santa Claude"

Claude as a teammate in a **free** Slack workspace (`test-agentic-how`), running on this Mac on the
Claude subscription (`claude -p`, no API key, no public URL — Socket Mode).

```
./start.sh            # tokens come from .env (SLACK_APP_TOKEN=xapp-…, SLACK_BOT_TOKEN=xoxb-…)
```

| demo | how |
|---|---|
| 1. answers | `@claude …` in a channel, or a DM |
| multiplayer | anyone replies in that thread, no re-tag needed: one Claude session per thread (`sessions.json`) |
| 2. acts | on its own petclinic clone in `./workdir` (see Permissions) |
| 3. proactive | after `QUIET_SECONDS` (20) of silence in a channel, Haiku reads the last messages and speaks up only if useful (`PROACTIVE=0` turns it off) |

Invite Santa Claude into a channel with `/invite @Santa Claude`.

## Sandbox (hard walls) — Docker Sandboxes `sbx`, sandbox `claude-petclinic-slackbot`
Every Claude turn runs as `sbx exec claude-petclinic-slackbot claude -p …` (see `run_claude` in slackbot.py).
The `slackbot.py` process on the Mac only does Slack I/O.

| wall | enforced by |
|---|---|
| files: only `./workdir` (its own petclinic clone) is mounted; `~/.claude`, `.env`, the rest of the Mac don't exist inside | sbx (microVM) |
| network: only the global sbx allow-list (AI APIs, registries, github) + `localhost:5432` for this sandbox; anything else → 403 | sbx proxy policy |
| Claude: subscription OAuth injected by the sbx proxy, no token inside | `sbx secret` (anthropic, oauth) |
| GitHub identity: App `santa-claude-petclinic`, installed on petclinic only: issues write, actions read, contents write. 1-hour token minted on the host by `bin/mint-github-app-token.sh` (copied to `~/.config/santa-claude/`), injected by the proxy | GitHub + `sbx secret set github --sandbox claude-petclinic-slackbot --command …` |
| no GitHub writes via API at all (incl. GraphQL): an app token can still open issues on ANY public repo, verified 9 Nov 2026 | sbx policy: deny POST/PATCH/PUT/DELETE on api.github.com, uploads.github.com |
| issue writes only through a narrow tool: `issues_mcp.py` (MCP over HTTP, thread in slackbot.py, `127.0.0.1:7431`) holds the App token on the host and can only create/comment/edit issues of victorrentea/petclinic | sbx policy `localhost:7431` + hardcoded repo in `issues_mcp.py` |
| never push `main`: ruleset where only admins + GitHub Actions bypass (`bin/protect-main.sh`) | GitHub |
| DB: dbhub MCP → `host.docker.internal:5432` (petclinic stack must be up) | sbx policy `localhost:5432` |

Inside, as defense in depth (enforced by Claude Code, not the OS): `--setting-sources ""`,
`--strict-mcp-config --mcp-config /home/agent/mcp.json`, `--tools`, `--allowedTools` (git local, `gh issue/run`
read, `/home/agent/bin/trigger-build` = push only to `claude/*`), `acceptEdits` in the workdir.

Recreate the sandbox with all its walls: `bin/create-sandbox.sh`.

Slack app config: `manifest.json` (create the app from it at https://api.slack.com/apps, Socket Mode).
`peek.py <channel-id> [n]` prints recent messages + thread replies for debugging.
