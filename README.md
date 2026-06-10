# xray-router

Turn a small **OpenWrt** router into a transparent **VLESS (Xray)** VPN gateway with
**split‑tunnel** routing: only the services you list go through your VPN server, everything
else stays direct (local speed, real IP). Works for **TCP and UDP** (games, voice) via TPROXY.

Originally built for a **Cudy WR3000** (MediaTek MT7981 / `aarch64`) on OpenWrt 25.12, but it
should work on any OpenWrt 24.10+/snapshot device with the `apk` package manager and the
`kmod-nft-tproxy` module available.

> You bring your own VLESS server (a `vless://` link). No keys are bundled in this repo.

---

## Features

- **Transparent proxy** for the whole LAN — no per‑device setup.
- **Split tunnel**: a curated default list (Telegram, YouTube, Google, Instagram, Discord,
  WhatsApp, ChatGPT, Claude, Roblox, Clash Royale/Supercell, TikTok, …) routes through the VPN;
  everything else goes direct. Fully editable.
- **TCP + UDP** via nftables **TPROXY** (so game UDP and QUIC can be tunnelled).
- **Tiny on flash**: the Xray binary (~35 MB) lives in **RAM** and is downloaded from the
  official Xray‑core GitHub release at every boot. Only a small config + minimal geo files
  (~40 KB) stay on flash.
- **Fail‑open**: if the binary can't be fetched at boot, the internet still works (directly).
- Optional **GUI** to edit the routed list over SSH (`tools/vpn_manager.py`).

## How it works

```
LAN client ──▶ nftables TPROXY (mark, tcp+udp) ──▶ Xray dokodemo-door
                                                      │  (sniffs SNI / matches geo)
                          ┌───────────────────────────┤
            listed sites  ▼                           ▼  everything else
                    VLESS outbound ──▶ your server          direct (WAN)
```

DNS from the LAN is sent through the tunnel (anti‑poisoning). IPv6 forwarding from the LAN is
dropped to avoid leaks (clients use IPv4). QUIC (UDP/443) is dropped so apps fall back to TCP,
which routes reliably by SNI — comment that one line out in `etc/init.d/xray` if you prefer to
tunnel QUIC.

---

## Requirements

- OpenWrt **24.10 / 25.x / snapshot** (uses the `apk` package manager).
- `kmod-nft-tproxy`, `kmod-nft-socket`, `unzip` available in the repo (installer adds them).
- Architecture: defaults to `aarch64` (`linux-arm64-v8a`). Other arches are auto‑detected; if
  yours is exotic, set `XRAY_ARCH` in `/etc/xray/xray.conf` after install.
- Your own **VLESS** server (Reality or WS+TLS), as a `vless://` link.

## Install

On the router (SSH in as `root`):

```sh
# get the project onto the router
cd /tmp
wget -O xr.tar.gz https://github.com/CMAR4OK/WR3000-v1-VLESS-VPN-Readdy-RU-/archive/refs/heads/main.tar.gz
tar xzf xr.tar.gz
cd WR3000-v1-VLESS-VPN-Readdy-RU--main

# run the installer (it will ask for your vless:// link)
sh install.sh
```

(No `wget`/`tar`? Use `git clone`, or copy the folder over with `scp`/WinSCP, then `sh install.sh`.)

Paste your `vless://` link when asked, e.g.:

```
vless://UUID@1.2.3.4:8443?type=tcp&security=reality&pbk=PUBLICKEY&sid=SHORTID&sni=www.microsoft.com&fp=chrome&flow=#myserver
```

That's it. Verify:

```sh
logread -e xray            # routing decisions ([transparent -> proxy] / -> direct)
```

## Configure which sites use the VPN

Edit the routed lists in **`/etc/xray/config.json`** (`routing.rules`), then:

```sh
/etc/init.d/xray restart
```

- Add a site: put `"domain:example.com"` in the proxy `domain` rule.
- Add an IP/subnet: put `"1.2.3.0/24"` in the proxy `ip` rule.
- `geosite:<cat>` / `geoip:<cat>` work only for categories in the bundled geo files
  (geosite: telegram, youtube, google, instagram, facebook, discord, openai; geoip: telegram,
  facebook). Regenerate with more categories using `geo/geofilter.py` (see below).
- **Send everything through the VPN** instead of split tunnel: replace the whole `rules` array
  with a single rule `{ "type":"field", "outboundTag":"proxy", "network":"tcp,udp" }`
  (keep the `dns-in -> proxy` rule first).

### Optional GUI (Windows)

`tools/vpn_manager.py` is a small Tkinter app to edit the domain/IP lists over SSH. It uses
PuTTY's `plink.exe` (set the path in the app). Run with `python tools/vpn_manager.py`. It
validates the config (`xray -test`) before applying. No secrets are stored in the script —
enter your router IP/password in the app; the host key is fetched automatically.

## Change the VPN server later

Edit the `proxy` outbound in `/etc/xray/config.json` (address/port/uuid/sni/keys), then
`/etc/init.d/xray restart`. Or just re‑run `sh install.sh` with a new link.

## Update / pin the Xray version

Defaults are in `etc/init.d/xray` and overridable in `/etc/xray/xray.conf`:

```sh
XRAY_VERSION="v26.3.27"      # any Xray-core release tag
XRAY_ARCH="linux-arm64-v8a"  # your router's arch
XRAY_SHA256=""               # optional: pin the unzipped binary's sha256
```

## Regenerate the geo files (more/less categories)

The bundled `geo/geoip.dat` / `geo/geosite.dat` are **minimal** (a few KB) so they fit in RAM
cheaply. To rebuild with the categories you want, on a PC with Python:

```sh
# download full bases (Loyalsoldier), then filter:
python geo/geofilter.py filter geoip-full.dat   geo/geoip.dat   "telegram,facebook,google"
python geo/geofilter.py filter geosite-full.dat geo/geosite.dat "telegram,youtube,google,netflix,discord"
# (use 'list' instead of 'filter' to see all available categories)
```
Copy the new files to `/etc/xray/` and `/etc/init.d/xray restart`.

## Uninstall

```sh
sh uninstall.sh
```

---

## Limitations / notes

- **IPv6** is not tunnelled; LAN IPv6 forwarding is dropped to avoid leaks (clients are IPv4).
- DNS for the LAN goes through the VPN. Apps using DoH/encrypted DNS bypass this.
- Some apps connect to CDNs with **ECH** (encrypted SNI) — if a service half‑works, add its
  CDN IP range to the proxy `ip` rule (find it via `logread -e xray` → `[transparent -> direct]`).
- This is **not** a DPI‑bypass tool. It routes traffic through *your* VLESS server; the server
  is what bypasses blocks. If a service uses a fixed port (e.g. Supercell games on 9339), a
  `{ "outboundTag":"proxy", "port":"9339" }` rule catches it regardless of IP.

## Credits

- [XTLS/Xray-core](https://github.com/XTLS/Xray-core) — the proxy core (MPL‑2.0).
- [Loyalsoldier/v2ray-rules-dat](https://github.com/Loyalsoldier/v2ray-rules-dat) — source of the geo data.
- [OpenWrt](https://openwrt.org/).

## License

MIT (this repo's scripts/config). Xray‑core and the geo data keep their own licenses.

## Disclaimer

For lawful use only (privacy, accessing services you are entitled to, testing your own
network). You are responsible for complying with the laws and terms that apply to you.
