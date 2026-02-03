#!/bin/sh

/usr/bin/cloudflared proxy-dns \
                     --address 127.0.0.1 \
                     --port 53 \
                     --upstream https://dns.google \
                     > /var/log/cloudflared.log 2>&1 &

echo $! > /run/cloudflared.pid

sleep 1