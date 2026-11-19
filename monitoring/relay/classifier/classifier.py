#!/usr/bin/env python3
"""Classify how clients disconnect from the relay, from kernel TCP events (conn-events.bt).

A "disconnect episode" means one client address has no open connection left for longer than
GRACE seconds. Shorter gaps are normal connection churn. Each episode is labelled from how
its last connections ended:

  injected?     a reset whose TTL differs from the client's SYN TTL (filtering equipment?)
  reset_active  a reset from the client while traffic was flowing (app/process killed?)
  reset_idle    a reset from the client on idle connections
  client_closed the client closed its connections (FIN; usually followed by a reset when the
                relay still writes): VPN switched off, app stopped, or killed while idle
  stalled       timeout with data unacknowledged (path broke during traffic)
  vanished      keepalive timeout on idle connections (network change, phone gone)

Lab results (Linux Xray client, monitoring/relay/classifier/lab.sh, 2026-11-19):
  killed during a download     -> reset_active   3/3
  stopped during a download    -> client_closed  3/3 (never reset_active)
  stopped or killed while idle -> client_closed  6/6 (the two are indistinguishable)
  network cut while idle       -> vanished       7/7, about 2 minutes after the cut
  network cut during download  -> stalled        1/1
  relay_closed  the relay closed the connections
  other         anything else

Privacy:
- Client addresses exist only in this process's memory, keyed by HMAC with a random key
  per run, and are dropped once their episode is decided.
- Nothing per client is written or logged. Only totals by label go to the textfile.
- --debug-client prints details for ONE given address (a lab test client), nothing else.
"""
import argparse
import hmac
import ipaddress
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict

HZ = 250                 # kernel CONFIG_HZ: idle values come in jiffies
GRACE = 10.0             # seconds without connections before it counts as a disconnect
WINDOW = 3.0             # connection ends this close to the last one belong to the episode
RESUME = 60.0            # same address back within this -> "resumed"
ACTIVE_MS = 5000         # received data within this before the end -> traffic was flowing
KEY = os.urandom(32)

ap = argparse.ArgumentParser()
ap.add_argument("--bt", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "conn-events.bt"))
ap.add_argument("--out", default="/var/lib/node_exporter/textfile/classifier.prom")
ap.add_argument("--container", default="vless-relay")
ap.add_argument("--exclude", action="append", default=[], help="own addresses (the probe)")
ap.add_argument("--debug-client", help="print episode details for this one address only")
a = ap.parse_args()


def norm(addr):
    ip = ipaddress.ip_address(addr)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return str(ip)


EXCLUDE = {norm(x) for x in a.exclude}
DEBUG = norm(a.debug_client) if a.debug_client else None


def key(addr):
    return hmac.new(KEY, addr.encode(), "sha256").digest()[:8]


lock = threading.Lock()
open_count = defaultdict(int)           # client key -> open connections
ends = defaultdict(list)                # client key -> [(t, kind, active)]
pending = {}                            # client key -> time its count reached 0
recent = {}                             # client key -> (episode time, label) for RESUME
debug_key = key(DEBUG) if DEBUG else None
syn_ttl = {}                            # (addr, port) -> ttl, short-lived
sk_flow = {}                            # sk -> (client key, syn ttl)
rst_ttl = {}                            # sk -> ttl of the reset that is about to end it
closed = {}                             # sk -> (time, end record) for late resets after a FIN
flow_ends = Counter()
episodes = Counter()
resumed = Counter()
ttl_checked = ttl_mismatch = 0


def seed():
    pid = subprocess.run(["docker", "inspect", "-f", "{{.State.Pid}}", a.container],
                         capture_output=True, text=True).stdout.strip()
    r = subprocess.run(["nsenter", "-t", pid, "-n", "ss", "-Htn", "state", "established",
                        "( sport = :443 )"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        peer = line.split()[3].rsplit(":", 1)[0].strip("[]")
        addr = norm(peer)
        if addr not in EXCLUDE:
            open_count[key(addr)] += 1


def classify(evs):
    kinds = {e[1] for e in evs}
    active = any(e[2] for e in evs)
    if "reset_ttl_mismatch" in kinds:
        return "injected?"
    if kinds & {"reset", "reset_ttl_mismatch"}:
        return "reset_active" if active else "reset_idle"
    if "timeout_unacked" in kinds:
        return "stalled"
    if "timeout_idle" in kinds:
        return "vanished"
    if kinds and kinds <= {"fin", "fin_reset"}:
        return "client_closed"
    if kinds <= {"relay_close", "fin", "fin_reset"} and "relay_close" in kinds:
        return "relay_closed"
    return "other"


def handle(parts):
    global ttl_checked, ttl_mismatch
    t = time.time()
    typ = parts[0]
    if typ == "S":
        addr = norm(parts[1])
        if addr not in EXCLUDE:
            syn_ttl[(addr, parts[2])] = int(parts[3])
            if len(syn_ttl) > 10000:
                syn_ttl.clear()
    elif typ == "O":
        sk, addr, port = parts[1], norm(parts[2]), parts[3]
        if addr in EXCLUDE:
            return
        k = key(addr)
        sk_flow[sk] = (k, syn_ttl.pop((addr, port), None))
        open_count[k] += 1
        pending.pop(k, None)               # came back within GRACE: churn, not an episode
        if k in recent and t - recent[k][0] < RESUME:
            resumed[recent.pop(k)[1]] += 1
    elif typ == "R":
        sk, state = parts[1], int(parts[3])
        if state == 1:                                   # ESTABLISHED: an E line follows
            rst_ttl[sk] = int(parts[2])
        elif sk in closed:                               # after the client's FIN
            rec = closed.pop(sk)[1]
            if rec[1] == "fin":
                rec[1] = "fin_reset"
                flow_ends["fin"] -= 1
                flow_ends["fin_reset"] += 1
                if rec[3] == debug_key:
                    print(f"{time.strftime('%H:%M:%S')} late reset after fin", flush=True)
    elif typ == "E":
        sk, how, err = parts[1], parts[2], int(parts[3])
        idle_rcv_ms = int(parts[4]) * 1000 // HZ
        idle_snd_ms = int(parts[5]) * 1000 // HZ
        retrans, probes = int(parts[6]), int(parts[7])
        unacked = retrans
        addr = norm(parts[8])
        if addr in EXCLUDE:
            return
        k = key(addr)
        flow = sk_flow.pop(sk, None)
        rttl = rst_ttl.pop(sk, None)
        if how == "P":
            kind = "fin"
        elif how == "L":
            kind = "relay_close"
        elif err == 104:
            kind = "reset"
            s = flow[1] if flow else None
            if s is not None and rttl:
                ttl_checked += 1
                if abs(s - rttl) >= 2:
                    ttl_mismatch += 1
                    kind = "reset_ttl_mismatch"
        elif err == 110:
            kind = "timeout_unacked" if retrans > 0 else "timeout_idle"
        else:
            kind = "abort_other"
        flow_ends[kind] += 1
        active = min(idle_rcv_ms, idle_snd_ms) < ACTIVE_MS
        rec = [t, kind, active, k]                       # mutable: a late reset may upgrade it
        ends[k].append(rec)
        ends[k] = [e for e in ends[k] if t - e[0] < 60]
        if how == "P":
            closed[sk] = (t, rec)
        for s in [s for s, (t0, _) in closed.items() if t - t0 > 10]:
            del closed[s]
        open_count[k] = max(0, open_count[k] - 1)
        if open_count[k] == 0:
            pending[k] = t
        if k == debug_key:
            print(f"{time.strftime('%H:%M:%S')} end kind={kind} err={err} idle_rcv_ms={idle_rcv_ms} "
                  f"idle_snd_ms={idle_snd_ms} retrans={retrans} probes={probes} open_left={open_count[k]}",
                  flush=True)


def decide():
    t = time.time()
    with lock:
        for k, t0 in list(pending.items()):
            if t - t0 < GRACE:
                continue
            del pending[k]
            evs = [e for e in ends.pop(k, []) if t0 - e[0] <= WINDOW]
            for s in [s for s, (_, rec) in closed.items() if rec[3] == k]:
                del closed[s]
            label = classify(evs)
            episodes[label] += 1
            recent[k] = (t0, label)
            open_count.pop(k, None)
            if k == debug_key:
                print(f"{time.strftime('%H:%M:%S')} EPISODE {label} from {sorted(Counter(x[1] for x in evs).items())}",
                      flush=True)
        for k in [k for k, (t0, _) in recent.items() if t - t0 > RESUME]:
            del recent[k]


def write():
    with lock:
        lines = ["# TYPE conn_flow_ends_total counter"]
        lines += [f'conn_flow_ends_total{{kind="{k}"}} {v}' for k, v in sorted(flow_ends.items())]
        lines += ["# TYPE disconnect_episodes_total counter"]
        lines += [f'disconnect_episodes_total{{class="{k}"}} {v}' for k, v in sorted(episodes.items())]
        lines += ["# TYPE disconnect_episodes_resumed_total counter"]
        lines += [f'disconnect_episodes_resumed_total{{class="{k}"}} {v}' for k, v in sorted(resumed.items())]
        lines += [f"conn_rst_ttl_checked_total {ttl_checked}", f"conn_rst_ttl_mismatch_total {ttl_mismatch}",
                  f"classifier_clients_connected {sum(1 for v in open_count.values() if v > 0)}",
                  f"classifier_last_update_timestamp_seconds {int(time.time())}"]
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(a.out), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, a.out)


def ticker():
    while True:
        time.sleep(5)
        decide()
        write()


def main():
    p = subprocess.Popen(["bpftrace", a.bt], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, bufsize=1)
    for line in p.stdout:              # wait until probes are attached, then seed
        if line.startswith("READY"):
            break
    with lock:
        seed()
    threading.Thread(target=ticker, daemon=True).start()
    for line in p.stdout:
        parts = line.split()
        if not parts:
            continue
        try:
            with lock:
                handle(parts)
        except (ValueError, IndexError):
            pass                        # never echo the line: it contains an address
    sys.exit("bpftrace exited")


if __name__ == "__main__":
    main()
