# Telegram SOCKS5 Proxy

SOCKS5 proxy for Telegram with username/password authentication. This proxy tunnels all TCP/UDP traffic, including calls.

## Quick Start

**1. Create password file:**

On VPS, create `danted.passwd`:
```
user:password
```

For example:
```
telegram:mySecurePassword123
```

**2. Run:**
```bash
docker compose up -d
```

## Configure Telegram

**Android/iOS:**
1. Settings → Data and Storage → Proxy
2. Add Proxy → SOCKS5
3. Server: `YOUR_VPS_IP`
4. Port: `1080`
5. Username: `telegram`
6. Password: `mySecurePassword123`

**Telegram Desktop:**
1. Settings → Network → Connection type → Use custom proxy
2. SOCKS5, Host: `YOUR_VPS_IP`, Port: `1080`
3. Username: `telegram`, Password: `mySecurePassword123`

## Features

- SOCKS4/SOCKS5 support
- Username/password authentication
- Both TCP and UDP tunneling
- Includes voice/video calls
- IPv4 and IPv6 support

## Logs

```bash
docker compose logs -f
```

