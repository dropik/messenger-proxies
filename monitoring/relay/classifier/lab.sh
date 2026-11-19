#!/bin/bash
# Stage-1 accuracy test of the disconnect classifier: a controlled Xray client in its own
# network namespace (address 10.99.0.2) connects to the relay's public address like a
# phone, and we end its connections in known ways. The classifier prints episodes for
# that one address only. Run as root on the relay; it takes about 25 minutes.
#
#   usage: lab.sh [RUNS_FAST] [RUNS_SLOW] > lab.log
set -u
RUNS_FAST=${1:-5}; RUNS_SLOW=${2:-3}
HERE=$(cd "$(dirname "$0")" && pwd)
L=/tmp/clf-lab; mkdir -p $L
NS="ip netns exec lab"

# client binary + config (probe users, relay's public address)
if [ ! -x $L/xray ]; then
  id=$(docker create teddysun/xray:26.10.31); docker cp "$id:/usr/bin/xray" $L/xray >/dev/null; docker rm "$id" >/dev/null
fi
cp /etc/monitoring/probe-client.json $L/client.json; chmod 600 $L/client.json

cleanup() { kill $CLF 2>/dev/null; pkill -f "$L/xray" 2>/dev/null; ip netns del lab 2>/dev/null; ip link del veth-lab 2>/dev/null; }
trap cleanup EXIT
ip netns del lab 2>/dev/null; ip link del veth-lab 2>/dev/null
ip netns add lab
ip link add veth-lab type veth peer name veth-lab-ns
ip link set veth-lab-ns netns lab
ip addr add 10.99.0.1/24 dev veth-lab; ip link set veth-lab up
$NS ip addr add 10.99.0.2/24 dev veth-lab-ns; $NS ip link set veth-lab-ns up; $NS ip link set lo up
$NS ip route add default via 10.99.0.1

python3 "$HERE/classifier.py" --bt "$HERE/conn-events.bt" --out $L/classifier.prom --debug-client 10.99.0.2 \
  > $L/episodes.log 2>&1 &
CLF=$!
sleep 8

start_client() { $NS $L/xray run -c $L/client.json >/dev/null 2>&1 & CPID=$!; sleep 2
  for i in 1 2 3; do $NS curl -s -o /dev/null --max-time 10 --proxy http://127.0.0.1:18081 https://www.gstatic.com/generate_204; done; }
# continuous download: the speed-test server refuses single requests over 25 MB (HTTP 403)
download() { $NS bash -c 'while true; do curl -s -o /dev/null --max-time 20 --proxy http://127.0.0.1:18081 "https://speed.cloudflare.com/__down?bytes=25000000"; done' & DL=$!; sleep 3; }
settle() { sleep 16; }     # > classifier GRACE

run() {  # name expected action
  local name=$1 expect=$2; shift 2
  echo "=== $name (expect $expect) $(date +%T)"
  echo "=== $name expect=$expect $(date +%T)" >> $L/episodes.log
  "$@"
  settle
}
s_term_idle()  { start_client; sleep 4; kill -TERM $CPID; wait $CPID 2>/dev/null; }
s_term_dl()    { start_client; download; kill -TERM $CPID; wait $CPID 2>/dev/null; kill $DL 2>/dev/null; }
s_kill_idle()  { start_client; sleep 4; kill -KILL $CPID; wait $CPID 2>/dev/null; }
s_kill_dl()    { start_client; download; kill -KILL $CPID; wait $CPID 2>/dev/null; kill $DL 2>/dev/null; }
s_drop_idle()  { start_client; sleep 4; $NS iptables -I INPUT -j DROP; $NS iptables -I OUTPUT -j DROP; sleep 170
                 kill -KILL $CPID; wait $CPID 2>/dev/null; $NS iptables -F; }
s_drop_dl()    { start_client; download; $NS iptables -I INPUT -j DROP; $NS iptables -I OUTPUT -j DROP; sleep 170
                 kill -KILL $CPID; wait $CPID 2>/dev/null; kill $DL 2>/dev/null; $NS iptables -F; }

for i in $(seq $RUNS_FAST); do
  run "S1 stop, idle"            client_closed s_term_idle
  run "S2 stop, downloading"     client_closed s_term_dl
  run "S3 kill, idle"            client_closed s_kill_idle
  run "S4 kill, downloading"     reset_active  s_kill_dl
done
for i in $(seq $RUNS_SLOW); do
  run "S5 network gone, idle"        vanished s_drop_idle
  run "S6 network gone, downloading" stalled  s_drop_dl
done
sleep 5
echo "=== done $(date +%T)"; echo "=== done" >> $L/episodes.log
cat $L/classifier.prom
