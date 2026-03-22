# VLESS Proxy with xhttp + TLS

Intermediate proxy server that accepts VLESS connections over xhttp (HTTPS) and forwards them to the upstream VLESS/REALITY server. Non-VLESS traffic is served by nginx as a static website.

## Architecture

```
Browser (HTTPS)          → Nginx (443) → Static website (html/)
Client (VLESS+TLS+xhttp) → Nginx (443) → Xray → Upstream VLESS server
```

## Setup

**1. Place your TLS certificate:**
```bash
mkdir certs
cp /path/to/your/cert.pem certs/cert.pem
cp /path/to/your/key.pem  certs/key.pem
```

**2. Create Xray config:**
```bash
cp config.json.example config.json
```

Edit `config.json` and replace:
- `CLIENT_UUID` — UUID for your clients (generate: `docker run --rm teddysun/xray xray uuid`)
- `VPN_SERVER_IP` — IP address of the upstream VLESS server
- `VPN_UUID` — UUID configured on the upstream server
- `VPN_REALITY_PUBLIC_KEY` — REALITY public key from the upstream server
- `VPN_SHORT_ID` — Short ID from the upstream server config
- `/your-secret-path` — Choose a non-obvious path (e.g. `/api/v2/updates`)

**3. Create `nginx.conf`:**
```bash
cp nginx.conf.example nginx.conf
```

**4. Update `nginx.conf`:**

Replace:
- `YOUR_DOMAIN` — your actual domain name (two occurrences)
- `/your-secret-path` — must match the path in `config.json`

**5. Place your static site under `html/`:**

Put any static website files under the `html/` directory. Nginx will serve them for all requests that don't match the VLESS path. At minimum, provide an `index.html`.

**6. Start:**
```bash
docker compose up -d
docker compose logs -f
```

## Client Configuration

Configure your VLESS client (v2rayNG, Hiddify, etc.):

| Setting | Value |
|---------|-------|
| Protocol | VLESS |
| Address | your domain |
| Port | 443 |
| UUID | `CLIENT_UUID` from config.json |
| Flow | *(empty)* |
| Transport | xhttp |
| Path | `/your-secret-path` |
| TLS | enabled |
| SNI | your domain |

## Verify

```bash
# Website should load
curl -I https://your-domain.com

# Logs
docker compose logs -f xray-proxy
docker compose logs -f nginx
```
