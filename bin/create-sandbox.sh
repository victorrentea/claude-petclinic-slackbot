#!/bin/zsh
# (Re)creates the sandbox every Claude turn runs in, with all its walls. Run on the HOST.
# Prerequisites: ~/.config/santa-claude/{mint-token.sh,app.env,private-key.pem} (see mint-github-app-token.sh)
# and the global sbx anthropic secret (`sbx secret set anthropic`, OAuth).
set -euo pipefail
cd "${0:A:h}/.."
S=${SANDBOX:-claude-petclinic-slackbot}

sbx create --name $S claude "$PWD/workdir"
# network: petclinic Postgres on the host; no GitHub writes over the API at all (incl. GraphQL)
sbx policy allow network --sandbox $S localhost:5432,localhost:7431  # DB + issues_mcp.py
sbx policy allow network --sandbox $S petclinic-production-28f17f61.up.railway.app  # the preview (bin/preview)
sbx policy deny network --sandbox $S api.github.com --method POST,PATCH,PUT,DELETE
sbx policy deny network --sandbox $S uploads.github.com --method POST,PATCH,PUT,DELETE
# GitHub identity: 1-hour App token minted on the host, injected by the sbx proxy
sbx secret set github --sandbox $S --command "$HOME/.config/santa-claude/mint-token.sh"
# MCP: the petclinic DB + issue writes through issues_mcp.py on the host
sbx cp mcp-sandbox.json $S:/home/agent/mcp.json
sbx exec -u root $S npm i -g @bytebase/dbhub@1.2.0
# the only way to start CI: push to claude/<branch>; root-owned so Claude can't rewrite it
sbx exec -u root $S mkdir -p /home/agent/bin
sbx cp bin/trigger-build $S:/home/agent/bin/trigger-build
sbx exec -u root $S sh -c 'chown root:root /home/agent/bin/trigger-build && chmod 755 /home/agent/bin/trigger-build'
echo "sandbox $S ready"
