#!/bin/bash
# Прозрачный шлюз для телевизора через глобальный VPN (sing-box TUN).
#
# Пускает трафик ТВ (192.168.0.100) через tun0 в VPN. Трафик ТВ уже заводится
# в туннель правилом sing-box `9001: from all lookup 2022`, поэтому здесь нужен
# только SNAT (masquerade) на tun0, чтобы ответы VPN-узла возвращались на сервер.
#
# MASQUERADE сделан отдельной nftables-таблицей (НЕ через /etc/ufw/before.rules),
# т.к. UFW при reload сбрасывает nat-таблицу и снёс бы правила Docker.
#
# Форвардинг (filter) разрешён отдельно через `ufw route allow` (persistent).
# IP forwarding: /etc/ufw/sysctl.conf (net.ipv4.ip_forward=1).
#
# Требования на стороне ТВ (см. server-notes/tv-vpn.md):
#   IP 192.168.0.100, шлюз 192.168.0.107, DNS 192.168.0.1.
#
# ВАЖНО: masquerade ставится ТОЛЬКО на LAN-интерфейс (fallback при выключенном
# VPN). На tun0 masquerade НЕ ставим: SNAT к 172.19.0.1 (собственный IP туна)
# заставляет sing-box отвечать с 172.19.0.2, conntrack помечает такой SYN-ACK
# как INVALID и UFW его режет. Трафик ТВ идёт в тун с реальным src 192.168.0.100,
# а ответы sing-box возвращает на него же (приватные сети исключены из туна).

set -u

NFT="nft"
TABLE="vpn_tv_gateway"
CHAIN="tv_postrouting"
TV_IP="${TV_IP:-192.168.0.100}"
LAN_IF="${LAN_IF:-wlp1s0}"

install() {
  "$NFT" add table inet "$TABLE" 2>/dev/null || true
  "$NFT" add chain inet "$TABLE" "$CHAIN" \
    '{ type nat hook postrouting priority srcnat; policy accept; }' 2>/dev/null || true
  "$NFT" flush chain inet "$TABLE" "$CHAIN" 2>/dev/null || true
  "$NFT" add rule inet "$TABLE" "$CHAIN" ip saddr "$TV_IP" oifname "$LAN_IF" masquerade
  echo "tv-vpn: OK (masquerade $TV_IP -> $LAN_IF; tun0 — без masquerade)"
}

uninstall() {
  "$NFT" delete table inet "$TABLE" 2>/dev/null || true
  echo "tv-vpn: removed"
}

status() {
  echo "nftables (inet $TABLE):"
  "$NFT" list table inet "$TABLE" 2>/dev/null || echo "  (нет)"
  echo "ip_forward: $(cat /proc/sys/net/ipv4/ip_forward)"
}

case "${1:-}" in
  install) install ;;
  uninstall) uninstall ;;
  status) status ;;
  *) echo "usage: $0 {install|uninstall|status}" ;;
esac
