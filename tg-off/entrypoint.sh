#!/bin/sh
set -e

DATA_DIR="/data"
SECRET_FILE="$DATA_DIR/secret"
PROXY_SECRET_FILE="$DATA_DIR/proxy-secret"
PROXY_CONFIG_FILE="$DATA_DIR/proxy-multi.conf"

# Generate secret if not exists
if [ ! -f "$SECRET_FILE" ]; then
    echo "Generating new secret..."
    head -c 16 /dev/urandom | xxd -ps > "$SECRET_FILE"
fi

SECRET=$(cat "$SECRET_FILE")
echo "Secret: $SECRET"

# Download proxy secret from Telegram (for connecting to Telegram servers)
if [ ! -f "$PROXY_SECRET_FILE" ] || [ $(find "$PROXY_SECRET_FILE" -mmin +1440 2>/dev/null) ]; then
    echo "Downloading proxy secret from Telegram..."
    curl -s https://core.telegram.org/getProxySecret -o "$PROXY_SECRET_FILE" || {
        echo "Failed to download proxy secret"
        exit 1
    }
fi

# Download proxy config (Telegram server IPs)
if [ ! -f "$PROXY_CONFIG_FILE" ] || [ $(find "$PROXY_CONFIG_FILE" -mmin +1440 2>/dev/null) ]; then
    echo "Downloading proxy config from Telegram..."
    curl -s https://core.telegram.org/getProxyConfig -o "$PROXY_CONFIG_FILE" || {
        echo "Failed to download proxy config"
        exit 1
    }
fi

# Get external IP for connection info
EXTERNAL_IP=${EXTERNAL_IP:-$(curl -s https://api.ipify.org || echo "YOUR_SERVER_IP")}
PORT=${PORT:-443}

# Build connection links
echo ""
echo "=========================================="
echo "MTProxy is starting..."
echo "=========================================="
echo ""
echo "Connection details:"
echo "  Server: $EXTERNAL_IP"
echo "  Port: $PORT"
echo "  Secret: $SECRET"
echo ""
echo "Telegram Links:"
echo "  tg://proxy?server=${EXTERNAL_IP}&port=${PORT}&secret=${SECRET}"
echo "  https://t.me/proxy?server=${EXTERNAL_IP}&port=${PORT}&secret=${SECRET}"
echo ""

# Optional: Fake TLS mode for better obfuscation
# Prepend 'ee' to secret and add domain hex for fake TLS
if [ -n "$FAKE_TLS_DOMAIN" ]; then
    DOMAIN_HEX=$(echo -n "$FAKE_TLS_DOMAIN" | xxd -ps)
    FAKE_SECRET="ee${SECRET}${DOMAIN_HEX}"
    echo "Fake TLS Mode (disguised as $FAKE_TLS_DOMAIN):"
    echo "  Secret: $FAKE_SECRET"
    echo ""
    echo "Telegram Links (Fake TLS):"
    echo "  tg://proxy?server=${EXTERNAL_IP}&port=${PORT}&secret=${FAKE_SECRET}"
    echo "  https://t.me/proxy?server=${EXTERNAL_IP}&port=${PORT}&secret=${FAKE_SECRET}"
    echo ""
fi

echo "=========================================="
echo ""

# Run MTProxy
# -u nobody -g nobody: run as non-root
# -H $PORT: listen port
# -S $SECRET: proxy secret
# -P: enable proxy protocol (optional)
# --aes-pwd: path to proxy secret file
# --http-stats: enable stats on different port if needed

# Run MTProxy
# -u nobody: run as non-root
# -p $PORT: listen port
# -S $SECRET: proxy secret (16 bytes hex)
# -H 8888: HTTP stats port
# --aes-pwd: path to proxy secret file
# --http-stats: enable stats endpoint

exec /mtproxy/objs/bin/mtproto-proxy \
    -u nobody \
    -p 8888 \
    -H $PORT \
    -S "$SECRET" \
    --aes-pwd "$PROXY_SECRET_FILE" \
    --http-stats \
    "$PROXY_CONFIG_FILE"
