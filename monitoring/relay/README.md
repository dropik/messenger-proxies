# Monitoring agents (on the relay)

Nothing is stored or reachable here. The relay has no host firewall, so everything listens on
`127.0.0.1`. Metrics are pushed through the tunnel to the [exit's stack](../exit/README.md).

| Piece | What it does |
|---|---|
| vmagent | scrapes node_exporter, pushes to `http://victoriametrics/api/v1/write` via the relay's `monitor-in` inbound (`127.0.0.1:10809`); buffers up to 500 MB on disk during outages |
| node_exporter | host metrics plus the textfile metrics below (`127.0.0.1:9100`) |
| collector (`../collector/collect.py`, timer every 30 s) | Xray traffic and path health (observatory), container state, log counts, totals of client connections on 443 |
| probe (`mon-probe` container + `probe/probe.py`, every minute) | a real Xray client connects to the relay's public address and fetches pages as the forward and direct groups; a 10 MB speed test every 15 min |

## Disconnect classifier (`classifier/`)

`monitoring-classifier.service` runs `classifier.py`, which reads kernel TCP events from
`conn-events.bt` (bpftrace, port 443 only). When a client address has had no connection for
10 s, it counts one **disconnect episode**, labelled from how the last connections ended:
- `reset_active`: killed during traffic
- `client_closed`: VPN off or app stopped
- `vanished`: network gone
- `stalled`: path broke during traffic
- `relay_closed`, `injected?` and `other`

**Privacy:** addresses are kept only in memory, HMAC-keyed with a random key per run.
Only totals are written (`classifier.prom`). The probe's own address is excluded via
`/etc/monitoring/classifier.env`.

**Accuracy:** `lab.sh` runs a controlled client through known disconnects. The results are
in `../PHASE1.md`. The labels are for dashboards only until real phones are checked.

## Relay Xray changes (`xray-monitoring.py`, idempotent)

- **Stats and metrics endpoint:** `0.0.0.0:11111` in the container, published on `127.0.0.1`.
- **`monitor-in`:** an HTTP proxy inbound on `10809`, published on `127.0.0.1`. It goes out via `mon-cdn` (Cloudflare), with `mon-cfws` (CloudFront WebSocket) as fallback, as the exit's `monitor@cdn` user. The exit sends that user's requests for the host `victoriametrics` to VictoriaMetrics.
- **Probe users:** `probe@relay` (routed like forward) and `probe-direct@relay` (routed like direct). They aren't in the subscriptions.
- **TCP keepalive on client connections:** 60 s idle, 20 s interval, 120 s user timeout. A vanished client is closed in about 2 minutes instead of never.
- **Private destinations blocked for client traffic:** a second layer on top of freedom's default policy.

Secrets live in `/etc/monitoring/` (mode 600) and never in the repo:
- `monitor-uuid`: copied from the exit
- `probe-uuids.json`: created by the script
- `probe-client.json`: created by `make-probe-client.py`

## Install

```bash
# monitor-uuid copied from the exit to /etc/monitoring/monitor-uuid first
cd /root/messenger-proxies/vless-relay
python3 ../monitoring/relay/xray-monitoring.py config.json        # writes config.json.new
docker run --rm -v $PWD/config.json.new:/c.json:ro teddysun/xray:26.10.31 xray run -test -c /c.json
mv config.json.new config.json && docker compose up -d             # compose publishes 10809/11111 on localhost
python3 ../monitoring/relay/make-probe-client.py config.json subscription/subs.json

install -d /usr/local/lib/monitoring /var/lib/node_exporter/textfile /var/lib/monitoring
install -m 755 ../monitoring/collector/collect.py ../monitoring/relay/probe/probe.py /usr/local/lib/monitoring/
cp ../monitoring/relay/collect.env.example /etc/monitoring/collect.env
install -m 644 ../monitoring/exit/systemd/monitoring-collect.* ../monitoring/relay/systemd/monitoring-probe.* /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now monitoring-collect.timer monitoring-probe.timer
cd ../monitoring/relay && docker compose up -d
```

Alert rules for the relay are in `../exit/vmalert/relay.yml`.
