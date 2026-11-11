#!/bin/sh
# Issue or renew the origin certificate (for CloudFront) with Let's Encrypt via a
# DNS-01 challenge, install it for Xray, and restart Xray only if it changed.
# Run daily by acme-renew.timer; safe to run by hand.
#
# acme/acme.env:      ACME_DOMAIN=name.duckdns.org   DNS_API=dns_duckdns
# acme/duckdns.env:   DuckDNS_Token=...   (secret, chmod 600)
set -e
cd "$(dirname "$0")/.."
. ./acme/acme.env
: "${ACME_DOMAIN:?set ACME_DOMAIN in acme/acme.env}" "${DNS_API:=dns_duckdns}"

mkdir -p acme/data && chmod 700 acme/data
acme() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/acme/data:/acme.sh" \
    --env-file acme/duckdns.env neilpang/acme.sh "$@"
}

src="acme/data/${ACME_DOMAIN}_ecc"
if [ ! -f "$src/fullchain.cer" ]; then
  acme --issue --server letsencrypt --dns "$DNS_API" --dnssleep 60 \
       -d "$ACME_DOMAIN" --keylength ec-256
else
  acme --cron || echo "acme.sh --cron reported a problem (see above)"
fi

new=$(sha256sum "$src/fullchain.cer" | cut -d' ' -f1)
old=$(sha256sum certs/origin-fullchain.pem 2>/dev/null | cut -d' ' -f1 || true)
if [ "$new" != "$old" ]; then
  install -m 600 "$src/fullchain.cer" certs/origin-fullchain.pem
  install -m 600 "$src/${ACME_DOMAIN}.key" certs/origin-key.pem
  docker restart vless-exit >/dev/null
  echo "installed new certificate for $ACME_DOMAIN, restarted vless-exit"
else
  echo "certificate for $ACME_DOMAIN unchanged"
fi
