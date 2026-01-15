# Telegram MTProto Proxy (Fake TLS)

High-performance Erlang MTProto proxy with **Fake TLS** support for bypassing DPI (Deep Packet Inspection).

## Features

- **Fake TLS mode** - traffic appears as HTTPS to any domain (e.g., google.com)
- **DD mode** - classic obfuscated mode
- High performance Erlang implementation
- Auto-generates secure secret
- Built-in stats endpoint
- Docker-ready

## Why Fake TLS?

Regular MTProto traffic can be detected and blocked by DPI. Fake TLS wraps the MTProto protocol inside TLS, making it look like regular HTTPS traffic to any website you choose. DPI will see a TLS handshake to `www.google.com` instead of Telegram.

## Quick Start

```bash
docker compose up -d --build
```

Check logs for connection details:
```bash
docker compose logs
```

Output:
```
==========================================
  MTProto Proxy (Erlang - Fake TLS)
==========================================

Server Configuration:
  IP: 1.2.3.4
  Port: 443
  Fake TLS Domain: www.google.com

==========================================
  Connection Links (Fake TLS - Recommended)
==========================================

Fake TLS Secret: ee1234567890abcdef...

tg://proxy?server=1.2.3.4&port=443&secret=ee1234567890abcdef...

https://t.me/proxy?server=1.2.3.4&port=443&secret=ee1234567890abcdef...
```

## Configuration

Edit `docker-compose.yml`:

```yaml
environment:
  # Port (443 recommended - looks like normal HTTPS)
  - PORT=443
  
  # Stats port
  - STATS_PORT=8888
  
  # External IP (auto-detected if not set)
  - EXTERNAL_IP=1.2.3.4
  
  # Fake TLS domain - traffic appears as HTTPS to this domain
  - FAKE_TLS_DOMAIN=www.google.com
  
  # Allowed protocols: tls, dd, or both
  # tls = Fake TLS (recommended)
  # dd = obfuscated mode (fallback)
  - ALLOWED_PROTOCOLS=tls,dd
  
  # Optional: Ad tag from @MTProxyBot
  # - TAG=your_ad_tag_here
```

## Secret Types

| Prefix | Mode | Description |
|--------|------|-------------|
| `ee` | Fake TLS | Looks like HTTPS traffic to specified domain |
| `dd` | DD | Simple obfuscation, easier to detect |

**Always use the `ee` (Fake TLS) secret** for better protection against DPI.

## Ports

| Port | Purpose |
|------|---------|
| 443 | MTProto proxy (looks like HTTPS) |
| 8888 | Stats endpoint |

## Stats

View proxy statistics:
```
http://YOUR_IP:8888/stats
```

## Connect from Telegram

### Method 1: Click Link
Copy the `tg://proxy?...` or `https://t.me/proxy?...` link from logs and open it.

### Method 2: Manual
1. **Settings** → **Data and Storage** → **Proxy**
2. **Add Proxy** → **MTProto**
3. Enter:
   - Server: your VPS IP
   - Port: 443
   - Secret: the `ee...` secret from logs

## Sharing

Share the `https://t.me/proxy?...` link - clicking it auto-configures Telegram.

## Troubleshooting

### Check if running
```bash
docker compose ps
docker compose logs -f
```

### Regenerate secret
```bash
docker compose down -v
docker compose up -d --build
```

### Connection issues
- Verify port 443 is open in firewall
- Check secret starts with `ee` for Fake TLS
- Try `dd` mode if TLS mode doesn't work

## Credits

Based on [seriyps/mtproto_proxy](https://github.com/seriyps/mtproto_proxy) - high-performance Erlang implementation.
