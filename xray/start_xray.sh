#!/bin/sh

/usr/bin/xray -c /etc/xray/config.json > /var/log/xray.log 2>&1 &

echo $! > /run/xray.pid

sleep 1