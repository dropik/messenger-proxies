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
- **The Cloudflare outbounds rotate their connections every 10–15 minutes** (`xmux`: 4–8
  streams per connection, 200–400 requests or 600–900 s per connection). On 2026-11-20 the
  probe showed some long-lived pooled connections dropping to 0.2–3 MB/s, while fresh
  connections over the same path ran at 9–18 MB/s. Xray's default rotation (30–50 min)
  let a degraded connection serve requests for too long.
- **The Cloudflare outbounds are spread over both of the zone's IPs.** Xray only ever dials
  the first address a pinned hostname resolves to, so those outbounds name the second IP
  directly (`exit-cdn-2`, `yt-cf-2`, …), with `serverName` and xhttp `host` still set to the
  CDN hostname. On 2026-11-21 the health checks showed single Cloudflare connections freezing
  for 2–15 s while others to the same IP kept working; the `rest` balancer now has two
  outbounds, so health checks can steer away from a bad one.
- **TCP: BBR, no slow start after idle**, set in compose for the container's own network
  namespace. The host needs the module and the matching defaults:
  ```bash
  echo tcp_bbr > /etc/modules-load.d/bbr.conf && modprobe tcp_bbr
  printf 'net.core.default_qdisc = fq\nnet.ipv4.tcp_congestion_control = bbr\nnet.ipv4.tcp_slow_start_after_idle = 0\n' > /etc/sysctl.d/90-vpn-tcp.conf
  sysctl --system && tc qdisc replace dev eth0 root fq
  ```
- **From this datacenter, uploads to every foreign CDN except Cloudflare are throttled**
  (~0.2 MB/s to CloudFront and Gcore; downloads from them run at full speed). So
  Cloudflare carries all uploads, and other CDNs only ever carry download data.
- **Split connections (`yt-split-*`)** use xhttp's `downloadSettings`: the upload half
  goes via Cloudflare, the download half of the same session via CloudFront (both reach
  the exit's xhttp inbound, which joins them). Tested: 21 MB/s down, 15 MB/s up, 32/32
  fast page loads. This does **not** work through Gcore, which buffers xhttp download
  streams (stalls after ~300 KB).
- **Routing:**
  - YouTube (sniffed by domain, `geosite:youtube`) round-robins over the `yt-*`
    outbounds. The live relay uses 7 pure-Cloudflare clones and 3 split ones (~70/30);
    clone more or fewer to change the ratio (Xray balancers have no weights). This moves
    about 30% of YouTube's bytes onto CloudFront.
  - Everything else: Cloudflare (`exit-cdn` and `exit-cdn-2`, round-robin).
  - Fallback for both: `exit-cfws` (CloudFront, WebSocket on the exit's `8444`, routed by a
    path behavior in the same distribution). Gcore did this until 2026-11-18, when TLS to its
    edge address was blocked from the relay's datacenter. Page loads
    work, uploads are slow. The split outbounds depend on Cloudflare for uploads, so
    they cannot be a fallback for it.
  - Tested on a copy: normal (28 Cloudflare / 12 split YouTube requests), CloudFront
    broken (all YouTube via Cloudflare), Cloudflare broken (everything via Gcore), Gcore
    broken (no change).
- **Health checks:** `burstObservatory` pings every `exit-*` and `yt-*` outbound once a
  minute; unhealthy ones drop out of the balancers until they recover.
- With a single CDN, drop the extra outbounds, the observatory and the balancers, and
  route to `exit-cdn` directly.
- **Sniffing** (`routeOnly`) reads the domain from TLS/QUIC so phone clients in TUN
  mode, which send only IPs, still match the YouTube rule.
- **The CDN hostname is pinned** to the zone's IPs (`.env`), so the relay never sends
  a plain-text DNS query for it.

## Setup

```bash
docker run --rm teddysun/xray xray x25519     # -> REALITY_PRIVATE_KEY (+ public key for clients)
docker run --rm teddysun/xray xray uuid       # once per user group -> FORWARD_UUID, DIRECT_UUID
openssl rand -hex 4                           # -> SHORT_ID
openssl rand -hex 8                           # -> CLIENT_XHTTP_PATH
cp config.json.example config.json            # fill placeholders; RELAY_UUID and XHTTP_PATH come from the exit, CDN_IP_2 from .env
cp .env.example .env                          # CDN hostname + its two Cloudflare IPs

openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -keyout decoy/key.pem -out decoy/cert.pem -days 1095 \
  -subj "/CN=$(hostname -f)" && chmod 600 decoy/key.pem

docker compose up -d
```

Harden the host as for the exit ([key-only SSH, automatic security updates](../vless-exit/README.md#6-host-hardening)).
Rebooting the relay drops every client for about a minute, so pick a quiet hour.

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

First time, on the relay (creates the tokens), then add `"worker_name"` and
`"worker_host"` (e.g. `name.subdomain.workers.dev`) to `subscription/subs.json`:

```bash
python3 subscription/gen_worker.py --address RELAY_IP
```

After any relay config change, deploy from **your own machine** (Node.js, plus
`npx wrangler login` once). It regenerates on the relay over ssh, deploys with
wrangler, deletes the local copy and checks both URLs:

```bash
python vless-relay/subscription/deploy.py root@RELAY_IP
```

The Cloudflare login never touches the relay: whoever controls the relay must not be
able to rewrite the Worker and hand users a config of their own. URLs are
`https://WORKER_HOST/TOKEN`; any other path is a 404. In client apps, turn on **update via proxy** where available, so refreshes go
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

If the CDN's IPs for the zone ever change, update `.env` and the outbounds that name the
second IP in `config.json`, then run `docker compose up -d`.
