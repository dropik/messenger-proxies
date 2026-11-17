#!/bin/sh
# Allow Docker-published ports only from CDN address ranges.
#
# Docker-published ports bypass ufw/INPUT rules, so the filter lives in the
# DOCKER-USER chain (FORWARD path) and matches the original destination port.
# Only NEW connections are checked: with a few hundred CDN ranges, matching every
# packet of a busy stream would cost real CPU; established ones are then accepted
# by Docker's own conntrack rules. Idempotent: safe to re-run.
set -e

PORTS="${PORTS:-${PORT:-8443}}"
RANGES="${RANGES:-/etc/cdn-only-firewall/ips-v4}"
IF="${IF:-$(ip route show default | awk '{print $5; exit}')}"

[ -s "$RANGES" ] || { echo "no ranges in $RANGES" >&2; exit 1; }

iptables -N DOCKER-USER 2>/dev/null || true
for PORT in $PORTS; do
  CHAIN="CDN-ONLY-$PORT"
  iptables -N "$CHAIN" 2>/dev/null || iptables -F "$CHAIN"
  grep -vE '^(#|$)' "$RANGES" | sort -u | while read -r net; do
    iptables -A "$CHAIN" -s "$net" -j RETURN
  done
  iptables -A "$CHAIN" -j DROP
  # remove the older per-packet hook if present
  iptables -D DOCKER-USER -i "$IF" -p tcp -m conntrack --ctorigdstport "$PORT" -j "$CHAIN" 2>/dev/null || true
  iptables -C DOCKER-USER -i "$IF" -p tcp -m conntrack --ctstate NEW --ctorigdstport "$PORT" -j "$CHAIN" 2>/dev/null \
    || iptables -I DOCKER-USER 1 -i "$IF" -p tcp -m conntrack --ctstate NEW --ctorigdstport "$PORT" -j "$CHAIN"
  echo "port $PORT on $IF: new connections limited to $(grep -vE '^(#|$)' "$RANGES" | sort -u | wc -l) ranges"
done
