#!/bin/sh
# Remove xray-router from the router. Run as root.
/etc/init.d/xray stop 2>/dev/null
/etc/init.d/xray disable 2>/dev/null
rm -f /etc/init.d/xray
rm -rf /etc/xray
rm -f /tmp/xray /tmp/xray.zip
nft delete table inet xray 2>/dev/null
nft delete table inet xray_fwd 2>/dev/null
ip rule del fwmark 1 lookup 100 2>/dev/null
ip route flush table 100 2>/dev/null
echo "xray-router removed."
echo "Dependencies kept (apk del kmod-nft-tproxy kmod-nft-socket unzip  to remove them too)."
