#!/bin/bash
# Mints a 1-hour GitHub App installation token scoped to ONE repo. Runs on the HOST as an sbx
# command secret, never inside the sandbox:
#   cp bin/mint-github-app-token.sh ~/.config/santa-claude/mint-token.sh   # outside any sbx mount
#   sbx secret set github --sandbox santa-claude --command ~/.config/santa-claude/mint-token.sh
# ~/.config/santa-claude/ holds private-key.pem (from the App) and app.env with:
#   APP_ID=…  INSTALLATION_ID=…  REPO=petclinic
set -euo pipefail
dir="$HOME/.config/santa-claude"
# shellcheck disable=SC1091
source "$dir/app.env"
b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }
now=$(date +%s)
header=$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)
payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' $((now - 60)) $((now + 540)) "$APP_ID" | b64url)
sig=$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -sign "$dir/private-key.pem" | b64url)
curl -fsS -X POST \
  -H "Authorization: Bearer $header.$payload.$sig" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/app/installations/$INSTALLATION_ID/access_tokens" \
  -d "{\"repositories\":[\"$REPO\"]}" |
  /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])'
