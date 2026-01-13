FROM alpine:3.19

# Install dependencies
RUN apk add --no-cache \
    curl \
    ca-certificates \
    openssl \
    tzdata \
    libcap \
    bash \
    socat

# Install acme.sh (works better with DuckDNS than lego)
RUN curl https://get.acme.sh | sh \
    && ln -s /root/.acme.sh/acme.sh /usr/local/bin/acme.sh

# Install AdGuard Home
ARG AGH_VERSION=0.107.43
RUN curl -sL "https://github.com/AdguardTeam/AdGuardHome/releases/download/v${AGH_VERSION}/AdGuardHome_linux_amd64.tar.gz" | tar xz -C /opt \
    && mv /opt/AdGuardHome /opt/adguardhome

# Create data directories
RUN mkdir -p /opt/adguardhome/conf \
             /opt/adguardhome/work \
             /opt/adguardhome/certs

# Allow binding to port 53
RUN setcap 'cap_net_bind_service=+ep' /opt/adguardhome/AdGuardHome

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /opt/adguardhome

EXPOSE 53/tcp 53/udp 853/tcp 853/udp 3000/tcp

ENTRYPOINT ["/entrypoint.sh"]
