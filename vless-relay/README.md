# VLESS relay (Russia)

Entry point for clients inside Russia. Clients connect with VLESS over
**xhttp + REALITY**; the relay forwards traffic through a CDN to the
[exit](../vless-exit/README.md), or straight out, depending on the user.

```
client ──REALITY/xhttp (SNI = WHITELISTED_SNI)──▶ relay :443
                                                   ├─ forward@relay ──xhttp/TLS──▶ CDN ──▶ exit ──▶ internet
                                                   └─ direct@relay  ──────────────────────────────▶ internet (from RU)
```

## Design notes

- **SNI must be a whitelisted Russian site.** In mobile whitelist mode, the filter
  lets connections through based on the SNI; a generic Russian site does not pass.
  Pick one and test it on mobile data before relying on it.
- **`dest` is a local decoy, never the real site.** REALITY contacts `dest` on every
  client connection. Pointing it at the whitelisted site itself works at first, then
  that site blocks the relay's IP once traffic grows, and every client fails. The
  decoy (nginx with a self-signed certificate) answers instead. Clients never check
  the `dest` certificate, and in TLS 1.3 a passive observer cannot see it either.
- **One inbound, several users.** Two inbounds on the same port end up with two
  listeners and random distribution between them, so about half of connections fail
  authentication. Users are told apart with `email` and `"user"` routing rules.
- **`direct` is the first outbound**, so anything no rule matches never falls through
  to an exit that might be down.
- **The CDN hostname is pinned** to the zone's IPs (`.env`), so the relay never sends
  a plain-text DNS query for it.

## Setup

```bash
docker run --rm teddysun/xray xray x25519     # -> REALITY_PRIVATE_KEY (+ public key for clients)
docker run --rm teddysun/xray xray uuid       # once per user group -> FORWARD_UUID, DIRECT_UUID
openssl rand -hex 4                           # -> SHORT_ID
openssl rand -hex 8                           # -> CLIENT_XHTTP_PATH
cp config.json.example config.json            # fill placeholders; RELAY_UUID and XHTTP_PATH come from the exit
cp .env.example .env                          # CDN hostname + its two Cloudflare IPs

openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -keyout decoy/key.pem -out decoy/cert.pem -days 1095 \
  -subj "/CN=$(hostname -f)" && chmod 600 decoy/key.pem

docker compose up -d
```

## Client link

```
vless://USER_UUID@RELAY_IP:443?encryption=none&security=reality&sni=WHITELISTED_SNI&fp=chrome&pbk=REALITY_PUBLIC_KEY&sid=SHORT_ID&type=xhttp&path=%2FCLIENT_XHTTP_PATH&host=WHITELISTED_SNI&mode=auto#relay
```

Get the public key from the private one with `xray x25519 -i REALITY_PRIVATE_KEY`.

## Checks

```bash
docker run --rm -v $PWD/config.json:/c.json:ro teddysun/xray xray run -test -c /c.json
docker logs --since 10m vless-relay | grep accepted     # shows user and chosen outbound
```

If the CDN's IPs for the zone ever change, update `.env` and run `docker compose up -d`.
