#!/bin/bash
# Выключить глобальный VPN (вернуть прямой интернет)
PASS=$(cat ~/.sudo_password 2>/dev/null)
if [ -n "$PASS" ]; then
  echo "$PASS" | sudo -S systemctl stop sing-box 2>/dev/null
else
  sudo systemctl stop sing-box
fi
sleep 2
if ! systemctl is-active -q sing-box; then
  ~/vpn-tool/vpn cron remove >/dev/null 2>&1
fi
echo "VPN OFF, egress: $(curl -s --max-time 8 https://api.ipify.org)"
