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
`https://CDN_HOSTNAME/` still reaches Xray (404). For a second CDN (for example
CloudFront), append its origin-facing ranges to the same file and restart the unit.
Cloudflare's ranges change rarely, but re-fetch them if Cloudflare announces new ones.

## Notes

- The relay pins `CDN_HOSTNAME` to the zone's Cloudflare IPs (see its `.env`), so it
  never resolves the name over plain DNS. Cloudflare routes by SNI, so the zone's
  assigned IPs keep working even if Cloudflare rotates them later.
- The SNI (`CDN_HOSTNAME`) is visible to DPI on the relay → CDN leg. If it gets
  blocked by name, add a new domain + origin certificate (Xray picks a certificate by
  SNI from the `certificates` list) and switch the relay.
- Cloudflare Free is meant for websites; heavy video through it is a terms-of-service
  grey area. Watch Analytics, and keep a second CDN path as a fallback.
