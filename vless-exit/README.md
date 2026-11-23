# VLESS exit (behind a CDN)

Foreign exit server for the [relay](../vless-relay/README.md). It accepts VLESS over
**xhttp + TLS 1.3** on port `8443`, and only from the CDN. Its IP never has to be
reachable from Russia, so an IP block there does not matter.

```
relay (RU) ──xhttp/TLS──▶ CDN edge (outside RU) ──▶ exit :8443 ──▶ internet
```

## 1. CDN (Cloudflare)

1. Add your domain to Cloudflare (Free plan) and point its nameservers there.
2. DNS: `A` record `CDN_HOSTNAME` → exit IP, **Proxied** (orange cloud).
   Keep it a first-level subdomain (`x.example.org`). Never add an unproxied record
   for the exit IP.
3. SSL/TLS → Overview: **Full (strict)**.
4. SSL/TLS → Origin Server → **Create Certificate** (ECC) for the domain. Save the
   certificate and key as `certs/cert.pem` and `certs/key.pem`.
5. Network: **gRPC on** (lets xhttp stream uploads over HTTP/2), WebSockets on.
6. Rules → Origin Rules: for `CDN_HOSTNAME`, **rewrite destination port to 8443**.
7. Caching → Cache Rules: **Bypass cache** for `CDN_HOSTNAME`.
8. Security: **Bot Fight Mode off**, **Browser Integrity Check off**.
   Either would challenge the relay's Xray client.

## 2. Exit server

```bash
docker run --rm teddysun/xray xray uuid      # -> RELAY_UUID
openssl rand -hex 8                          # -> XHTTP_PATH
cp config.json.example config.json           # fill RELAY_UUID and /XHTTP_PATH
mkdir -p certs && chmod 700 certs            # put cert.pem + key.pem here, chmod 600
docker compose up -d
```

Check locally (an HTTP 404 from Xray means TLS works):

```bash
curl -sk -o /dev/null -w '%{http_code}\n' --resolve CDN_HOSTNAME:8443:127.0.0.1 https://CDN_HOSTNAME:8443/
```

## 3. Firewall: CDN only

Docker-published ports **bypass ufw**, so a ufw rule does not protect `8443`. The
script in `firewall/` filters in Docker's `DOCKER-USER` chain instead.

```bash
sudo mkdir -p /etc/cdn-only-firewall
curl -fsS https://www.cloudflare.com/ips-v4 | sudo tee /etc/cdn-only-firewall/ips-v4
sudo install -m 755 firewall/cdn-only-firewall.sh /usr/local/sbin/cdn-only-firewall
sudo install -m 644 firewall/cdn-only-firewall.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now cdn-only-firewall
```

From any non-CDN host, `https://EXIT_IP:8443/` must now time out, while
`https://CDN_HOSTNAME/` still reaches Xray (404).

With a second CDN, let `update-ranges.sh` build the list from both sources (Cloudflare's
published list and AWS's `CLOUDFRONT_ORIGIN_FACING` ranges) and reapply the firewall.
It refuses to replace the file if either download comes back empty. Re-run it when
either CDN announces new ranges:

```bash
sudo sh firewall/update-ranges.sh
```

## 4. Second CDN: origin certificate (for CloudFront)

CloudFront needs the origin to be a **hostname** with a **publicly trusted**
certificate (it does not trust the Cloudflare Origin CA). Use a free dynDNS name
(for example DuckDNS) pointing at the exit, so the exit's IP is never tied to your
Cloudflare domain. Xray serves both certificates on `8443` and picks one by SNI.

```bash
mkdir -p acme && chmod 700 acme
cp acme/acme.env.example acme/acme.env            # set ACME_DOMAIN to the dynDNS name
read -rsp "DuckDNS token: " T && printf 'DuckDNS_Token=%s\n' "$T" > acme/duckdns.env \
  && chmod 600 acme/duckdns.env && unset T
sh acme/renew.sh                                   # issues via DNS-01, installs certs/origin-*.pem
```

Add the second certificate to the `cdn-in` inbound's `tlsSettings.certificates`:

```json
{ "certificateFile": "/etc/xray/certs/origin-fullchain.pem", "keyFile": "/etc/xray/certs/origin-key.pem" }
```

Daily renewal (restarts Xray only when the certificate actually changed):

```bash
sudo install -m 644 acme/acme-renew.service acme/acme-renew.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now acme-renew.timer
```

The DuckDNS token can edit every name in that DuckDNS account, so keep the account for
this only. It lives on the exit, which is fine: whoever controls the exit already
controls the traffic.

## 5. Second CDN: CloudFront (download legs and WebSocket fallback)

From the relay's datacenter, uploads to every foreign CDN except Cloudflare are
throttled (~0.2 MB/s), while downloads from them run at full speed. So:

- **CloudFront** points at the xhttp inbound (`8443`) and carries only the **download
  half** of split connections (the relay's `yt-split-*` outbounds upload via
  Cloudflare). CloudFront withholds an *idle* xhttp download stream, but streams it
  fine once data flows: 21 MB/s, 32/32 page loads in testing.
- **The fallback when Cloudflare fails is WebSocket through the same CloudFront
  distribution:** a second origin (the same dynDNS name, port `8444`) and a behavior whose
  path pattern is the WebSocket path. The inbound on `8444` is published in
  `docker-compose.yml` and covered by the firewall via `PORTS="8443 8444"`. Measured from the
  relay: about 3 MB/s down, 2 MB/s up.
  Gcore carried it until 2026-11-18, when TLS to its edge address was blocked from the
  relay's datacenter. Gcore also buffers xhttp download streams (stalls after ~300 KB), so it
  could only ever carry WebSocket.

```json
{
  "tag": "cdn-ws", "port": 8444, "protocol": "vless",
  "settings": { "clients": [{ "id": "RELAY_UUID", "email": "relay@cdn" }], "decryption": "none" },
  "streamSettings": {
    "network": "ws", "security": "tls",
    "tlsSettings": { "minVersion": "1.3", "alpn": ["http/1.1"],
      "certificates": [{ "certificateFile": "/etc/xray/certs/origin-fullchain.pem",
                         "keyFile": "/etc/xray/certs/origin-key.pem" }] },
    "wsSettings": { "path": "/WS_PATH" },
    "sockopt": { "trustedXForwardedFor": ["CF-Connecting-IP", "X-Amz-Cf-Id"] }
  }
}
```

`trustedXForwardedFor` (on both inbounds): the CDNs add `X-Forwarded-For` to every request,
and without this Xray logs a warning per request (about 100,000 a day here). Xray trusts the
header only when the CDN's own header is present. No rule on the exit uses the source address,
and the firewall admits only CDN ranges, so trusting it changes nothing else.

CloudFront distribution:

| Setting | Value |
|---|---|
| Origin domain | the dynDNS name (`ACME_DOMAIN`), HTTPS only, port **8443** |
| Origin response / keep-alive timeout | 60 s |
| Viewer protocol | HTTPS only; HTTP/2 and HTTP/3 on |
| Allowed methods | all |
| Cache policy | CachingDisabled |
| Origin request policy | **AllViewerExceptHostHeader** (forwarding Host breaks origin TLS: 502) |
| Compression, WAF, logging | off |
| Second origin (WebSocket fallback) | the same dynDNS name, HTTPS only, port **8444**, same timeouts, **origin path empty** |
| Behavior for the fallback | path pattern = `/WS_PATH`, that origin, GET/HEAD, CachingDisabled, AllViewerExceptHostHeader, no compression |

Gcore (removed): it was the WebSocket fallback until TLS to its edge was blocked from the
relay's datacenter on 2026-11-18. `update-ranges.sh` can still add its ~1,300 ranges with
`CDNS="cloudflare cloudfront gcore"`.

The firewall checks only new connections, so a list change doesn't touch established ones.
Origin changes in CloudFront can take several minutes to reach all edges. Until then,
requests may hit the old port; the exit answers 404 for paths it doesn't serve.

## 6. Host hardening

Same on the relay. Keys only for SSH: the drop-in sorts first because sshd keeps the
first value it reads, ahead of any provider files that enable passwords. Check that a key
login works before closing the current session.

```bash
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
  | sudo tee /etc/ssh/sshd_config.d/00-hardening.conf && sudo sshd -t && sudo systemctl reload ssh
```

Debian security and point-release updates install daily via `unattended-upgrades` (Debian's
own repositories only, so Docker and Tailscale never update on their own), without
rebooting. A kernel update leaves `/var/run/reboot-required`; the `HostRebootRequired`
alert fires after two days, and the reboot is done by hand.

```bash
sudo apt-get install -y unattended-upgrades
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
  | sudo tee /etc/apt/apt.conf.d/20auto-upgrades
```

## Notes

- Xray resolves destinations itself over DNS-over-HTTPS (`dns` block), not through
  Docker's embedded DNS. Through Docker, lookups inherit the host's resolvers (often
  including unreachable IPv6 ones) and parallel UDP queries get dropped by conntrack:
  in practice about 2,000 failed lookups a day, each a failed first attempt for the user.

- The relay pins `CDN_HOSTNAME` to the zone's Cloudflare IPs (see its `.env`), so it
  never resolves the name over plain DNS. Cloudflare routes by SNI, so the zone's
  assigned IPs keep working even if Cloudflare rotates them later.
- The SNI (`CDN_HOSTNAME`) is visible to DPI on the relay → CDN leg. If it gets
  blocked by name, add a new domain + origin certificate (Xray picks a certificate by
  SNI from the `certificates` list) and switch the relay.
- Cloudflare Free is meant for websites; heavy video through it is a terms-of-service
  grey area. Watch Analytics, and keep a second CDN path as a fallback.
