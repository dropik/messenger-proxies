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

Alerts go to a Telegram bot: critical ones with sound, warnings silently, each with a
"resolved" follow-up. Events (rules labelled `type: event`: a container restart, a reboot)
are sent once, silently, with no follow-up. The message format is `alertmanager/telegram.tmpl`.

### Users' channel

A private Telegram channel for the people using the VPN, with the same bot as an admin that
may only post. It gets two kinds of messages, both silent and in Russian:
- **Outages, automatically:** `VpnOutage` (`audience: users`) fires when a real client can't get
  through (either group's probe fails) or the relay is unreachable, after 7 minutes, and stays
  on 5 minutes after recovery so flapping doesn't post repeatedly. One post when it starts,
  one when it's over (template `telegram.users`). The owner gets the detailed alerts instead.
- **Announcements, by hand:** `./announce.sh "текст"` (maintenance, "refresh the subscription").

Setup: create a private channel with a bland name, add the bot as an admin with only "Post
messages", post anything in it, then read the channel id from the bot's `getUpdates` and save
it as `alertmanager/secrets/users_channel_id` (root:65534, 0640); it replaces `chat_id: -1`.
Members can't write in a channel; keep comments (a linked discussion group) off.

### DNS

The exit's DNS alert counts only failed lookups (timeouts, server errors). "No such domain"
answers, mostly apps retrying domains that don't exist, are counted separately
(`xray_dns_nxdomain`) and shown on the dashboard only.

1. Create a bot with @BotFather (`/newbot`) and send it any message.
2. Put the token on the exit without it landing in shell history:
   ```bash
   cd monitoring/exit/alertmanager && umask 077 && mkdir -p secrets
   read -rsp "Bot token: " t; echo; printf %s "$t" | sudo tee secrets/telegram_token >/dev/null; unset t
   sudo chown debian:65534 secrets && sudo chmod 750 secrets
   sudo chown root:65534 secrets/telegram_token && sudo chmod 640 secrets/telegram_token
   ```
3. Find the chat id: `getUpdates` on the bot lists the chat you wrote from. Copy
   `alertmanager.yml.example` to `alertmanager.yml`, set both `chat_id`s, and run
   `docker compose restart alertmanager`.
4. Test: `docker exec mon-alertmanager amtool --alertmanager.url=http://127.0.0.1:9093 alert add alertname=Test severity=critical`.

The Watchdog alert goes nowhere until a healthchecks.io check exists (see the comment in
the example). Without it, nothing notices if the exit itself goes down, because
Alertmanager runs there too.

## Dashboard

"VPN overview" (folder VPN) is provisioned read-only from
`grafana/provisioning/dashboards/json/vpn.json`. That file is generated: edit
`grafana/build_dashboard.py`, run it, copy the JSON to the exit, and Grafana picks it up
within a few seconds. The datasource is recreated on every start so its uid stays `vm`.

## Access

**Tailscale (normal way).** The exit is in your tailnet as `monitor`, and Tailscale serves
Grafana there over plain HTTP. That's fine because the tailnet itself is encrypted
end to end. Nothing listens publicly. From any device logged in to your Tailscale account,
open `http://monitor`; the user is `admin` and the password is in `grafana.env`.

```bash
# on the exit, once (Tailscale from pkgs.tailscale.com)
sudo tailscale up --hostname=monitor --accept-dns=false     # approve the link it prints
sudo tailscale serve --bg --http=80 http://127.0.0.1:3000  # persists across reboots
```

In the Tailscale admin console, **disable key expiry** for `monitor`. Otherwise it drops
out of the tailnet after 180 days.

Tailscale adds its own `ts-input` iptables chain ahead of ufw: it accepts traffic arriving
on `tailscale0` and UDP 41641 (direct connections). So tailnet devices can reach the exit,
while the public firewall is unchanged.

**SSH tunnel (fallback, also for raw queries):**

```bash
ssh -L 3000:127.0.0.1:3000 -L 8428:127.0.0.1:8428 debian@EXIT_IP
```

Then open `http://localhost:3000` (Grafana) or `http://localhost:8428/vmui` (raw queries).
