#!/bin/zsh
# Start Santa Claude, the Slack teammate (Socket Mode, runs on this Mac, uses the Claude subscription).
cd "${0:A:h}"
exec uv run python slackbot.py
