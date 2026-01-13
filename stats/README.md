# VPS Statistics Dashboard

Real-time system monitoring using Netdata.

## Quick Start

```bash
cd stats
docker compose up -d
```

Access the dashboard at: `http://your-vps-ip:19999`

## What's Monitored

- **CPU**: Usage per core, load, frequency
- **Memory**: RAM, swap, caches
- **Disk**: I/O, space usage
- **Network**: Bandwidth, packets, errors
- **Docker**: All container metrics (including WhatsApp proxy)
- **Processes**: Running, blocked, forks

## Data Retention

Default setup keeps ~1-2 hours of data in memory. Data persists across container restarts via Docker volumes.

## Optional: Connect to Netdata Cloud

For 14 days of free historical data:

1. Sign up at https://app.netdata.cloud
2. Get your claim token from the dashboard
3. Add it to `NETDATA_CLAIM_TOKEN` in docker-compose.yml
4. Restart the container

## Security Note

The dashboard is publicly accessible on port 19999. For production:

1. Use a firewall to restrict access
2. Or put behind a reverse proxy with authentication
