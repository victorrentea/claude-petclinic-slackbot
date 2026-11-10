"""Print the last N top-level messages of a channel with their thread replies (debug helper)."""
import sys
from dotenv import dotenv_values
from slack_sdk import WebClient
c = WebClient(dotenv_values('.env')['SLACK_BOT_TOKEN'])
if len(sys.argv) < 2: sys.exit('usage: peek.py <channel-id> [n]')
ch, n = sys.argv[1], int(sys.argv[2] if len(sys.argv) > 2 else 3)
for m in reversed(c.conversations_history(channel=ch, limit=n)['messages']):
    print('MSG', m.get('user'), m.get('text', '')[:300])
    if m.get('reply_count'):
        for r in c.conversations_replies(channel=ch, ts=m['ts'])['messages'][1:]:
            print('   ↳', r.get('user'), r['text'][:400])
