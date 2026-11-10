#!/usr/bin/env python3
"""Regenerate the subscription Worker on the relay and deploy it with wrangler.

Run from your own machine, not the relay: the Cloudflare login stays here, so
whoever controls the relay cannot rewrite the Worker.

    python vless-relay/subscription/deploy.py root@RELAY_IP

Needs: ssh access to the relay, Node.js, and `npx wrangler login` done once.
The Worker's name and hostname are read from subs.json on the relay
(keys "worker_name" and "worker_host").
"""
import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

COMPAT_DATE = "2026-11-01"


def ssh(host, command):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", host, command], capture_output=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "subscription-check"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # TLS / network problems
        return f"error: {type(e).__name__}", b""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host", help="ssh target of the relay, e.g. root@RELAY_IP")
    ap.add_argument("--relay-dir", default="/root/messenger-proxies/vless-relay")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()
    sub_dir = f"{args.relay_dir}/subscription"

    print("1/4 regenerating on the relay")
    print("    " + ssh(args.host, f"cd {args.relay_dir} && python3 subscription/gen_worker.py").strip()
          .replace("\n", "\n    "))
    worker_js = ssh(args.host, f"cat {sub_dir}/worker.js")
    subs = json.loads(ssh(args.host, f"cat {sub_dir}/subs.json"))
    name, host = subs.get("worker_name"), subs.get("worker_host")
    if not name or not host:
        sys.exit("set worker_name and worker_host in subs.json on the relay")

    npx = shutil.which("npx") or sys.exit("npx not found: install Node.js")
    tmp = Path(tempfile.mkdtemp(prefix="sub-worker-"))
    try:
        (tmp / "worker.js").write_text(worker_js, encoding="utf-8")
        print(f"2/4 deploying Worker '{name}'")
        r = subprocess.run([npx, "--yes", "wrangler", "deploy", "worker.js", "--name", name,
                            "--compatibility-date", COMPAT_DATE, "--no-bundle"],
                           cwd=tmp, capture_output=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            sys.exit("wrangler deploy failed:\n" + r.stdout[-1500:] + r.stderr[-1500:])
        version = re.search(r"Current Version ID:\s*(\S+)", r.stdout)
        print(f"    deployed{', version ' + version.group(1) if version else ''}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("3/4 removed local copy")

    if args.no_verify:
        return
    print(f"4/4 verifying https://{host}/")
    routes = json.loads(re.search(r"const SUBS = (\{.*?\});\n", worker_js, re.S).group(1))
    ok = True
    for email, g in subs["groups"].items():
        status, body = fetch(f"https://{host}/{g['token']}")
        try:
            match = base64.b64decode(body).decode().split("\n") == routes[g["token"]]["links"]
        except Exception:
            match = False
        ok &= status == 200 and match
        print(f"    {email}: HTTP {status}, content matches: {match}")
    status, _ = fetch(f"https://{host}/not-a-token")
    ok &= status == 404
    print(f"    wrong token: HTTP {status}")
    print("done" if ok else "VERIFY FAILED (a fresh deploy can take a few seconds to propagate)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
