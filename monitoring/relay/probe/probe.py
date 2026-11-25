#!/usr/bin/env python3
"""End-to-end probe: fetch a few sites through the relay exactly like a client does.

The mon-probe container runs a real Xray client that connects to the relay's public
address over REALITY. It has two local HTTP proxies: forward (127.0.0.1:18081) and direct
(127.0.0.1:18082), each with its own probe user.
Writes node_exporter textfile metrics. Every 15 minutes it also measures download speed.
"""
import argparse
import os
import re
import subprocess
import tempfile
import time

GROUPS = {"forward": "http://127.0.0.1:18081", "direct": "http://127.0.0.1:18082"}
TARGETS = {
    "forward": {
        "generate_204": "https://www.gstatic.com/generate_204",
        "youtube": "https://www.youtube.com/",
        "telegram": "https://web.telegram.org/",
        "instagram": "https://www.instagram.com/",
    },
    "direct": {
        "generate_204": "https://www.gstatic.com/generate_204",
        "yandex": "https://ya.ru/",
    },
}
# OVH's test file. speed.cloudflare.com answers HTTP 429 once an address has fetched too
# often, and it refuses single downloads over 25 MB.
SPEED_URL = "https://proof.ovh.net/files/10Mb.dat"


def curl(proxy, url, timeout, detail=False):
    """-> (http_code, seconds, bytes_per_second); code 0 means the request failed.
    detail=True adds (time_to_first_byte, transfer_bytes_per_second): the transfer phase alone,
    without connection setup, which takes a large share of a short download."""
    r = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "--proxy", proxy, "--max-time", str(timeout),
         "-w", "%{http_code} %{time_total} %{speed_download} %{time_starttransfer} %{size_download}", url],
        capture_output=True, text=True)
    try:
        code, t, speed, ttfb, size = r.stdout.split()
        code, t, speed, ttfb, size = int(code), float(t), float(speed), float(ttfb), float(size)
    except ValueError:
        code, t, speed, ttfb, size = 0, float(timeout), 0.0, 0.0, 0.0
    if not detail:
        return code, t, speed
    xfer = size / (t - ttfb) if t - ttfb > 0.001 else 0.0
    return code, t, speed, ttfb, xfer


def cf_edges(env_file, tries=3):
    """Which Cloudflare data centre each pinned IP reaches, and the TCP connect time there.
    The relay's provider spreads connections over several routes (one IP reaches FRA, AMS or ARN
    depending on the connection), and a bad route makes only the connections on it stall."""
    try:
        env = dict(l.strip().split("=", 1) for l in open(env_file) if "=" in l and not l.startswith("#"))
        host = env["CDN_HOSTNAME"]
    except (OSError, KeyError):
        return []
    lines = ["# HELP cloudflare_edge_ok Trace requests through this pinned IP that succeeded (of 3)",
             "# TYPE cloudflare_edge_ok gauge",
             "# HELP cloudflare_edge_connect_seconds Fastest TCP connect to this data centre via the IP",
             "# TYPE cloudflare_edge_connect_seconds gauge",
             "# HELP cloudflare_edge_hits Trace requests that landed in this data centre (of 3)",
             "# TYPE cloudflare_edge_hits gauge"]
    for n in (1, 2):
        ip = env.get(f"CDN_IP_{n}")
        if not ip:
            continue
        seen, ok = {}, 0
        for _ in range(tries):
            r = subprocess.run(["curl", "-s", "--max-time", "10", "--resolve", f"{host}:443:{ip}",
                                f"https://{host}/cdn-cgi/trace", "-w", "\n@ %{time_connect}\n"],
                               capture_output=True, text=True)
            colo = re.search(r"^colo=([A-Z]{3})$", r.stdout, re.M)
            conn = re.search(r"^@ ([\d.]+)$", r.stdout, re.M)
            if colo and conn:
                ok += 1
                c = seen.setdefault(colo.group(1), [9e9, 0])
                c[0] = min(c[0], float(conn.group(1)))
                c[1] += 1
        lines.append(f'cloudflare_edge_ok{{ip="{n}"}} {ok}')
        for colo, (t, hits) in seen.items():
            lines.append(f'cloudflare_edge_connect_seconds{{ip="{n}",colo="{colo}"}} {t:.3f}')
            lines.append(f'cloudflare_edge_hits{{ip="{n}",colo="{colo}"}} {hits}')
    return lines


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--speed-every", type=int, default=15, help="minutes between speed tests")
    p.add_argument("--cdn-env", help="the relay's .env (CDN_HOSTNAME, CDN_IP_1/2): trace Cloudflare edges")
    a = p.parse_args()

    lines = [
        "# HELP probe_success Fetch through the relay succeeded (2xx/3xx)",
        "# TYPE probe_success gauge",
    ]
    durations = ["# HELP probe_duration_seconds Total fetch time", "# TYPE probe_duration_seconds gauge"]
    for group, proxy in GROUPS.items():
        for target, url in TARGETS[group].items():
            code, t, _ = curl(proxy, url, 15)
            ok = 1 if 200 <= code < 400 else 0
            lines.append(f'probe_success{{group="{group}",target="{target}"}} {ok}')
            durations.append(f'probe_duration_seconds{{group="{group}",target="{target}"}} {t:.3f}')
    lines += durations

    # The speed result is kept between runs so the gauge always has a value.
    speed_file = a.out + ".speed"
    if time.gmtime().tm_min % a.speed_every == 0 or not os.path.exists(speed_file):
        code, _, bps, ttfb, xfer = curl(GROUPS["forward"], SPEED_URL, 60, detail=True)
        lines += ["# HELP probe_download_ok Last speed test got the file (HTTP 200)",
                  "# TYPE probe_download_ok gauge", f'probe_download_ok{{group="forward"}} {1 if code == 200 else 0}']
        # A refused or failed download is not a speed: keep the previous value then.
        if code == 200 or not os.path.exists(speed_file):
            ok = code == 200
            with open(speed_file, "w") as f:
                f.write(f"{bps if ok else 0} {int(time.time())} {ttfb if ok else 0:.3f} {xfer if ok else 0:.0f}\n")
    try:
        v = open(speed_file).read().split() + ["0", "0"]       # older files have two fields
        bps, ts, ttfb, xfer = v[:4]
        lines += [
            "# HELP probe_download_bytes_per_second 10 MB download speed through forward, setup included",
            "# TYPE probe_download_bytes_per_second gauge",
            f'probe_download_bytes_per_second{{group="forward"}} {bps}',
            "# HELP probe_download_transfer_bytes_per_second Same download, transfer phase only",
            "# TYPE probe_download_transfer_bytes_per_second gauge",
            f'probe_download_transfer_bytes_per_second{{group="forward"}} {xfer}',
            "# HELP probe_download_ttfb_seconds Same download, time to first byte",
            "# TYPE probe_download_ttfb_seconds gauge",
            f'probe_download_ttfb_seconds{{group="forward"}} {ttfb}',
            "# HELP probe_download_timestamp_seconds When the speed was last measured",
            "# TYPE probe_download_timestamp_seconds gauge",
            f'probe_download_timestamp_seconds{{group="forward"}} {ts}',
        ]
    except (OSError, ValueError):
        pass
    if a.cdn_env:
        lines += cf_edges(a.cdn_env)
    lines += ["# HELP probe_last_run_timestamp_seconds Last probe run",
              "# TYPE probe_last_run_timestamp_seconds gauge",
              f"probe_last_run_timestamp_seconds {int(time.time())}"]

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(a.out), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, a.out)


if __name__ == "__main__":
    main()
