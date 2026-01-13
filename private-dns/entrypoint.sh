#!/bin/sh
set -e

# Load environment from config file
if [ ! -f /config/env ]; then
    echo "ERROR: /config/env not found!"
    echo "Copy config/env.example to config/env and fill in your values"
    exit 1
fi

export $(grep -v '^#' /config/env | xargs)

# Validate required variables
if [ -z "$DUCKDNS_SUBDOMAIN" ] || [ "$DUCKDNS_SUBDOMAIN" = "your_subdomain" ]; then
    echo "ERROR: DUCKDNS_SUBDOMAIN not set in config/env"
    exit 1
fi

if [ -z "$DUCKDNS_TOKEN" ] || [ "$DUCKDNS_TOKEN" = "your_token_here" ]; then
    echo "ERROR: DUCKDNS_TOKEN not set in config/env"
    exit 1
fi

if [ -z "$PROXY_IP" ] || [ "$PROXY_IP" = "your_vps_ip" ]; then
    echo "ERROR: PROXY_IP not set in config/env"
    exit 1
fi

DOMAIN="${DUCKDNS_SUBDOMAIN}.duckdns.org"
echo "=========================================="
echo "Private DNS Setup"
echo "Domain: $DOMAIN"
echo "Proxy IP: $PROXY_IP"
echo "=========================================="

# Update DuckDNS with current IP
echo "Updating DuckDNS..."
RESULT=$(curl -s "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=")
if [ "$RESULT" = "OK" ]; then
    echo "DuckDNS updated successfully"
else
    echo "WARNING: DuckDNS update failed: $RESULT"
fi

# Certificate paths
CERT_DIR="/opt/adguardhome/certs"
CERT_FILE="$CERT_DIR/fullchain.pem"
KEY_FILE="$CERT_DIR/privkey.pem"
ACME_DIR="/root/.acme.sh/${DOMAIN}_ecc"

# Check if certificate exists and is valid
NEED_CERT=false
if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "Certificate not found, will request new one"
    NEED_CERT=true
else
    # Check if cert expires within 30 days
    if openssl x509 -checkend 2592000 -noout -in "$CERT_FILE" 2>/dev/null; then
        echo "Certificate is valid"
    else
        echo "Certificate expires soon, will renew"
        NEED_CERT=true
    fi
fi

# Get/renew certificate using acme.sh
if [ "$NEED_CERT" = "true" ]; then
    echo "Requesting certificate using acme.sh..."
    
    # Use acme.sh with DuckDNS
    # --dnssleep 120 waits 2 minutes for DNS propagation (no active checking)
    # --server letsencrypt uses Let's Encrypt instead of ZeroSSL default
    export DuckDNS_Token="$DUCKDNS_TOKEN"
    
    # Register account if needed (with or without email)
    if [ -n "$ACME_EMAIL" ]; then
        acme.sh --register-account -m "$ACME_EMAIL" --server letsencrypt 2>/dev/null || true
    else
        acme.sh --register-account --server letsencrypt 2>/dev/null || true
    fi
    
    if [ -d "$ACME_DIR" ]; then
        echo "Renewing existing certificate..."
        acme.sh --renew -d "$DOMAIN" --dnssleep 120 --server letsencrypt || {
            echo "Renewal failed, trying fresh issue..."
            acme.sh --issue --dns dns_duckdns -d "$DOMAIN" --dnssleep 120 --server letsencrypt --force || {
                echo "Certificate request failed. Continuing without TLS..."
            }
        }
    else
        echo "Issuing new certificate..."
        acme.sh --issue --dns dns_duckdns -d "$DOMAIN" --dnssleep 120 --server letsencrypt || {
            echo "Certificate request failed. Continuing without TLS..."
        }
    fi
    
    # Copy certs to AdGuard directory
    if [ -f "$ACME_DIR/fullchain.cer" ]; then
        cp "$ACME_DIR/fullchain.cer" "$CERT_FILE"
        cp "$ACME_DIR/${DOMAIN}.key" "$KEY_FILE"
        chmod 600 "$KEY_FILE"
        echo "Certificate installed successfully"
    fi
fi

# Generate AdGuard Home config if it doesn't exist
AGH_CONFIG="/opt/adguardhome/conf/AdGuardHome.yaml"
if [ ! -f "$AGH_CONFIG" ]; then
    echo "Generating AdGuard Home configuration..."
    mkdir -p /opt/adguardhome/conf
    
    cat > "$AGH_CONFIG" << EOF
bind_host: 0.0.0.0
bind_port: 3000
users: []
# No users = setup wizard will appear on first access
auth_attempts: 5
block_auth_min: 15
http_proxy: ""
language: en
theme: auto
dns:
  bind_hosts:
    - 0.0.0.0
  port: 53
  anonymize_client_ip: false
  protection_enabled: true
  blocking_mode: default
  blocked_response_ttl: 10
  protection_disabled_until: null
  parental_block_host: family-block.dns.adguard.com
  safebrowsing_block_host: standard-block.dns.adguard.com
  ratelimit: 0
  ratelimit_whitelist: []
  refuse_any: true
  upstream_dns:
    - https://dns.cloudflare.com/dns-query
    - https://dns.google/dns-query
  upstream_dns_file: ""
  bootstrap_dns:
    - 8.8.8.8
    - 1.1.1.1
  all_servers: false
  fastest_addr: true
  fastest_timeout: 1s
  allowed_clients: []
  disallowed_clients: []
  blocked_hosts:
    - version.bind
    - id.server
    - hostname.bind
  trusted_proxies:
    - 127.0.0.0/8
    - ::1/128
  cache_size: 4194304
  cache_ttl_min: 0
  cache_ttl_max: 0
  cache_optimistic: true
  bogus_nxdomain: []
  aaaa_disabled: false
  enable_dnssec: true
  edns_client_subnet:
    custom_ip: ""
    enabled: false
    use_custom: false
  max_goroutines: 300
  handle_ddr: true
  ipset: []
  ipset_file: ""
  filtering_enabled: true
  filters_update_interval: 24
  parental_enabled: false
  safesearch_enabled: false
  safebrowsing_enabled: false
  safebrowsing_cache_size: 1048576
  safesearch_cache_size: 1048576
  parental_cache_size: 1048576
  cache_time: 30
  rewrites:
    - domain: '*.whatsapp.net'
      answer: ${PROXY_IP}
    - domain: '*.whatsapp.com'
      answer: ${PROXY_IP}
    - domain: '*.fbcdn.net'
      answer: ${PROXY_IP}
    - domain: '*.cdninstagram.com'
      answer: ${PROXY_IP}
  blocked_services:
    ids: []
    schedule:
      time_zone: UTC
  local_domain_name: lan
  resolve_clients: true
  use_private_ptr_resolvers: true
  local_ptr_upstreams: []
  serve_http3: false
  use_http3_upstreams: false
tls:
  enabled: true
  server_name: ${DOMAIN}
  force_https: false
  port_https: 0
  port_dns_over_tls: 853
  port_dns_over_quic: 853
  port_dnscrypt: 0
  dnscrypt_config_file: ""
  allow_unencrypted_doh: false
  certificate_chain: ""
  private_key: ""
  certificate_path: /opt/adguardhome/certs/fullchain.pem
  private_key_path: /opt/adguardhome/certs/privkey.pem
  strict_sni_check: false
querylog:
  enabled: true
  file_enabled: true
  interval: 720h
  size_memory: 1000
  ignored: []
statistics:
  enabled: true
  interval: 720h
  ignored: []
filters:
  - enabled: false
    url: https://adguardteam.github.io/HostlistsRegistry/assets/filter_1.txt
    name: AdGuard DNS filter
    id: 1
whitelist_filters: []
user_rules: []
dhcp:
  enabled: false
clients:
  runtime_sources:
    whois: true
    arp: true
    rdns: true
    dhcp: true
    hosts: true
  persistent: []
log_file: ""
log_max_backups: 0
log_max_size: 100
log_max_age: 3
log_compress: false
log_localtime: false
verbose: false
os:
  group: ""
  user: ""
  rlimit_nofile: 0
schema_version: 24
EOF

    echo "AdGuard Home configuration generated"
fi

echo ""
echo "=========================================="
echo "Starting AdGuard Home..."
echo "Web UI: http://${PROXY_IP}:3000"
echo "DNS-over-TLS: tls://${DOMAIN}"
echo "Private DNS (Android): ${DOMAIN}"
echo "=========================================="

exec /opt/adguardhome/AdGuardHome --no-check-update -c /opt/adguardhome/conf/AdGuardHome.yaml -w /opt/adguardhome/work
