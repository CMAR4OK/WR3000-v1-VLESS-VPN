#!/bin/sh
# xray-router installer — run this ON the OpenWrt router (as root).
#   cd into the unpacked project folder and:  sh install.sh
#
# It installs dependencies, asks for YOUR VLESS server (paste a vless:// link),
# generates the config, and starts a transparent split-tunnel VPN.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "================ xray-router installer ================"

# ---- sanity checks ----
[ "$(id -u)" = "0" ] || { echo "Run as root."; exit 1; }
command -v apk >/dev/null 2>&1 || { echo "This needs OpenWrt with the 'apk' package manager (24.10+/snapshot)."; exit 1; }
command -v nft >/dev/null 2>&1 || { echo "nftables (nft) not found."; exit 1; }

ARCH="$(uname -m 2>/dev/null)"
echo "Router arch: $ARCH  ($(. /etc/openwrt_release 2>/dev/null; echo "$DISTRIB_DESCRIPTION"))"
case "$ARCH" in
    aarch64) XRAY_ARCH="linux-arm64-v8a" ;;
    armv7l)  XRAY_ARCH="linux-arm32-v7a" ;;
    x86_64)  XRAY_ARCH="linux-64" ;;
    mips)    XRAY_ARCH="linux-mips32" ;;
    mipsel)  XRAY_ARCH="linux-mips32le" ;;
    *) echo "Unknown arch '$ARCH' — set XRAY_ARCH manually in /etc/xray/xray.conf later."; XRAY_ARCH="linux-arm64-v8a" ;;
esac
echo "Xray arch:   $XRAY_ARCH"

# ---- dependencies ----
echo; echo ">> Installing dependencies (tproxy modules + unzip)..."
apk update >/dev/null 2>&1 || true
apk add kmod-nft-tproxy kmod-nft-socket unzip >/dev/null 2>&1 || \
    apk add kmod-nft-tproxy kmod-nft-socket unzip
modprobe nft_tproxy 2>/dev/null || true
modprobe nft_socket 2>/dev/null || true
if ! nft list ruleset >/dev/null 2>&1; then echo "nft not working"; exit 1; fi
echo "   ok"

# ---- collect server (VLESS) ----
echo
echo ">> Your VLESS server."
echo "   Paste a vless:// link (recommended), or just press Enter to type fields manually."
printf "vless:// link: "
read VLESS_LINK

ADDR=""; PORT="443"; UUID=""; TYPE="tcp"; SEC="reality"
PBK=""; SID=""; SNI=""; FP="chrome"; FLOW=""; WPATH="/"; WHOST=""

urldecode() { printf '%s' "$1" | sed 's/%2F/\//g; s/%2f/\//g; s/%3A/:/g; s/%2E/./g'; }

if [ -n "$VLESS_LINK" ]; then
    rest="${VLESS_LINK#vless://}"; rest="${rest%%#*}"
    UUID="${rest%%@*}"; rest="${rest#*@}"
    hp="${rest%%\?*}"; ADDR="${hp%%:*}"; PORT="${hp##*:}"
    query="${rest#*\?}"
    SEC=""; TYPE=""
    oldifs="$IFS"; IFS='&'
    for kv in $query; do
        k="${kv%%=*}"; v="${kv#*=}"
        case "$k" in
            type) TYPE="$v" ;; security) SEC="$v" ;; pbk) PBK="$v" ;; sid) SID="$v" ;;
            sni) SNI="$v" ;; fp) FP="$v" ;; flow) FLOW="$v" ;;
            path) WPATH="$(urldecode "$v")" ;; host) WHOST="$v" ;;
        esac
    done
    IFS="$oldifs"
    [ -z "$TYPE" ] && TYPE="tcp"
    [ -z "$SEC" ] && SEC="none"
    [ -z "$WHOST" ] && WHOST="$SNI"
else
    printf "Server address: "; read ADDR
    printf "Port [443]: "; read x; PORT="${x:-443}"
    printf "UUID (id): "; read UUID
    printf "Security (reality/tls) [reality]: "; read x; SEC="${x:-reality}"
    printf "Network (tcp/ws) [tcp]: "; read x; TYPE="${x:-tcp}"
    printf "SNI / serverName: "; read SNI
    printf "Fingerprint [chrome]: "; read x; FP="${x:-chrome}"
    if [ "$SEC" = "reality" ]; then
        printf "Reality public key (pbk): "; read PBK
        printf "Reality short id (sid): "; read SID
        printf "Flow (empty or xtls-rprx-vision) [empty]: "; read FLOW
    fi
    if [ "$TYPE" = "ws" ]; then
        printf "WS path [/]: "; read x; WPATH="${x:-/}"
        printf "WS host header [$SNI]: "; read x; WHOST="${x:-$SNI}"
    fi
fi

[ -n "$ADDR" ] && [ -n "$UUID" ] || { echo "Address and UUID are required."; exit 1; }
echo "   server: $ADDR:$PORT  security=$SEC network=$TYPE sni=$SNI"

# ---- build the proxy outbound JSON ----
USER_JSON="{ \"id\": \"$UUID\", \"encryption\": \"none\", \"level\": 8"
[ -n "$FLOW" ] && USER_JSON="$USER_JSON, \"flow\": \"$FLOW\""
USER_JSON="$USER_JSON }"

if [ "$SEC" = "reality" ]; then
    STREAM="\"network\": \"$TYPE\", \"security\": \"reality\", \"realitySettings\": { \"show\": false, \"fingerprint\": \"$FP\", \"serverName\": \"$SNI\", \"publicKey\": \"$PBK\", \"shortId\": \"$SID\", \"spiderX\": \"/\" }"
elif [ "$SEC" = "tls" ]; then
    STREAM="\"network\": \"$TYPE\", \"security\": \"tls\", \"tlsSettings\": { \"allowInsecure\": false, \"fingerprint\": \"$FP\", \"serverName\": \"$SNI\" }"
    if [ "$TYPE" = "ws" ]; then
        STREAM="$STREAM, \"wsSettings\": { \"path\": \"$WPATH\", \"headers\": { \"Host\": \"$WHOST\" } }"
    fi
else
    STREAM="\"network\": \"$TYPE\""
fi

OUTBOUND="    {
      \"tag\": \"proxy\",
      \"protocol\": \"vless\",
      \"settings\": { \"vnext\": [ { \"address\": \"$ADDR\", \"port\": $PORT, \"users\": [ $USER_JSON ] } ] },
      \"streamSettings\": { $STREAM }
    }"

# ---- assemble /etc/xray ----
echo; echo ">> Writing /etc/xray ..."
mkdir -p /etc/xray
cp "$SCRIPT_DIR/geo/geoip.dat"   /etc/xray/geoip.dat
cp "$SCRIPT_DIR/geo/geosite.dat" /etc/xray/geosite.dat

printf '%s\n' "$OUTBOUND" > /tmp/.ob.json
awk -v obf="/tmp/.ob.json" '
    /__PROXY_OUTBOUND__/ { while ((getline line < obf) > 0) print line; print ","; next }
    { print }
' "$SCRIPT_DIR/config/config.template.json" > /etc/xray/config.json
rm -f /tmp/.ob.json

# remember arch/version for the init script
cat > /etc/xray/xray.conf <<EOF
XRAY_ARCH="$XRAY_ARCH"
# XRAY_VERSION="v26.3.27"
# XRAY_SHA256=""
EOF

# ---- init script ----
cp "$SCRIPT_DIR/etc/init.d/xray" /etc/init.d/xray
chmod 0755 /etc/init.d/xray
/etc/init.d/xray enable

# ---- start ----
echo; echo ">> Starting (downloads the Xray binary into RAM, ~10-20s)..."
/etc/init.d/xray restart
i=0; while [ $i -lt 30 ]; do pidof xray >/dev/null 2>&1 && break; sleep 1; i=$((i+1)); done

echo
if pidof xray >/dev/null 2>&1 && nft list table inet xray >/dev/null 2>&1; then
    echo "================ DONE ✓ ================"
    echo "VPN is running. Listed services route through your server; everything else is direct."
    echo "Logs:        logread -e xray"
    echo "Edit list:   /etc/xray/config.json  then  /etc/init.d/xray restart"
    echo "Stop / start: /etc/init.d/xray stop | start"
else
    echo "Something didn't come up. Check:  logread -e xray"
    echo "(If the binary download failed, the internet still works directly — fail-open.)"
fi
