#!/bin/sh
# Refresh the CDN address ranges allowed to reach the exit port, then reapply the
# firewall. Sources: Cloudflare's published list and AWS ip-ranges.json
# (service CLOUDFRONT_ORIGIN_FACING). Run as root; re-run when either CDN announces
# new ranges.
set -e
OUT="${RANGES:-/etc/cdn-only-firewall/ips-v4}"
tmp=$(mktemp)
trap 'rm -f "$tmp" "$tmp.cf" "$tmp.aws"' EXIT

curl -fsS --max-time 20 https://www.cloudflare.com/ips-v4 \
  | grep -E '^[0-9.]+/[0-9]+$' > "$tmp.cf"
curl -fsS --max-time 30 https://ip-ranges.amazonaws.com/ip-ranges.json \
  | python3 -c 'import json,sys
for p in json.load(sys.stdin)["prefixes"]:
    if p["service"] == "CLOUDFRONT_ORIGIN_FACING": print(p["ip_prefix"])' \
  | sort -u > "$tmp.aws"

[ -s "$tmp.cf" ] && [ -s "$tmp.aws" ] || { echo "a range list came back empty; keeping $OUT" >&2; exit 1; }

{
  echo "# Cloudflare ($(wc -l < "$tmp.cf") ranges)"
  cat "$tmp.cf"
  echo "# CloudFront origin-facing ($(wc -l < "$tmp.aws") ranges)"
  cat "$tmp.aws"
} > "$tmp"

mkdir -p "$(dirname "$OUT")"
install -m 644 "$tmp" "$OUT"
systemctl restart cdn-only-firewall.service
echo "allowed: $(wc -l < "$tmp.cf") Cloudflare + $(wc -l < "$tmp.aws") CloudFront ranges"
