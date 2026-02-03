#!/bin/sh

rm /run/*.pid

# Mock resolvconf to prevent wg-quick from breaking Docker DNS
echo "#!/bin/sh" > /usr/sbin/resolvconf
chmod +x /usr/sbin/resolvconf

if [ "$XRAY_OUTBOUND" = "warp" ]; then
  # xray-config upstream URL for WireGuard configs
  WG_CONFIGS_URL="http://xray-config:5000/wg-configs"

  # Wait for xray-config to be ready
  MAX_RETRIES=30
  RETRY_COUNT=0
  while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
      RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$WG_CONFIGS_URL")
      if [ "$RESPONSE" -eq 200 ]; then
          echo "xray-config is ready: $WG_CONFIGS_URL"
          break
      fi
      echo "Waiting for xray-config to generate WG configs... (HTTP status: $RESPONSE)"
      sleep 2
      RETRY_COUNT=$((RETRY_COUNT + 1))
  done

  if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
      echo "Error: xray-config timed out"
      exit 1
  fi

  # Fetch WireGuard configs and save them locally
  mkdir -p /etc/wireguard
  WG_CONFIGS=$(curl -s "$WG_CONFIGS_URL")
  echo "$WG_CONFIGS"

  # Extract and save each WireGuard config
  for iface in wg0 wg1 wg2; do
      CONFIG_CONTENT=$(echo "$WG_CONFIGS" | jq -r ".\"$iface\" // empty")
      if [ -n "$CONFIG_CONTENT" ]; then
          echo "$CONFIG_CONTENT" > "/etc/wireguard/${iface}.conf"
          echo "Saved /etc/wireguard/${iface}.conf"
      fi
  done

  # Bring up wg interfaces
  for i in 0 1 2; do
      if [ -f "/etc/wireguard/wg$i.conf" ]; then
          echo "Bringing up wg$i..."
          /usr/bin/wg-quick up "wg$i" || echo "Warning: Failed to bring up wg$i"
          
          MONIT_CONF_PATH="/etc/monit.d/wg$i"
          cp /wg_monit "$MONIT_CONF_PATH"
          sed -i "s|\${INTERFACE}|wg$i|g" "$MONIT_CONF_PATH"
      fi
  done
fi

sed -i 's/^#  include \/etc\/monit\.d\/\*$/  include \/etc\/monit.d\/*/' /etc/monitrc

XRAY_CONFIG_URL="http://xray-config:5000/config"

# Wait for Xray config
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$XRAY_CONFIG_URL")
    if [ "$RESPONSE" -eq 200 ]; then
        echo "xray-config is ready: $XRAY_CONFIG_URL"
        break
    fi
    echo "Waiting for xray-config... (HTTP status: $RESPONSE)"
    sleep 2
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "Error: xray-config timed out"
    exit 1
fi

curl -s "$XRAY_CONFIG_URL" > /etc/xray/config.json

# Start Xray immediately so xray-config can test it
/start_xray.sh

monit --version

monit -I
