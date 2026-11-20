# Monitoring stack (on the exit)

VictoriaMetrics (storage, 30 days), vmalert + Alertmanager (alerts to a Telegram bot),
Grafana (dashboards), node_exporter plus a small collector for Xray, containers,
certificates and log counts. See [../PHASE1.md](../PHASE1.md) for the design.

Nothing is reachable from the internet:
- Grafana and VictoriaMetrics listen on `127.0.0.1` only.
- node_exporter listens on the monitoring bridge's gateway, `10.213.0.1`.
- The relay's metrics arrive through the tunnel. The exit's Xray redirects a dedicated monitoring user, and only that user, to VictoriaMetrics.

## Install

```bash
cd monitoring/exit
umask 077
printf 'GF_SECURITY_ADMIN_PASSWORD=%s\n' "$(openssl rand -base64 18)" > grafana.env
cp alertmanager/alertmanager.yml.example alertmanager/alertmanager.yml   # start with the "null" version
docker compose up -d

# node_exporter is reached from the bridge, which ufw filters on INPUT
sudo ufw allow in on br-mon to 10.213.0.1 port 9100 proto tcp comment 'node_exporter for monitoring'

# collector
sudo install -d -m 755 /usr/local/lib/monitoring /var/lib/node_exporter/textfile /var/lib/monitoring /etc/monitoring
sudo install -m 755 ../collector/collect.py /usr/local/lib/monitoring/collect.py
sudo install -m 644 collect.env.example /etc/monitoring/collect.env    # adjust paths
sudo install -m 644 systemd/monitoring-collect.service systemd/monitoring-collect.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now monitoring-collect.timer
```

## Exit Xray

The exit's Xray needs these changes (see `vless-exit/config.json.example`):
- `stats`, `policy` and `metrics` (listening on `10.213.0.20:11111`)
- a monitoring user
- a `to-vm` outbound that redirects to VictoriaMetrics. **Don't name it `metrics`:** that is
  the metrics service's own tag, and traffic sent to it lands in Xray's expvar handler instead.
- a `finalRules` allow for exactly `10.213.0.10:8428`. Freedom in Xray 26.x blocks private
  and reserved addresses by default for traffic from VLESS inbounds.
- routing: the monitoring user's requests for the host `victoriametrics` go to `to-vm`. Its
  other traffic (the relay's health checks) goes out normally. Private addresses are blocked
  for everyone else.

It also has to join the `monitoring` network at `10.213.0.20` (see `vless-exit/docker-compose.yml`).

## Alerts

Create a bot with @BotFather, send it a message, and find your chat id. Then fill
`alertmanager/secrets/telegram_token`, `chat_id` and the healthchecks.io ping URL, switch
`alertmanager.yml` to the full version, and run `docker compose restart alertmanager`.

## Dashboard

"VPN overview" (folder VPN) is provisioned read-only from
`grafana/provisioning/dashboards/json/vpn.json`. That file is generated: edit
`grafana/build_dashboard.py`, run it, copy the JSON to the exit, and Grafana picks it up
within a few seconds. The datasource is recreated on every start so its uid stays `vm`.

## Access

```bash
ssh -L 3000:127.0.0.1:3000 -L 8428:127.0.0.1:8428 debian@EXIT_IP
```

Then open `http://localhost:3000` (Grafana; the user is `admin`, the password is in
`grafana.env`) or `http://localhost:8428/vmui` (raw queries).
