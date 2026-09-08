#!/bin/bash
# Inbound-bypass for the global sing-box TUN VPN.
#
# When sing-box runs with auto_route + strict_route, the kernel routes ALL
# non-private, non-node outbound traffic through tun0 (ip rule 9001 -> table 2022).
# Replies to *inbound* connections (SSH, web/Caddy) therefore leave through the
# tunnel with the VPN node's source IP -> asymmetric routing -> the client never
# finishes the handshake (SSH hangs / times out).
#
# Fix: mark inbound connections (conntrack) and route their reply packets
# through the main table (direct) via an ip rule, bypassing the tunnel.
# Ports are configurable via BYPASS_PORTS (space separated), default "22 80 443".
# This is additive and independent of sing-box (survives `vpn use ...` restarts).

set -u

NFT="nft"
IP="ip"

TABLE="vpn_ssh_bypass"
MARK="0x1"
RULE_PREF="8500"      # must be < 9000 (sing-box's own rules) so it wins
BYPASS_PORTS="${BYPASS_PORTS:-22 80 443}"

install() {
  "$NFT" add table inet "$TABLE" 2>/dev/null || true
  "$NFT" add chain inet "$TABLE" prerouting \
    '{ type filter hook prerouting priority mangle; policy accept; }' 2>/dev/null || true
  "$NFT" add chain inet "$TABLE" output \
    '{ type route hook output priority mangle; policy accept; }' 2>/dev/null || true
  for p in $BYPASS_PORTS; do
    "$NFT" add rule inet "$TABLE" prerouting tcp dport "$p" \
      ct mark set "$MARK" 2>/dev/null || true
  done
  "$NFT" add rule inet "$TABLE" output ct mark "$MARK" \
    meta mark set "$MARK" 2>/dev/null || true

  "$IP" rule del pref "$RULE_PREF" 2>/dev/null || true
  "$IP" rule add pref "$RULE_PREF" fwmark "$MARK" lookup main
  echo "inbound-bypass: OK (tcp/$BYPASS_PORTS -> ct mark $MARK -> ip rule pref $RULE_PREF -> main)"
}

uninstall() {
  "$NFT" delete table inet "$TABLE" 2>/dev/null || true
  "$IP" rule del pref "$RULE_PREF" 2>/dev/null || true
  echo "ssh-bypass: removed"
}

status() {
  echo "ip rule:"
  "$IP" rule show | grep -E "^$RULE_PREF:" || echo "  (нет)"
  echo "nftables:"
  "$NFT" list table inet "$TABLE" 2>/dev/null || echo "  (нет)"
}

case "${1:-}" in
  install) install ;;
  uninstall) uninstall ;;
  status) status ;;
  *) echo "usage: $0 {install|uninstall|status}" ;;
esac
