FROM wernight/dante

# Create default user (can be overridden at build time)
ARG SOCKS_USER=telegram
ARG SOCKS_PASS=password

# Add user with specified username and password
RUN adduser -D $SOCKS_USER && \
    echo "$SOCKS_USER:$SOCKS_PASS" | chpasswd
    
COPY sockd.conf /etc/
