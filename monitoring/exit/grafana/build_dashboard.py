#!/usr/bin/env python3
"""Generate the provisioned Grafana dashboard (provisioning/dashboards/json/vpn.json).

Edit here, run `python build_dashboard.py`, commit both. Colors follow fixed roles:
- Categorical series take slots in a fixed order: dark-mode steps, validated on Grafana's
  dark panel surface with all adjacent pairs passing.
- Status colors are only used for state (OK/UP vs FAILING/DOWN), always with a text label.
"""
import json
import os

DS = {"type": "prometheus", "uid": "vm"}
SLOT = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9"]
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"

panels = []
_id = [0]
_y = [0]


def nid():
    _id[0] += 1
    return _id[0]


def target(expr, legend="", instant=False, fmt="time_series", ref="A", interval=""):
    t = {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref,
         "instant": instant, "range": not instant, "format": fmt}
    if interval:
        t["interval"] = interval
    return t


def row(title):
    panels.append({"type": "row", "title": title, "id": nid(), "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": _y[0]}, "panels": []})
    _y[0] += 1


def fixed_colors(names):
    """Override: series name -> categorical slot, in the given order."""
    return [{"matcher": {"id": "byName", "options": n},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": SLOT[i]}}]}
            for i, n in enumerate(names)]


def updown_mappings(up="UP", down="DOWN"):
    return [{"type": "value", "options": {
        "1": {"text": up, "color": GOOD, "index": 0},
        "0": {"text": down, "color": CRIT, "index": 1}}},
        {"type": "special", "options": {"match": "null", "result": {"text": "NO DATA", "color": WARN}}}]


def stat(title, expr, x, w, h=4, mappings=None, unit="none", thresholds=None, color_mode="background",
         desc="", decimals=None):
    p = {"type": "stat", "title": title, "id": nid(), "description": desc, "datasource": DS,
         "gridPos": {"h": h, "w": w, "x": x, "y": _y[0]},
         "targets": [target(expr, instant=True)],
         "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                     "colorMode": color_mode, "graphMode": "none", "textMode": "value",
                     "justifyMode": "center", "orientation": "auto", "wideLayout": True},
         "fieldConfig": {"defaults": {"unit": unit, "mappings": mappings or [],
                                      "color": {"mode": "thresholds"},
                                      "thresholds": thresholds or {"mode": "absolute", "steps": [
                                          {"color": "text", "value": None}]}},
                         "overrides": []}}
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    panels.append(p)


def timeseries(title, targets, x, w, h=8, unit="none", names=None, bars=False, stack=False, desc="",
               min0=True, interval=""):
    custom = {"drawStyle": "bars" if bars else "line", "lineWidth": 2, "fillOpacity": 80 if bars else 0,
              "pointSize": 8, "showPoints": "never", "spanNulls": False,
              "axisSoftMin": 0 if min0 else None, "gradientMode": "none",
              "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
    p = {"type": "timeseries", "title": title, "id": nid(), "description": desc, "datasource": DS,
         "gridPos": {"h": h, "w": w, "x": x, "y": _y[0]}, "targets": targets,
         "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                     "tooltip": {"mode": "multi", "sort": "desc"}},
         "fieldConfig": {"defaults": {"unit": unit, "custom": custom,
                                      "color": {"mode": "fixed", "fixedColor": SLOT[0]}},
                         "overrides": fixed_colors(names or [])}}
    if interval:
        p["interval"] = interval
    panels.append(p)


def state_timeline(title, expr, legend, x, w, h=8, up="UP", down="DOWN", desc=""):
    panels.append({"type": "state-timeline", "title": title, "id": nid(), "description": desc,
                   "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": _y[0]},
                   "targets": [target(expr, legend)],
                   "options": {"showValue": "never", "mergeValues": True, "rowHeight": 0.8,
                               "alignValue": "left", "legend": {"showLegend": False},
                               "tooltip": {"mode": "single"}},
                   "fieldConfig": {"defaults": {"mappings": updown_mappings(up, down),
                                                "color": {"mode": "thresholds"},
                                                "thresholds": {"mode": "absolute", "steps": [
                                                    {"color": CRIT, "value": None}, {"color": GOOD, "value": 1}]},
                                                "custom": {"fillOpacity": 85, "lineWidth": 0}},
                                   "overrides": []}})


def nextrow(h):
    _y[0] += h


# ---------------------------------------------------------------- is it working?
row("Is it working?")
stat("Forward", 'min(probe_success{host="relay",group="forward",target="generate_204"})', 0, 3,
     mappings=updown_mappings("OK", "FAILING"),
     desc="Probe: a real Xray client on the relay fetches a test page as the forward group, every minute.")
stat("Direct", 'min(probe_success{host="relay",group="direct",target="generate_204"})', 3, 3,
     mappings=updown_mappings("OK", "FAILING"), desc="Probe as the direct group (exits in Russia).")
stat("Cloudflare", 'xray_observatory_alive{host="relay",tag="exit-cdn"}', 6, 3,
     mappings=updown_mappings(), desc="Relay health check through Cloudflare, the main path.")
stat("Fallback", 'xray_observatory_alive{host="relay",tag="exit-cfws"}', 9, 3,
     mappings=updown_mappings(), desc="CloudFront WebSocket fallback; takes over if Cloudflare fails.")
stat("Split", 'min(xray_observatory_alive{host="relay",tag=~"yt-split-.*"})', 12, 3,
     mappings=updown_mappings(), desc="CloudFront split: YouTube download legs via CloudFront (uploads via Cloudflare).")
stat("Data age", 'time() - max(timestamp(up{host="relay",job="node"}))', 15, 3, unit="s",
     decimals=0, desc="Seconds since the relay's metrics last arrived at the exit through the tunnel.",
     thresholds={"mode": "absolute", "steps": [{"color": GOOD, "value": None},
                                               {"color": WARN, "value": 120}, {"color": CRIT, "value": 300}]})
stat("Speed", 'probe_download_bytes_per_second{host="relay",group="forward"}', 18, 3,
     unit="Bps", decimals=1, desc="Probe download speed: 10 MB through forward, every 15 minutes.",
     thresholds={"mode": "absolute", "steps": [{"color": CRIT, "value": None},
                                               {"color": WARN, "value": 1e6}, {"color": GOOD, "value": 3e6}]})
stat("Alerts", 'count(ALERTS{alertstate="firing",alertname!="Watchdog"}) or vector(0)', 21, 3,
     desc="Alerts firing now (vmalert). Details in the table at the bottom.",
     thresholds={"mode": "absolute", "steps": [{"color": GOOD, "value": None}, {"color": CRIT, "value": 1}]})
nextrow(4)

# ---------------------------------------------------------------- paths
row("Paths (health checks from the relay, every minute)")
state_timeline("Path health", 'xray_observatory_alive{host="relay",tag=~"exit-.*|yt-split-.*|mon-.*"}',
               "{{tag}}", 0, 12, desc="exit-cdn = Cloudflare, exit-cfws = CloudFront WebSocket fallback, "
               "yt-split-* = CloudFront download legs, mon-* = the monitoring push paths.")
timeseries("Health check response time", [
    target('xray_observatory_delay_ms{host="relay",tag="exit-cdn"}', "Cloudflare", ref="A"),
    target('xray_observatory_delay_ms{host="relay",tag="exit-cfws"}', "CloudFront fallback", ref="B"),
    target('xray_observatory_delay_ms{host="relay",tag="yt-split-1"}', "CloudFront split", ref="C")],
    12, 12, unit="ms", names=["Cloudflare", "CloudFront fallback", "CloudFront split"])
nextrow(8)

# ---------------------------------------------------------------- probe
row("Probe (a real client through the relay)")
state_timeline("Probe results", 'probe_success{host="relay"}', "{{group}} → {{target}}", 0, 8,
               up="OK", down="FAIL")
timeseries("Page fetch time (forward)", [
    target('probe_duration_seconds{host="relay",group="forward"}', "{{target}}")],
    8, 8, unit="s", names=["generate_204", "youtube", "telegram", "instagram"])
timeseries("Download speed (forward, every 15 min)", [
    target('probe_download_bytes_per_second{host="relay",group="forward"}', "forward")],
    16, 8, unit="Bps", names=["forward"])
nextrow(8)

# ---------------------------------------------------------------- traffic
row("Traffic through the relay")
PATHS = [("Cloudflare", 'exit-cdn|yt-cf-.*'), ("CloudFront split", 'yt-split-.*'),
         ("CloudFront fallback", 'exit-cfws'), ("Direct (from Russia)", 'direct')]
for i, (direction, title) in enumerate((("downlink", "Download to users, by path"),
                                        ("uplink", "Upload from users, by path"))):
    timeseries(title, [
        target(f'sum(rate(xray_traffic_bytes_total{{host="relay",kind="outbound",direction="{direction}",'
               f'tag=~"{rx}"}}[5m]))', name, ref=chr(65 + j)) for j, (name, rx) in enumerate(PATHS)],
        12 * i, 12, unit="Bps", names=[n for n, _ in PATHS],
        desc="Bytes per second per outbound group on the relay (5-minute average).")
nextrow(8)

# ---------------------------------------------------------------- clients
row("Clients and disconnects")
CLASSES = ["client_closed", "vanished", "reset_active", "stalled", "relay_closed", "other", "injected?"]
timeseries("Disconnects per hour, by how they ended", [
    target('sum by (class) (increase(disconnect_episodes_total{host="relay"}[1h]))', "{{class}}",
           interval="1h")], 0, 12, bars=True, stack=True, names=CLASSES, interval="1h",
    desc="A disconnect = a client address with no connection for 10 s. client_closed: VPN off / app "
         "stopped. vanished: network gone (~2 min to detect). reset_active: app killed during traffic. "
         "stalled: path broke during traffic. Lab-checked on a Linux client only; see PHASE1.md.")
timeseries("Client connections on 443", [
    target('tcp_conns_established{host="relay"}', "open", ref="A"),
    target('tcp_conns_silent_30m{host="relay"}', "silent 30+ min", ref="B"),
    target('tcp_conns_backoff{host="relay"}', "peer not answering", ref="C")],
    12, 8, names=["open", "silent 30+ min", "peer not answering"])
stat("Clients connected", 'classifier_clients_connected{host="relay"}', 20, 4, h=8, color_mode="none",
     desc="Distinct client addresses with an open connection right now (probe excluded).")
nextrow(8)

# ---------------------------------------------------------------- hosts
row("Servers")
HOSTS = ["relay", "exit"]
timeseries("CPU busy", [target('100 * (1 - avg by (host) (rate(node_cpu_seconds_total{mode="idle"}[5m])))',
                               "{{host}}")], 0, 6, unit="percent", names=HOSTS)
timeseries("Memory available", [target('100 * node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes',
                                        "{{host}}")], 6, 6, unit="percent", names=HOSTS)
timeseries("Xray memory (Go heap)", [target('xray_go_heap_bytes', "{{host}}")], 12, 6, unit="bytes",
           names=HOSTS)
timeseries("Errors per hour", [
    target('increase(log_matches_total{host="relay",name="xray_health_fail"}[1h])', "relay: failed health checks",
           ref="A"),
    target('increase(log_matches_total{host="exit",name="xray_dns_error"}[1h])', "exit: DNS errors", ref="B")],
    18, 6, names=["relay: failed health checks", "exit: DNS errors"])
nextrow(8)
stat("Disk used: relay", '100 * (1 - node_filesystem_avail_bytes{host="relay",mountpoint="/"} / '
     'node_filesystem_size_bytes{host="relay",mountpoint="/"})', 0, 4, unit="percent", decimals=0,
     thresholds={"mode": "absolute", "steps": [{"color": GOOD, "value": None}, {"color": WARN, "value": 75},
                                               {"color": CRIT, "value": 85}]})
stat("Disk used: exit", '100 * (1 - node_filesystem_avail_bytes{host="exit",mountpoint="/"} / '
     'node_filesystem_size_bytes{host="exit",mountpoint="/"})', 4, 4, unit="percent", decimals=0,
     thresholds={"mode": "absolute", "steps": [{"color": GOOD, "value": None}, {"color": WARN, "value": 75},
                                               {"color": CRIT, "value": 85}]})
stat("Let's Encrypt cert", '(cert_not_after_seconds{name="letsencrypt"} - time()) / 86400', 8, 4, unit="suffix: days",
     decimals=0, desc="Days until the origin certificate CloudFront checks expires (renewed daily).",
     thresholds={"mode": "absolute", "steps": [{"color": CRIT, "value": None}, {"color": WARN, "value": 14},
                                               {"color": GOOD, "value": 30}]})
stat("Cloudflare origin cert", '(cert_not_after_seconds{name="cloudflare_origin"} - time()) / 86400', 12, 4,
     unit="suffix: days", decimals=0,
     thresholds={"mode": "absolute", "steps": [{"color": CRIT, "value": None}, {"color": WARN, "value": 14},
                                               {"color": GOOD, "value": 30}]})
stat("CDN ranges age", '(time() - file_mtime_seconds{name="cdn_ranges"}) / 86400', 16, 4, unit="suffix: days",
     decimals=0, desc="Days since the exit firewall's CDN address list was refreshed (update-ranges.sh).",
     thresholds={"mode": "absolute", "steps": [{"color": GOOD, "value": None}, {"color": WARN, "value": 30},
                                               {"color": CRIT, "value": 35}]})
stat("Monitoring push path", 'max(xray_observatory_alive{host="relay",tag=~"mon-.*"})', 20, 4,
     mappings=updown_mappings(), desc="At least one path for the relay's metrics is up.")
nextrow(4)

# ---------------------------------------------------------------- alerts
row("Alerts firing now")
panels.append({"type": "table", "title": "Firing alerts", "id": nid(), "datasource": DS,
               "gridPos": {"h": 5, "w": 24, "x": 0, "y": _y[0]},
               "targets": [target('ALERTS{alertstate="firing",alertname!="Watchdog"}', instant=True,
                                  fmt="table")],
               "transformations": [{"id": "organize", "options": {
                   "excludeByName": {"Time": True, "Value": True, "__name__": True, "alertstate": True,
                                     "job": True, "instance": True},
                   "indexByName": {"alertname": 0, "host": 1, "severity": 2}}}],
               "fieldConfig": {"defaults": {"noValue": "Nothing firing"}, "overrides": []},
               "options": {"showHeader": True}})
nextrow(5)

dashboard = {
    "uid": "vpn-overview", "title": "VPN overview", "tags": ["vpn"], "timezone": "browser",
    "schemaVersion": 39, "version": 1, "editable": True, "refresh": "1m",
    "time": {"from": "now-24h", "to": "now"},
    "annotations": {"list": [
        {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True,
         "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"},
        {"datasource": DS, "enable": True, "iconColor": "#c3c2b7", "name": "Container restarts",
         "expr": 'changes(container_started_time_seconds[2m]) > 0', "step": "60s",
         "titleFormat": "{{host}}: {{name}} restarted", "textFormat": "all its connections dropped"}]},
    "panels": panels,
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "provisioning", "dashboards", "json", "vpn.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8", newline="\n") as f:
    json.dump(dashboard, f, indent=1, ensure_ascii=False)
print(f"wrote {out}: {len([p for p in panels if p['type'] != 'row'])} panels")
