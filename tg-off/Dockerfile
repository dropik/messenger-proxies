FROM debian:bookworm-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    git \
    openssl \
    curl \
    xxd \
    && rm -rf /var/lib/apt/lists/*

# Clone and build MTProxy
RUN git clone --depth 1 https://github.com/TelegramMessenger/MTProxy.git /mtproxy \
    && cd /mtproxy \
    && make -j$(nproc)

WORKDIR /mtproxy

# Create data directory
RUN mkdir -p /data

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 443 8888

ENTRYPOINT ["/entrypoint.sh"]
