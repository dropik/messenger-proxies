# WhatsApp Proxy Server Dockerfile
# Based on WhatsApp's official proxy implementation using HAProxy

FROM alpine:3.19

LABEL maintainer="WhatsApp Proxy"
LABEL description="WhatsApp Proxy Server for bypassing network restrictions"

# Install HAProxy and required packages
RUN apk add --no-cache \
    haproxy \
    openssl \
    ca-certificates

# Create directories for certificates and configuration
RUN mkdir -p /etc/haproxy/certs /var/lib/haproxy

# Generate self-signed certificate for TLS termination
RUN openssl req -x509 -nodes -days 3650 \
    -newkey rsa:2048 \
    -keyout /etc/haproxy/certs/proxy.key \
    -out /etc/haproxy/certs/proxy.crt \
    -subj "/C=US/ST=State/L=City/O=WhatsAppProxy/CN=whatsapp-proxy" && \
    cat /etc/haproxy/certs/proxy.crt /etc/haproxy/certs/proxy.key > /etc/haproxy/certs/proxy.pem && \
    chmod 600 /etc/haproxy/certs/proxy.pem

# Copy HAProxy configuration
COPY haproxy.cfg /etc/haproxy/haproxy.cfg

# Expose WhatsApp proxy ports (TCP only)
# 80    - HTTP
# 443   - HTTPS/TLS
# 587   - Media transfers
# 7777  - Media transfers (alt)
# 5222  - XMPP (WhatsApp messaging)
# 8080  - Alternative HTTP port
# 8443  - Alternative HTTPS port
# 8404  - HAProxy stats
EXPOSE 80 443 587 7777 5222 8080 8443 8404

# Run HAProxy
CMD ["haproxy", "-f", "/etc/haproxy/haproxy.cfg", "-db"]
