#!/usr/bin/env python3
"""Write node_exporter textfile metrics for one host.

Collects, all optional:
  --xray NAME=URL          Xray metrics endpoint (/debug/vars): traffic per inbound/outbound,
                           observatory (path health), Go memory.
  --container NAME         Docker container: running, start time, OOM-killed.
  --cert NAME=PATH         certificate expiry (PEM, first certificate in the file).
  --log NAME=CONTAINER=RE  cumulative count of container log lines matching RE.
                           Only counts are kept; log lines are never stored.
  --file-age NAME=PATH     modification time of a file.
  --sockets NAME=CONTAINER=PORT
                           totals over the container's established TCP connections on PORT
                           (open, silent 30+ min, waiting on unacknowledged data, with a
                           keepalive timer). No addresses are kept.
  --peers NAME=CONTAINER=MATCH[,MATCH...]
                           TCP health of the container's established connections matching any
                           MATCH (dst:IP, dport:PORT or sport:PORT; no spaces, so the option
                           survives systemd's word splitting): connections, stuck ones, RTT,
                           and counters of retransmits, out-of-order packets and bytes. For the
                           relay's connections to Cloudflare and the exit's from it. Sockets are
                           tracked between runs by a hash; counts a socket gathers after the
                           last run before it closes are lost, so the counters run slightly low.

Runs from a systemd timer (as root, for docker and the certificates). Writes atomically.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


class Out:
    def __init__(self):
        self.lines, self.seen = [], set()

    def add(self, metric, value, help_, type_="gauge", /, **labels):
        if metric not in self.seen:
            self.seen.add(metric)
            self.lines.append(f"# HELP {metric} {help_}")
            self.lines.append(f"# TYPE {metric} {type_}")
        lab = ",".join(f'{k}="{esc(v)}"' for k, v in labels.items())
        self.lines.append(f"{metric}{{{lab}}} {value}" if lab else f"{metric} {value}")


def run(cmd, timeout=20):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


def split2(s, n):
    parts = s.split("=", n - 1)
    if len(parts) != n:
        sys.exit(f"bad argument: {s!r}")
    return parts


def collect_xray(out, name, url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            d = json.load(r)
    except Exception:
        out.add("xray_up", 0, "Xray metrics endpoint reachable", xray=name)
        return
    out.add("xray_up", 1, "Xray metrics endpoint reachable", xray=name)
    for kind, tags in (d.get("stats") or {}).items():
        for tag, v in (tags or {}).items():
            for direction in ("uplink", "downlink"):
                if direction in v:
                    out.add("xray_traffic_bytes_total", v[direction],
                            "Bytes through Xray since its start", "counter",
                            xray=name, kind=kind, tag=tag, direction=direction)
    now = time.time()
    for tag, o in (d.get("observatory") or {}).items():
        out.add("xray_observatory_alive", 1 if o.get("alive") else 0,
                "Outbound passed its last health check", xray=name, tag=tag)
        out.add("xray_observatory_delay_ms", o.get("delay", 0),
                "Health check response time", xray=name, tag=tag)
        if o.get("last_seen_time"):
            out.add("xray_observatory_last_seen_age_seconds", round(now - o["last_seen_time"]),
                    "Seconds since the outbound last passed a check", xray=name, tag=tag)
    ms = d.get("memstats") or {}
    for key, metric in (("HeapAlloc", "xray_go_heap_bytes"), ("Sys", "xray_go_sys_bytes")):
        if key in ms:
            out.add(metric, ms[key], f"Go runtime {key}", xray=name)


def collect_containers(out, names):
    for n in names:
        r = run(["docker", "inspect", "-f",
                 "{{.State.Running}} {{.State.StartedAt}} {{.State.OOMKilled}}", n])
        if r.returncode != 0:
            out.add("container_running", 0, "Container is running", name=n)
            continue
        running, started, oom = r.stdout.split()
        out.add("container_running", 1 if running == "true" else 0, "Container is running", name=n)
        out.add("container_oom_killed", 1 if oom == "true" else 0,
                "Container's last exit was an OOM kill", name=n)
        ts = run(["date", "-u", "-d", started, "+%s"]).stdout.strip()
        if ts.isdigit():
            out.add("container_started_time_seconds", ts, "When the container last started", name=n)


def collect_cert(out, name, path):
    r = run(["openssl", "x509", "-enddate", "-noout", "-in", path])
    if r.returncode == 0 and "=" in r.stdout:
        ts = run(["date", "-u", "-d", r.stdout.strip().split("=", 1)[1], "+%s"]).stdout.strip()
        if ts.isdigit():
            out.add("cert_not_after_seconds", ts, "Certificate expiry time", name=name)
            return
    out.add("cert_read_error", 1, "Certificate could not be read", name=name)


def collect_sockets(out, name, container, port):
    pid = run(["docker", "inspect", "-f", "{{.State.Pid}}", container]).stdout.strip()
    if not pid.isdigit() or pid == "0":
        return
    r = run(["nsenter", "-t", pid, "-n", "ss", "-Htino", "state", "established",
             f"( sport = :{port} )"])
    if r.returncode != 0:
        return
    n = silent = unacked = backoff = keepalive = 0
    for line in r.stdout.splitlines():
        if not line.startswith(("\t", " ")):          # connection line (info lines are indented)
            n += 1
            if "timer:(keepalive" in line:
                keepalive += 1
            continue
        rcv = re.search(r"lastrcv:(\d+)", line)
        snd = re.search(r"lastsnd:(\d+)", line)
        if rcv and snd and int(rcv.group(1)) > 1_800_000 and int(snd.group(1)) > 1_800_000:
            silent += 1
        if "unacked:" in line:
            unacked += 1
        if "backoff:" in line:
            backoff += 1
    for metric, v, h in (
        ("tcp_conns_established", n, "Established TCP connections"),
        ("tcp_conns_silent_30m", silent, "Connections with nothing sent or received for 30+ min"),
        ("tcp_conns_unacked", unacked, "Connections with data waiting for acknowledgement"),
        ("tcp_conns_backoff", backoff, "Connections in retransmission backoff (peer not answering)"),
        ("tcp_conns_keepalive_timer", keepalive, "Connections with a keepalive timer"),
    ):
        out.add(metric, v, h, name=name, port=port)


PEER_COUNTERS = (  # ss -i field -> counter metric
    ("retrans", "tcp_peer_retrans_segments_total", "Segments retransmitted (loss on the way out)"),
    ("rcv_ooopack", "tcp_peer_rcv_ooo_packets_total", "Packets received out of order (loss on the way in)"),
    ("segs_out", "tcp_peer_segs_out_total", "Segments sent"),
    ("bytes_received", "tcp_peer_received_bytes_total", "Bytes received"),
    ("bytes_acked", "tcp_peer_acked_bytes_total", "Bytes sent and acknowledged"),
)


def ss_filter(match):
    terms = []
    for m in match.split(","):
        kind, _, val = m.partition(":")
        if kind == "dst":
            terms.append(f"dst {val}")
        elif kind in ("dport", "sport"):
            terms.append(f"{kind} = :{val}")
        else:
            sys.exit(f"bad --peers match: {m!r}")
    return "( " + " or ".join(terms) + " )"


def collect_peers(out, name, container, match, state):
    pid = run(["docker", "inspect", "-f", "{{.State.Pid}}", container]).stdout.strip()
    if not pid.isdigit() or pid == "0":
        return
    r = run(["nsenter", "-t", pid, "-n", "ss", "-Htin", "state", "established", ss_filter(match)])
    if r.returncode != 0:
        return
    socks, cur = {}, None
    for line in r.stdout.splitlines():
        if not line.startswith(("\t", " ")):
            f = line.split()
            cur = hashlib.sha256(" ".join(f[-2:]).encode()).hexdigest()[:16]  # local + peer
            socks[cur] = ""
        elif cur:
            socks[cur] += line
    prev = state.get(f"peers:{name}", {})
    totals = state.get(f"peer_totals:{name}", {})
    now, rtts, stuck, backoff = {}, [], 0, 0
    for key, info in socks.items():
        vals = []
        for field, _, _ in PEER_COUNTERS:
            m = re.search(rf"\b{field}:(?:\d+/)?(\d+)", info)    # retrans:cur/total -> total
            vals.append(int(m.group(1)) if m else 0)
        old = prev.get(key, [0] * len(vals))
        for (field, _, _), v, o in zip(PEER_COUNTERS, vals, old):
            totals[field] = totals.get(field, 0) + max(v - o, 0)
        now[key] = vals
        m = re.search(r"\brtt:([\d.]+)", info)
        if m:
            rtts.append(float(m.group(1)))
        if "backoff:" in info:
            backoff += 1
        ack = re.search(r"lastack:(\d+)", info)
        if "unacked:" in info and ack and int(ack.group(1)) >= 2000:
            stuck += 1
    state[f"peers:{name}"] = now
    state[f"peer_totals:{name}"] = totals
    rtts.sort()
    out.add("tcp_peer_conns", len(socks), "Established connections to/from these peers", name=name)
    out.add("tcp_peer_stuck_conns", stuck, "Connections with sent data unacknowledged for 2+ s", name=name)
    out.add("tcp_peer_backoff_conns", backoff, "Connections in retransmission backoff", name=name)
    if rtts:
        out.add("tcp_peer_rtt_median_ms", rtts[len(rtts) // 2], "Median smoothed RTT", name=name)
        out.add("tcp_peer_rtt_max_ms", rtts[-1], "Highest smoothed RTT", name=name)
    for field, metric, h in PEER_COUNTERS:
        out.add(metric, totals.get(field, 0), h, "counter", name=name)


def collect_logs(out, specs, state):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    by_container = {}
    for name, container, regex in specs:
        by_container.setdefault(container, []).append((name, re.compile(regex)))
    for container, pats in by_container.items():
        key = f"logs_since:{container}"
        since = state.get(key)
        counts = {n: 0 for n, _ in pats}
        if since:
            r = run(["docker", "logs", "--since", since, "--until", now, container], timeout=60)
            if r.returncode == 0:
                for line in (r.stdout + r.stderr).splitlines():
                    for n, rx in pats:
                        if rx.search(line):
                            counts[n] += 1
        state[key] = now
        for n, c in counts.items():
            total = state.get(f"count:{n}", 0) + c
            state[f"count:{n}"] = total
            out.add("log_matches_total", total,
                    "Container log lines matching a pattern (counted, never stored)", "counter",
                    name=n, container=container)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--xray", action="append", default=[])
    p.add_argument("--container", action="append", default=[])
    p.add_argument("--cert", action="append", default=[])
    p.add_argument("--log", action="append", default=[])
    p.add_argument("--file-age", action="append", default=[])
    p.add_argument("--sockets", action="append", default=[])
    p.add_argument("--peers", action="append", default=[])
    a = p.parse_args()

    t0 = time.time()
    try:
        with open(a.state) as f:
            state = json.load(f)
    except Exception:
        state = {}
    out = Out()
    for s in a.xray:
        collect_xray(out, *split2(s, 2))
    collect_containers(out, a.container)
    for s in a.cert:
        collect_cert(out, *split2(s, 2))
    collect_logs(out, [split2(s, 3) for s in a.log], state)
    for s in a.sockets:
        collect_sockets(out, *split2(s, 3))
    for s in a.peers:
        collect_peers(out, *split2(s, 3), state)
    for s in a.file_age:
        name, path = split2(s, 2)
        if os.path.exists(path):
            out.add("file_mtime_seconds", int(os.path.getmtime(path)), "File modification time",
                    name=name)
    out.add("collector_last_run_timestamp_seconds", int(time.time()), "Last collector run")
    out.add("collector_duration_seconds", round(time.time() - t0, 3), "Collector run time")

    for path, text in ((a.state, json.dumps(state)), (a.out, "\n".join(out.lines) + "\n")):
        d = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)


if __name__ == "__main__":
    main()
