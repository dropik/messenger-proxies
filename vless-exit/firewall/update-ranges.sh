#!/bin/sh
# Refresh the CDN address ranges allowed to reach the exit ports, then reapply the
# firewall. Sources: Cloudflare's published list, AWS ip-ranges.json (service
# CLOUDFRONT_ORIGIN_FACING) and Gcore's public CDN address lists. Run as root;
# re-run when a CDN announces new ranges. CDNS selects which ones to include.
set -e
OUT="${RANGES:-/etc/cdn-only-firewall/ips-v4}"
CDNS="${CDNS:-cloudflare cloudfront gcore}"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fetch_cloudflare() {
  curl -fsS --max-time 20 https://www.cloudflare.com/ips-v4 | grep -E '^[0-9.]+/[0-9]+$'
}
fetch_cloudfront() {
  curl -fsS --max-time 30 https://ip-ranges.amazonaws.com/ip-ranges.json | python3 -c 'import json,sys
for p in json.load(sys.stdin)["prefixes"]:
    if p["service"] == "CLOUDFRONT_ORIGIN_FACING": print(p["ip_prefix"])'
}
fetch_gcore() {
  for list in public-net-list public-ip-list; do
    curl -fsS --max-time 30 "https://api.gcore.com/cdn/$list" \
      | python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin)["addresses"]))'
  done
}

: > "$tmp/all"
for cdn in $CDNS; do
  "fetch_$cdn" | sort -u > "$tmp/$cdn"
  [ -s "$tmp/$cdn" ] || { echo "$cdn list came back empty; keeping $OUT" >&2; exit 1; }
  { echo "# $cdn ($(wc -l < "$tmp/$cdn") ranges)"; cat "$tmp/$cdn"; } >> "$tmp/all"
done

mkdir -p "$(dirname "$OUT")"
install -m 644 "$tmp/all" "$OUT"
systemctl restart cdn-only-firewall.service
grep '^#' "$OUT"
