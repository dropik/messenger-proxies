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
- **`exit-cdn` uses xhttp `stream-up`**: uploads go as one long HTTP/2 stream instead
  of many small requests (about 6x faster uploads, far fewer CDN requests). It needs
  gRPC enabled at the CDN (Cloudflare: Network → gRPC); without it, use `packet-up`.
- **No access log.** Xray's access log would record every user's home IP next to the
  sites they visit, on a server under Russian jurisdiction. `"access": "none"` keeps
  only warnings and errors; turn it on briefly when debugging (see Checks).
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

## Subscriptions

One subscription URL per user group, served by a free Cloudflare Worker on
`*.workers.dev`, so it survives the relay going down and never reveals the exit's
domain. When the relay changes (new IP, SNI or key), regenerate and redeploy: apps
pick it up on their next refresh, with no new links to hand out.

```bash
python3 subscription/gen_worker.py --address RELAY_IP   # first run: creates tokens in subs.json
python3 subscription/gen_worker.py                      # after config changes: same tokens
```

Paste `subscription/worker.js` into the Worker editor (Workers & Pages → your Worker →
Edit code) and deploy. URLs are `https://WORKER.workers.dev/TOKEN`; any other path is
a 404. In client apps, turn on **update via proxy** where available, so refreshes go
through the VPN and the subscription host is never contacted directly from Russia.

## Checks

```bash
docker run --rm -v $PWD/config.json:/c.json:ro teddysun/xray xray run -test -c /c.json
docker logs --since 10m vless-relay                     # warnings and errors only
```

To see which user and outbound each connection takes while debugging, remove
`"access": "none"` from `log`, run `docker compose up -d --force-recreate`, check
`docker logs vless-relay | grep accepted`, then put it back and recreate again (that
also drops the logged lines).

If the CDN's IPs for the zone ever change, update `.env` and run `docker compose up -d`.
