#!/bin/bash
# Включить глобальный VPN (sing-box TUN)
PASS=$(cat ~/.sudo_password 2>/dev/null)
if [ -n "$PASS" ]; then
  echo "$PASS" | sudo -S systemctl start sing-box 2>/dev/null
else
  sudo systemctl start sing-box
fi
sleep 3
if systemctl is-active -q sing-box; then
  echo "VPN ON, egress: $(curl -s --max-time 8 https://api.ipify.org)"
  ~/vpn-tool/vpn cron install >/dev/null 2>&1
else
  echo "VPN failed to start"
fi
