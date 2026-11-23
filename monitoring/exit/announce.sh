#!/bin/bash
# Post a message to the users' channel through the alert bot (silently, plain text).
#   announce.sh "текст"        or        echo "текст" | announce.sh
# The token and channel id are read from alertmanager/secrets/ with sudo and never appear in
# the process list: curl gets the URL through a config on stdin.
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)/alertmanager/secrets"
text=${1:-$(cat)}
[ -n "$text" ] || { echo "nothing to post" >&2; exit 1; }
chat=$(sudo cat "$D/users_channel_id")
printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$(sudo cat "$D/telegram_token")" \
  | curl -s --max-time 20 -K - --data-urlencode "chat_id=$chat" --data-urlencode "text=$text" \
      -d disable_notification=true \
  | python3 -c 'import json, sys; r = json.load(sys.stdin); print("posted" if r.get("ok") else "failed: " + r.get("description", "?"))'
