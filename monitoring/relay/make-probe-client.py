#!/usr/bin/env python3
"""Build the probe's Xray client config from the relay's live config.

Writes /etc/monitoring/probe-client.json (mode 600): two local HTTP proxies,
127.0.0.1:18081 (probe@relay, routed like forward) and 127.0.0.1:18082 (probe-direct@relay,
routed like direct). Both connect to the relay's public address the way the client links
do. Prints no secrets.

usage: make-probe-client.py RELAY_CONFIG SUBS_JSON [OUT]
"""
import json
import os
import re
import subprocess
import sys

conf, subs = sys.argv[1], sys.argv[2]
out = sys.argv[3] if len(sys.argv) > 3 else "/etc/monitoring/probe-client.json"
c = json.load(open(conf))
address = os.environ.get("PROBE_ADDRESS") or json.load(open(subs))["address"]   # override for tests
vin = next(i for i in c["inbounds"] if i["tag"] == "vless-in")
rs, xs = vin["streamSettings"]["realitySettings"], vin["streamSettings"]["xhttpSettings"]
ids = {x["email"]: x["id"] for x in vin["settings"]["clients"]}
for e in ("probe@relay", "probe-direct@relay"):
    if e not in ids:
        sys.exit(f"{e} is not a client in {conf}; run xray-monitoring.py and apply it first")

o = subprocess.run(["docker", "exec", "vless-relay", "xray", "x25519", "-i", rs["privateKey"]],
                   capture_output=True, text=True, check=True).stdout
m = re.search(r"(?:Public key|PublicKey|Password)[^:]*:\s*(\S+)", o)
if not m:
    sys.exit("could not derive the REALITY public key")


def outbound(tag, uid):
    return {
        "tag": tag, "protocol": "vless",
        "settings": {"vnext": [{"address": address, "port": vin["port"],
                                "users": [{"id": uid, "encryption": "none"}]}]},
        "streamSettings": {
            "network": "xhttp", "security": "reality",
            "realitySettings": {"serverName": rs["serverNames"][0], "fingerprint": "chrome",
                                "publicKey": m.group(1), "shortId": rs["shortIds"][0]},
            "xhttpSettings": {"path": xs["path"], "host": xs.get("host", ""),
                              "mode": xs.get("mode", "auto")},
        },
    }


client = {
    "log": {"loglevel": "warning", "access": "none"},
    "inbounds": [
        {"tag": "forward", "listen": "127.0.0.1", "port": 18081, "protocol": "http"},
        {"tag": "direct", "listen": "127.0.0.1", "port": 18082, "protocol": "http"},
    ],
    "outbounds": [outbound("as-forward", ids["probe@relay"]),
                  outbound("as-direct", ids["probe-direct@relay"])],
    "routing": {"rules": [
        {"type": "field", "inboundTag": ["forward"], "outboundTag": "as-forward"},
        {"type": "field", "inboundTag": ["direct"], "outboundTag": "as-direct"},
    ]},
}
old = os.umask(0o077)
json.dump(client, open(out, "w"), indent=2)
os.umask(old)
print(f"wrote {out}")
