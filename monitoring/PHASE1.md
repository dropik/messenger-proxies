# Monitoring, phase 1: plan

Goal: know within minutes **whether users can connect**, and when someone reports a
problem, tell **whether it was the phone, the network, the censor or us**.

Privacy rules (same as the access-log decision):
- No client addresses, user names or destinations stored anywhere.
- Client addresses exist only in memory, for seconds, in the disconnect classifier.
- Only totals by type and time leave the relay.
- Monitoring data lives on the exit (Italy), never on the relay (Russia).

## Components

### A. Monitoring host (on the exit)

| Piece | Role | Memory |
|---|---|---|
| VictoriaMetrics (single node) | metrics storage, 30-day retention | ~80 MB |
| vmalert + Alertmanager | alert rules, sends to a Telegram bot (to the admin only) | ~40 MB |
| Grafana | dashboards, listens on `127.0.0.1` only, reached via an SSH tunnel | ~120 MB |
| node_exporter + textfile scripts | exit host, Xray restarts, DNS failure count, certificate expiry | ~20 MB |

- **Watchdog:** the exit pings an outside heartbeat (healthchecks.io) every 5 minutes, so a dead monitoring host is noticed.
- **Space:** the exit has 1.5 GB of RAM and 35 GB of disk free.

### B. Getting data out of the relay

The relay can't reach the exit's IP (it's blocked from Russia), and the exit must not connect to the relay. So the relay **pushes its data through the tunnel**:

- **vmagent on the relay** collects local metrics and sends them over the existing CDN path, through a localhost-only Xray inbound on the relay. It buffers on disk during outages and resends later.
- **On the exit:**
  - The relay uses a **separate monitoring UUID**. Only that user may reach the metrics store, which sits at a fixed address on the exit's Docker network.
  - **Private addresses (`geoip:private`) are blocked for all other traffic.** Xray 26.x's freedom outbound already blocks private and reserved addresses by default for traffic from VLESS inbounds, so this rule is a second layer. It also stops such requests at routing, before any DNS lookup.
- **Dead man's switch:** no data from the relay for 5 minutes → alert.

### C. Probes (on the relay, against itself)

A probe container runs a real Xray client against the relay's public address, using a dedicated probe user:
- **Every minute:** a test page (generate_204), YouTube, Telegram, an Instagram page.
- **Every 15 minutes:** a 10 MB download, to measure speed.
- **The same with the direct group.**

This catches broken config, Xray, REALITY or CDN paths. It **doesn't** catch blocks on Russian networks; that needs a second vantage point in Russia (phase 4).

### D. Relay health

- **Xray's built-in metrics endpoint (stats and observatory):** health and response time per path, traffic per path and per group.
- **node_exporter:** CPU, memory, disk, the connection table.
- **Container restarts and host reboots.**

### E. Client connection telemetry

1. **TCP keepalive on the client inbound:**
   - `sockopt`: `tcpKeepAliveIdle: 60`, `tcpKeepAliveInterval: 20`, `tcpUserTimeout: 120000`.
   - Plus the container setting `net.ipv4.tcp_keepalive_probes=3` in `docker-compose.yml`.
   - Result: a vanished client is detected in about 2 minutes. Today it's never detected: 806 of 916 connections had been silent for over 30 minutes, 58 of them for over 2 days.
   - **Verified on the relay** with a throwaway Xray 26.10.31 container: with these options, accepted sockets get a 60 s keepalive timer; without them (like the live config) they get none. `tcpUserTimeout` isn't shown by `ss`, so stage 1 below checks it by its effect.
2. **Gauges every minute, from `ss` in the container (totals only):** open connections, silent over 30 minutes, data stuck unacknowledged.
3. **Disconnect classifier:**
   - A bpftrace script (Debian 13 has 0.23.2; the kernel has BTF) watches only port 443 and records how each connection ends:

     | Kernel signal | Raw class |
     |---|---|
     | `inet_sock_set_state` ESTABLISHED → CLOSE_WAIT | client closed first (FIN) |
     | `inet_sock_set_state` ESTABLISHED → FIN_WAIT1 | relay closed first |
     | `tcp_receive_reset` | client side sent a reset |
     | `inet_sk_error_report` with ETIMEDOUT | vanished (keepalive) or stalled (resend timeout); told apart by whether data was unacknowledged |
     | RST TTL ≠ the client's SYN TTL (kprobe) | possibly injected by filtering equipment (**experimental**) |

   - A small program groups one client's connection ends within 2 seconds into one **disconnect episode** and labels it:
     - clean close
     - reset during traffic (likely the app was killed)
     - vanished (and whether it came back from a new address within 60 s)
     - stalled
     - injected?
     - unknown
   - Addresses are only HMAC keys in memory, with a random key per run, and are never written anywhere. Output: counters per class plus "episode" events on the Grafana timeline.

### Alerts (short list)

- **Critical:**
  - a probe fails 3 times in a row
  - every path behind the relay is down
  - no relay data for 5 minutes
  - the heartbeat is missed
- **Warning:**
  - Cloudflare path unhealthy for over 5 minutes (users are on the Gcore fallback)
  - 10 MB speed under the threshold for 30 minutes
  - a container restart or host reboot
  - a certificate expiring in under 14 days
  - disk or memory over 85%
  - a burst of "reset during traffic" or "injected?" episodes across several clients within 5 minutes (a filtering or server event, not one phone)

## Checking the classifier's accuracy

The classifier's labels are a hypothesis until measured. **Until stages 1 and 2 pass, they appear on the dashboard only, with no alerts.**

### Stage 1: lab, a controlled test client (before using it)

**Setup:**
- A test Xray client in its own network namespace (a container) with a dedicated test UUID. It connects to the relay's public address.
- `iptables` and `tc` in that namespace simulate network loss.
- `scapy` forges resets.

**Scenarios,** 20 runs each, with the cause known to the second:

| # | What we do | Expected label |
|---|---|---|
| S1 | stop the client normally while idle | clean close |
| S2 | stop it normally during a download | clean close |
| S3 | kill it (SIGKILL) while idle | clean close or reset (record which) |
| S4 | kill it during a download | reset during traffic |
| S5 | drop all its packets while idle | vanished, about 2 min later |
| S6 | drop all its packets during a download | stalled |
| S7 | drop, then reconnect from a second address | vanished, back from a new address |
| S8 | forged reset with a different TTL | injected? |
| S9 | forged reset with the same TTL | (measures what can't be told apart) |

**Measured:**
- correct label per class (precision and recall)
- delay until detection
- grouping errors: one disconnect split into several, or two clients merged into one

**Results (2026-11-19, Linux Xray client, `monitoring/relay/classifier/lab.sh`):**

| Scenario | Label | Correct |
|---|---|---|
| killed during a download (S4) | reset_active | 3/3 |
| stopped during a download (S2) | client_closed | 3/3 (never reset_active) |
| stopped or killed while idle (S1, S3) | client_closed | 6/6 (the two can't be told apart) |
| network cut while idle (S5) | vanished, ~122 s after the cut | 7/7 |
| network cut during a download (S6) | stalled | 1/1 |

What the lab corrected:
- **A client closing almost always ends in a reset after its FIN**, because the relay is still writing. So "reset after FIN" doesn't mean the client was interrupted mid-transfer. Only a reset while the connection is still fully open does.
- **The unacknowledged-data count is useless at that point:** the kernel purges the send queue before the state change. Retransmit and keepalive-probe counters are used instead.
- **The speed-test server refuses single downloads over 25 MB,** so the first round's "downloading" scenarios weren't downloading at all.

Not tested yet: forged resets (S7/S8), carrier-grade NAT, and how a real iPhone ends its connections (stage 2).

### Stage 2: real phones, ground truth from people

- **On a willing iPhone with v2RayTun, and one Android phone,** each action 5 times with the time noted to the second:
  - disconnect button (idle, and during video)
  - quitting the app
  - airplane mode
  - leaving Wi-Fi range
  - Wi-Fi ↔ mobile data switch
  - reboot
- **Memory kills can't be triggered on demand.** We use `JetsamEvent` reports (`packet-extension`, `per-process-limit`) as ground truth: is there a matching episode within ±10 s, and what label did it get?
- **This answers the main unknown:** what an iPhone actually sends when iOS kills the VPN extension (reset, close, or nothing).

### Stage 3: ongoing checks

- **Share of "unknown"** episodes.
- **How much normal clients' TTL varies over a connection's life.** This is the false-alarm rate for "injected?".
- **Carrier-grade NAT collisions:** several users behind one carrier address make their episodes merge. Flag addresses with unusually many concurrent connections.

### Thresholds to accept

| Label | Accepted when |
|---|---|
| clean / reset / vanished / stalled | at least 90% correct on S1–S7 |
| "app killed" | at least 4 of 5 known iPhone memory kills match |
| "injected?" | stays experimental unless the TTL false-alarm rate is under 1% |

### Known limits

- **The relay can't see inside TLS** (whether the client sent a TLS close message), so "pressed disconnect" and "process exited" may look the same.
- **"Vanished" also covers mobile operators dropping idle connections,** not just phones going offline.
- **Keepalives delay "vanished" detection by about 2 minutes.**

## Live changes this needs (each one approved before it's done)

1. **Exit:**
   - the monitoring containers
   - Xray: the monitoring user, and blocking private addresses for everything else
   - one Xray restart
2. **Relay:**
   - Xray: metrics, stats and API on localhost, a localhost monitoring inbound, keepalive options, a probe user
   - Xray: block private addresses (`geoip:private`, `geosite:private`) for user traffic. This is a second layer on top of freedom's default policy.
   - compose: the keepalive setting
   - install bpftrace, node_exporter and vmagent
   - one restart, at night
3. **From you:** a Telegram bot (from BotFather) and a healthchecks.io check. The bot token is stored only on the exit.
