#!/usr/bin/env python3
"""End-to-end probe: fetch a few sites through the relay exactly like a client does.

The mon-probe container runs a real Xray client that connects to the relay's public
address over REALITY. It has two local HTTP proxies: forward (127.0.0.1:18081) and direct
(127.0.0.1:18082), each with its own probe user.
Writes node_exporter textfile metrics. Every 15 minutes it also measures download speed.
"""
import argparse
import os
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
SPEED_URL = "https://speed.cloudflare.com/__down?bytes=10000000"


def curl(proxy, url, timeout):
    """-> (http_code, seconds, bytes_per_second); code 0 means the request failed."""
    r = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "--proxy", proxy, "--max-time", str(timeout),
         "-w", "%{http_code} %{time_total} %{speed_download}", url],
        capture_output=True, text=True)
    try:
        code, t, speed = r.stdout.split()
        return int(code), float(t), float(speed)
    except ValueError:
        return 0, float(timeout), 0.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--speed-every", type=int, default=15, help="minutes between speed tests")
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
        code, _, bps = curl(GROUPS["forward"], SPEED_URL, 60)
        with open(speed_file, "w") as f:
            f.write(f"{bps if code == 200 else 0} {int(time.time())}\n")
    try:
        bps, ts = open(speed_file).read().split()
        lines += [
            "# HELP probe_download_bytes_per_second 10 MB download speed through forward",
            "# TYPE probe_download_bytes_per_second gauge",
            f'probe_download_bytes_per_second{{group="forward"}} {bps}',
            "# HELP probe_download_timestamp_seconds When the speed was last measured",
            "# TYPE probe_download_timestamp_seconds gauge",
            f'probe_download_timestamp_seconds{{group="forward"}} {ts}',
        ]
    except (OSError, ValueError):
        pass
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
