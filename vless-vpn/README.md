# VLESS VPN with REALITY Protocol

High-performance VPN using VLESS protocol with REALITY obfuscation for DPI bypass.

## What is REALITY?

REALITY disguises VLESS traffic as TLS to legitimate websites (like google.com). DPI can't distinguish it from regular HTTPS.

## Setup

**1. Generate UUID (on VPS):**
```bash
docker run --rm teddysun/xray xray uuid
# Example output: 00000000-0000-0000-0000-000000000000
```

**2. Generate REALITY keys (on VPS):**
```bash
docker run --rm teddysun/xray xray x25519
# You'll get: Private key and Public key
```

**3. Edit `config.json`:**
```bash
cp config.json.example config.json
nano config.json
```

Replace:
- `00000000-0000-0000-0000-000000000000` with your UUID
- `PrivateKeyHere` with your REALITY private key
- `www.google.com` with target domain (can be any legitimate HTTPS website)

**4. Run:**
```bash
docker compose up -d --build
docker compose logs
```

## Connect from Xray Client

### Android (v2rayNG)

1. Import subscription or add manually:
   - Protocol: VLESS
   - Address: `YOUR_VPS_IP`
   - Port: `443`
   - UUID: (your generated UUID)
   - Flow: `xtls-rprx-vision`
   - TLS: enabled
   - Reality: enabled
   - Public key: (your REALITY public key)
   - SNI: `www.google.com`

### Desktop (Qv2ray)

1. Settings → Inbound
2. New VLESS connection
3. Same settings as above

### Telegram

Just use the SOCKS or MTProto proxies instead - VLESS is for general VPN.

## Features

- VLESS protocol (lightweight, faster than Trojan)
- REALITY obfuscation (looks like normal HTTPS)
- XTLS Vision flow (optimized performance)
- IPv4 & IPv6 support
- DPI resistant

## Logs

```bash
docker compose logs -f
```
