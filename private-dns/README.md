# Private DNS for WhatsApp Proxy

DNS-over-TLS server using AdGuard Home with Let's Encrypt certificates via DuckDNS.

## What This Does

When Android users set this as their **Private DNS**, all their DNS queries go through your server encrypted (DoT). The server redirects WhatsApp/Facebook CDN domains to your proxy IP while forwarding everything else to upstream DNS.

```
User's Phone → Private DNS (DoT) → Your VPS
                     ↓
         DNS rewrites *.whatsapp.net → Your VPS IP
         DNS rewrites *.fbcdn.net → Your VPS IP
         Other domains → Cloudflare/Google DNS
```

## Prerequisites

1. **DuckDNS account** - Free at https://www.duckdns.org
2. **A subdomain** created on DuckDNS (e.g., `myproxy` → `myproxy.duckdns.org`)
3. **Port 853** open on your VPS firewall (for DNS-over-TLS)
4. **WhatsApp proxy** running (from `../whatsapp/`)

## Setup

### 1. Configure Environment

```bash
cp config/env.example config/env
nano config/env
```

Fill in:
- `DUCKDNS_SUBDOMAIN` - Your DuckDNS subdomain (just the name, not full domain)
- `DUCKDNS_TOKEN` - Your DuckDNS token (from the website)
- `PROXY_IP` - Your VPS public IP address

### 2. Build and Start

```bash
docker compose up -d --build
```

First run will:
1. Update DuckDNS with your VPS IP
2. Get Let's Encrypt certificate using DNS-01 challenge
3. Start AdGuard Home with DNS-over-TLS enabled

### 3. Configure Admin Password

Open web UI at `http://your-vps-ip:3000`

**Default credentials:**
- Username: `admin`
- Password: `admin`

**Change the password immediately!**

## Configure Android Private DNS

1. Go to **Settings** → **Network & Internet** → **Private DNS**
2. Select **Private DNS provider hostname**
3. Enter your domain: `yoursubdomain.duckdns.org`
4. Save

Now all DNS queries from your phone are encrypted and WhatsApp traffic routes through your proxy!

## Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 53 | TCP/UDP | Standard DNS (optional) |
| 853 | TCP/UDP | DNS-over-TLS (Private DNS) |
| 443 | TCP | DNS-over-HTTPS |
| 3000 | TCP | Web UI |

## DNS Rewrites

The following domains are redirected to your proxy:

- `*.whatsapp.net` → Your VPS IP
- `*.whatsapp.com` → Your VPS IP  
- `*.fbcdn.net` → Your VPS IP (media CDN)
- `*.cdninstagram.com` → Your VPS IP (some media)

You can add more in AdGuard Home web UI under **Filters** → **DNS rewrites**.

## Certificate Renewal

Certificates auto-renew when the container restarts and cert is expiring within 30 days. For automatic renewal, add a cron job:

```bash
# Restart weekly to check certificate renewal
0 3 * * 0 cd /path/to/private-dns && docker compose restart
```

## Troubleshooting

### Certificate Issues

```bash
# View logs
docker compose logs -f

# Force certificate renewal (delete old certs)
docker compose down
docker volume rm private-dns_adguard_certs private-dns_adguard_lego
docker compose up -d --build
```

### Test DNS-over-TLS

```bash
# Using kdig (from knot-dnsutils)
kdig -d @yoursubdomain.duckdns.org +tls-ca +tls-host=yoursubdomain.duckdns.org whatsapp.net

# Should return your VPS IP
```

### Check if DoT Port is Open

```bash
nc -zv your-vps-ip 853
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Your VPS                              │
│                                                              │
│  ┌──────────────────────┐    ┌────────────────────────────┐ │
│  │   Private DNS        │    │     WhatsApp Proxy         │ │
│  │   (AdGuard Home)     │    │       (HAProxy)            │ │
│  │                      │    │                            │ │
│  │  :853 DNS-over-TLS ──┼────┼──→ :443 HTTPS/Media       │ │
│  │  :53  Plain DNS      │    │   :80  HTTP                │ │
│  │  :3000 Web UI        │    │   :5222 XMPP               │ │
│  │                      │    │                            │ │
│  │  DNS Rewrites:       │    │  SNI Routing:              │ │
│  │  *.whatsapp.net →────┼────┼──→ *.whatsapp.net         │ │
│  │    YOUR_VPS_IP       │    │  *.fbcdn.net               │ │
│  └──────────────────────┘    └────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                    ↑
            DNS-over-TLS (encrypted)
                    │
            ┌───────┴───────┐
            │  Android Phone │
            │  Private DNS:  │
            │  subdomain.    │
            │  duckdns.org   │
            └───────────────┘
```

## Comparison: DNS Proxy vs Private DNS

| Feature | whatsapp-dns (dnsmasq) | private-dns (AdGuard) |
|---------|------------------------|------------------------|
| Encryption | No (plain DNS) | Yes (DoT/DoH) |
| Android Private DNS | No | Yes |
| Setup complexity | Simple | Medium |
| Use case | Home network, router | Mobile users |
| Bypass ISP | Maybe blocked | Hard to block |
