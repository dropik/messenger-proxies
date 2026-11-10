#!/bin/sh
# Allow a Docker-published port only from CDN address ranges.
#
# Docker-published ports bypass ufw/INPUT rules, so the filter lives in the
# DOCKER-USER chain (FORWARD path) and matches the original destination port.
# Idempotent: safe to re-run after changing the ranges file.
set -e

PORT="${PORT:-8443}"
RANGES="${RANGES:-/etc/cdn-only-firewall/ips-v4}"
IF="${IF:-$(ip route show default | awk '{print $5; exit}')}"
CHAIN="CDN-ONLY-$PORT"

[ -s "$RANGES" ] || { echo "no ranges in $RANGES" >&2; exit 1; }

iptables -N "$CHAIN" 2>/dev/null || iptables -F "$CHAIN"
while read -r net; do
  case "$net" in ''|\#*) continue ;; esac
  iptables -A "$CHAIN" -s "$net" -j RETURN
done < "$RANGES"
iptables -A "$CHAIN" -j DROP

iptables -N DOCKER-USER 2>/dev/null || true
iptables -C DOCKER-USER -i "$IF" -p tcp -m conntrack --ctorigdstport "$PORT" -j "$CHAIN" 2>/dev/null \
  || iptables -I DOCKER-USER 1 -i "$IF" -p tcp -m conntrack --ctorigdstport "$PORT" -j "$CHAIN"

echo "port $PORT on $IF limited to $(grep -cvE '^(#|$)' "$RANGES") ranges"
