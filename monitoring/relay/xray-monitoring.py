#!/usr/bin/env python3
"""Add monitoring to the relay's Xray config (idempotent). Writes config.json.new.

Adds:
- stats and a metrics endpoint (0.0.0.0:11111 in the container; compose publishes it on
  127.0.0.1 only)
- "monitor-in": a localhost-only HTTP proxy inbound (port 10809) that vmagent uses to push
  metrics. It goes out via mon-cdn (Cloudflare) with mon-cfws (CloudFront WebSocket) as
  fallback, as the exit's monitoring user.
- probe users: probe@relay (routed like forward) and probe-direct@relay (routed like direct)
- TCP keepalive on the client inbound: detect vanished clients in about 2 minutes
- private destinations (geoip:private, geosite:private) blocked for client traffic

Secrets come from files and are never printed:
  /etc/monitoring/monitor-uuid  (the exit's monitor@cdn id)
  /etc/monitoring/probe-uuids.json (created here if missing)
"""
import copy
import json
import os
import sys
import uuid

CONF = sys.argv[1] if len(sys.argv) > 1 else "config.json"
c = json.load(open(CONF))
mon_id = open("/etc/monitoring/monitor-uuid").read().strip()
pfile = "/etc/monitoring/probe-uuids.json"
if not os.path.exists(pfile):
    old = os.umask(0o077)
    json.dump({"probe@relay": str(uuid.uuid4()), "probe-direct@relay": str(uuid.uuid4())},
              open(pfile, "w"))
    os.umask(old)
probes = json.load(open(pfile))

c["stats"] = {}
c["metrics"] = {"tag": "metrics", "listen": "0.0.0.0:11111"}
c["policy"] = {"system": {k: True for k in ("statsInboundUplink", "statsInboundDownlink",
                                              "statsOutboundUplink", "statsOutboundDownlink")}}

vin = next(i for i in c["inbounds"] if i["tag"] == "vless-in")
cl = [x for x in vin["settings"]["clients"] if not x["email"].startswith("probe")]
cl += [{"id": probes[e], "email": e, "flow": ""} for e in ("probe@relay", "probe-direct@relay")]
vin["settings"]["clients"] = cl
vin["streamSettings"]["sockopt"] = {"tcpKeepAliveIdle": 60, "tcpKeepAliveInterval": 20,
                                    "tcpUserTimeout": 120000}
c["inbounds"] = [i for i in c["inbounds"] if i["tag"] != "monitor-in"] + [
    {"tag": "monitor-in", "listen": "0.0.0.0", "port": 10809, "protocol": "http"}]

ob = {o["tag"]: o for o in c["outbounds"]}
mons = []
for src, tag in (("exit-cdn", "mon-cdn"), ("exit-cfws", "mon-cfws")):
    o = copy.deepcopy(ob[src])
    o["tag"] = tag
    o["settings"]["vnext"][0]["users"] = [{"id": mon_id, "encryption": "none"}]
    mons.append(o)
c["outbounds"] = [o for o in c["outbounds"] if not o["tag"].startswith("mon-")]
c["outbounds"][-1:-1] = mons            # before "block"

sel = c["burstObservatory"]["subjectSelector"]
if "mon-" not in sel:
    sel.append("mon-")

r = c["routing"]
r["balancers"] = [b for b in r["balancers"] if b["tag"] != "monitor"] + [
    {"tag": "monitor", "selector": ["mon-cdn"], "fallbackTag": "mon-cfws",
     "strategy": {"type": "roundRobin"}}]
rules = [x for x in r["rules"] if x.get("inboundTag") not in (["monitor-in"], ["vless-in"])]
for x in rules:
    if x.get("user") and "direct@relay" in x["user"] and "probe-direct@relay" not in x["user"]:
        x["user"].append("probe-direct@relay")
r["rules"] = [
    {"type": "field", "inboundTag": ["monitor-in"], "balancerTag": "monitor"},
    {"type": "field", "inboundTag": ["vless-in"], "ip": ["geoip:private"], "outboundTag": "block"},
    {"type": "field", "inboundTag": ["vless-in"], "domain": ["geosite:private"], "outboundTag": "block"},
] + rules

old = os.umask(0o077)
json.dump(c, open(CONF + ".new", "w"), indent=2)
os.umask(old)
print("clients:", [x["email"] for x in vin["settings"]["clients"]])
print("inbounds:", [i["tag"] for i in c["inbounds"]])
print("outbounds:", [o["tag"] for o in c["outbounds"]])
print("balancers:", [(b["tag"], b["selector"], b.get("fallbackTag")) for b in r["balancers"]])
print("rules:", [(x.get("inboundTag") or x.get("user") or x.get("domain") or x.get("network"),
                  x.get("ip") or x.get("domain") if x.get("inboundTag") else "",
                  x.get("outboundTag") or x.get("balancerTag")) for x in r["rules"]])
