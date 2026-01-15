# Telegram MTProto Proxy

Official Telegram MTProto proxy for bypassing blocks.

## Features

- Official Telegram MTProxy implementation
- Auto-generates secure secret
- Auto-downloads Telegram server configs
- Optional **Fake TLS** mode (traffic looks like HTTPS)
- Persistent data (secret survives restarts)

## Quick Start

```bash
docker compose up -d --build
```

Check logs for connection details:
```bash
docker compose logs
```

You'll see output like:
```
Connection details:
  Server: YOUR_IP
  Port: 8888
  Secret: abc123...

Telegram Links:
  tg://proxy?server=YOUR_IP&port=8888&secret=abc123...
  https://t.me/proxy?server=YOUR_IP&port=8888&secret=abc123...
```

## Configuration

Edit `docker-compose.yml`:

```yaml
environment:
  # Change listening port
  - PORT=443
  
  # Set external IP manually (if auto-detection fails)
  - EXTERNAL_IP=1.2.3.4
  
  # Enable Fake TLS (recommended for censored networks)
  # Traffic will look like HTTPS to google.com
  - FAKE_TLS_DOMAIN=www.google.com
```

## Fake TLS Mode

For heavily censored networks, enable Fake TLS to disguise MTProto traffic as regular HTTPS:

```yaml
environment:
  - FAKE_TLS_DOMAIN=www.google.com
```

This makes DPI see traffic that looks like TLS connections to google.com.

The proxy will output a special secret starting with `ee` - use that one in Telegram.

## Ports

| Host Port | Container Port | Purpose |
|-----------|----------------|---------|
| 8888 | 443 | MTProto proxy |

Change host port in `docker-compose.yml` if 8888 is taken:
```yaml
ports:
  - "9999:443"  # Use port 9999 instead
```

## Connect from Telegram

1. Open link from logs: `tg://proxy?server=...`
2. Or manually: **Settings** → **Data and Storage** → **Proxy** → **Add Proxy**
   - Type: MTProto
   - Server: your VPS IP
   - Port: 8888 (or your configured port)
   - Secret: from logs

## Sharing

Share the `https://t.me/proxy?...` link with others - clicking it auto-configures Telegram.

## Troubleshooting

### Check if running
```bash
docker compose ps
docker compose logs -f
```

### Regenerate secret
```bash
docker compose down
docker volume rm telegram_mtproxy_data
docker compose up -d
```

### Firewall
Make sure port 8888 (or your chosen port) is open:
```bash
# Ubuntu/Debian
sudo ufw allow 8888/tcp

# Or with iptables
sudo iptables -A INPUT -p tcp --dport 8888 -j ACCEPT
```
