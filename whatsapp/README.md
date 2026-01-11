# WhatsApp Proxy Server

A Docker-based WhatsApp proxy server using HAProxy to enable WhatsApp connectivity in restricted networks.

## Quick Start

### Build and Run

```bash
# Using Docker Compose (recommended)
docker-compose up -d

# Or build and run manually
docker build -t whatsapp-proxy .
docker run -d --name whatsapp-proxy \
  -p 80:80 \
  -p 443:443 \
  -p 5222:5222 \
  -p 8080:8080 \
  -p 8443:8443 \
  -p 8404:8404 \
  --restart unless-stopped \
  whatsapp-proxy
```

### Check Status

```bash
# View logs
docker logs whatsapp-proxy

# Check HAProxy stats (if enabled)
curl http://your-server-ip:8404/stats
```

## Configuration in WhatsApp App

1. Open WhatsApp on your phone
2. Go to **Settings** → **Storage and Data** → **Proxy**
3. Enable **Use Proxy**
4. Enter your VPS IP address or domain: `your-server-ip` or `your-domain.com`
5. Tap **Save**

## Ports

This setup uses non-standard ports to allow multiple proxy services (WhatsApp, Telegram, etc.) on the same VPS.

**Note:** With `network_mode: host`, the container binds directly to host ports (no port mapping).

### TCP Ports (Messaging & Data)

| Port | Description |
|------|-------------|
| 80 | HTTP traffic |
| 443 | HTTPS/TLS traffic |
| 587 | Media transfers (photos, videos, docs) |
| 5222 | XMPP (WhatsApp messaging) |
| 8080 | Alternative HTTP |
| 8443 | Alternative HTTPS |
| 5404 | HAProxy statistics dashboard |

## Firewall Configuration

Make sure to open the required ports on your VPS:

```bash
# UFW (Ubuntu/Debian)
# TCP ports
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 587/tcp
ufw allow 5222/tcp
ufw allow 8080/tcp
ufw allow 8443/tcp
ufw allow 5404/tcp

# firewalld (CentOS/RHEL)
# TCP ports
firewall-cmd --permanent --add-port=80/tcp
firewall-cmd --permanent --add-port=443/tcp
firewall-cmd --permanent --add-port=587/tcp
firewall-cmd --permanent --add-port=5222/tcp
firewall-cmd --permanent --add-port=8080/tcp
firewall-cmd --permanent --add-port=8443/tcp
firewall-cmd --permanent --add-port=5404/tcp
firewall-cmd --reload
```

## Troubleshooting

### Connection Issues
- Ensure all required ports are open on your VPS firewall
- Check if HAProxy is running: `docker ps`
- Review logs: `docker logs whatsapp-proxy`

### Certificate Issues
The container generates a self-signed certificate on build. For production use, consider using a proper SSL certificate.

## Security Notes

- The statistics page (port 8404) is exposed for monitoring. Consider restricting access in production.
- Change default configurations as needed for your security requirements.
- Keep the Docker image updated regularly.

## License

This proxy implementation is for personal use to access WhatsApp in restricted networks.
