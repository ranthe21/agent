#!/bin/sh

/usr/bin/killall cloudflared

echo $! > /run/cloudflared.pid