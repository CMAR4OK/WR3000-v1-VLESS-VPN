# xray-router

Прозрачный **VLESS (Xray)** VPN-шлюз на роутере **OpenWrt** со **split-tunnel** маршрутизацией:
через VPN идут только нужные сервисы, остальное — напрямую (локальная скорость, реальный IP).
Работает с **TCP и UDP** (игры, голос) через TPROXY.

Сделано для роутера **Cudy WR3000 v1** (MediaTek MT7981 / `aarch64`) на OpenWrt 25.12, но должно
работать на любом OpenWrt 24.10+/snapshot с пакетным менеджером `apk` и модулем `kmod-nft-tproxy`.

> Свой VLESS-сервер вы вставляете сами (ссылкой `vless://`). В репозитории нет никаких ключей.

**🌐 Язык:** [Русский](#-русский) · [English](#-english)

---

## 🇷🇺 Русский

### Что это

Превращает дешёвый OpenWrt-роутер в VPN-шлюз на Xray/VLESS. Раздаёт VPN на всю сеть без настройки
каждого устройства. По умолчанию — **split-tunnel**: через VPN идут только перечисленные сервисы
(Telegram, YouTube, Google, Instagram, Discord, WhatsApp, ChatGPT, Claude, Roblox, Clash Royale,
TikTok и т.д.), а всё остальное — напрямую. Список полностью редактируется.

### Возможности

- **Прозрачный прокси** на всю LAN — без настройки на каждом устройстве.
- **Split-tunnel** из коробки (через VPN — только нужное; остальное напрямую = быстрее).
- **TCP + UDP** через nftables **TPROXY** (тунелится игровой UDP и QUIC).
- **Почти не занимает флеш**: бинарь Xray (~35 МБ) живёт в **RAM** и качается из официального
  релиза Xray-core на GitHub при каждой загрузке. Во флеше — только конфиг + мини-geo (~40 КБ).
- **Fail-open**: если бинарь не скачался при загрузке — интернет всё равно работает (напрямую).
- Опциональный **GUI** для правки списка сайтов по SSH (`tools/vpn_manager.py`).

### Как это работает

```
Клиент LAN ──▶ nftables TPROXY (метка, tcp+udp) ──▶ Xray dokodemo-door
                                                       │  (сниффит SNI / матчит geo)
                          ┌────────────────────────────┤
        сервисы из списка ▼                            ▼  всё остальное
                    VLESS outbound ──▶ ваш сервер           напрямую (WAN)
```

DNS клиентов идёт через туннель (защита от подмены). IPv6-форвардинг из LAN дропается (тунелим
только IPv4 → без утечек). QUIC (UDP/443) дропается, чтобы приложения откатились на TCP, который
надёжно роутится по SNI — закомментируйте эту строку в `etc/init.d/xray`, если хотите тунелить QUIC.

### Требования

- OpenWrt **24.10 / 25.x / snapshot** (пакетный менеджер `apk`).
- В репозитории доступны `kmod-nft-tproxy`, `kmod-nft-socket`, `unzip` (установщик их доставит).
- Архитектура: по умолчанию `aarch64` (`linux-arm64-v8a`). Другие определяются автоматически; если
  экзотика — пропишите `XRAY_ARCH` в `/etc/xray/xray.conf` после установки.
- Свой **VLESS**-сервер (Reality или WS+TLS) в виде ссылки `vless://`.

### Установка

По SSH на роутер (под `root`):

```sh
cd /tmp
wget -O xr.tar.gz https://github.com/CMAR4OK/WR3000-v1-VLESS-VPN-Readdy-RU-/archive/refs/heads/main.tar.gz
tar xzf xr.tar.gz
cd WR3000-v1-VLESS-VPN-Readdy-RU--main

# запуск установщика (он спросит вашу vless:// ссылку)
sh install.sh
```

Нет `wget`/`tar`? Используйте `git clone` или скопируйте папку через `scp`/WinSCP, затем `sh install.sh`.

Вставьте свою `vless://` ссылку, когда спросит, например:

```
vless://UUID@1.2.3.4:8443?type=tcp&security=reality&pbk=ПУБКЛЮЧ&sid=SHORTID&sni=www.microsoft.com&fp=chrome&flow=#myserver
```

Проверить:

```sh
logread -e xray            # решения маршрутизации ([transparent -> proxy] / -> direct)
```

### Настройка: какие сайты идут через VPN

Правьте списки в **`/etc/xray/config.json`** (`routing.rules`), затем:

```sh
/etc/init.d/xray restart
```

- Добавить сайт: `"domain:example.com"` в правило proxy `domain`.
- Добавить IP/подсеть: `"1.2.3.0/24"` в правило proxy `ip`.
- `geosite:<кат>` / `geoip:<кат>` работают только для категорий в комплектных geo-файлах
  (geosite: telegram, youtube, google, instagram, facebook, discord, openai; geoip: telegram,
  facebook). Больше категорий — пересоберите geo через `geo/geofilter.py` (см. ниже).
- **Всё через VPN** вместо split-tunnel: замените весь массив `rules` одним правилом
  `{ "type":"field", "outboundTag":"proxy", "network":"tcp,udp" }` (правило `dns-in -> proxy`
  оставьте первым).

#### GUI (Windows, опционально)

`tools/vpn_manager.py` — небольшое приложение (Tkinter) для правки списков доменов/IP по SSH.
Использует `plink.exe` из PuTTY (укажите путь в приложении). Запуск: `python tools/vpn_manager.py`.
Перед применением проверяет конфиг (`xray -test`). Секретов в скрипте нет — IP/пароль роутера
вводите в приложении, host key берётся автоматически.

### Сменить VPN-сервер позже

Поправьте outbound `proxy` в `/etc/xray/config.json` (адрес/порт/uuid/sni/ключи), затем
`/etc/init.d/xray restart`. Либо просто перезапустите `sh install.sh` с новой ссылкой.

### Версия Xray

Настройки в `etc/init.d/xray`, переопределяются в `/etc/xray/xray.conf`:

```sh
XRAY_VERSION="v26.3.27"      # любой тег релиза Xray-core
XRAY_ARCH="linux-arm64-v8a"  # архитектура вашего роутера
XRAY_SHA256=""               # опционально: зафиксировать sha256 распакованного бинаря
```

### Пересборка geo (больше/меньше категорий)

Комплектные `geo/geoip.dat` / `geo/geosite.dat` — **минимальные** (несколько КБ), чтобы дёшево
жить в RAM. Чтобы собрать со своими категориями, на ПК с Python:

```sh
# скачайте полные базы (Loyalsoldier), затем отфильтруйте:
python geo/geofilter.py filter geoip-full.dat   geo/geoip.dat   "telegram,facebook,google"
python geo/geofilter.py filter geosite-full.dat geo/geosite.dat "telegram,youtube,google,netflix,discord"
# (вместо 'filter' используйте 'list', чтобы увидеть все доступные категории)
```
Скопируйте новые файлы в `/etc/xray/` и `/etc/init.d/xray restart`.

### Удаление

```sh
sh uninstall.sh
```

### Ограничения

- **IPv6** не тунелится; форвардинг IPv6 из LAN дропается во избежание утечек (клиенты на IPv4).
- DNS LAN идёт через VPN. Приложения с DoH/шифрованным DNS это обходят.
- Некоторые приложения ходят на CDN с **ECH** (шифрованный SNI) — если сервис работает наполовину,
  добавьте диапазон IP его CDN в правило proxy `ip` (найдите его в `logread -e xray` →
  `[transparent -> direct]`).
- Это **не** DPI-обход. Трафик идёт через *ваш* VLESS-сервер; блокировки обходит именно сервер.
  Если у сервиса фиксированный порт (напр. игры Supercell на 9339), правило
  `{ "outboundTag":"proxy", "port":"9339" }` ловит его независимо от IP.

### Авторы

- **Nazar ([@CMAR4OK](https://github.com/CMAR4OK))** — идея, приобретение и тестирование
  оборудования и серверов, настройка и отладка на реальном железе.
- **Claude (Anthropic)** — помощь в написании кода, скриптов и документации.

### Благодарности

- [XTLS/Xray-core](https://github.com/XTLS/Xray-core) — ядро прокси (MPL-2.0).
- [Loyalsoldier/v2ray-rules-dat](https://github.com/Loyalsoldier/v2ray-rules-dat) — исходные geo-данные.
- [OpenWrt](https://openwrt.org/).

### Лицензия

MIT (скрипты/конфиги этого репо). Xray-core и geo-данные — под своими лицензиями.

### Дисклеймер

Только для законного использования (приватность, доступ к сервисам, на которые вы имеете право,
тесты собственной сети). Вы сами отвечаете за соблюдение применимых к вам законов и правил.

---

## 🇬🇧 English

Turn a small **OpenWrt** router into a transparent **VLESS (Xray)** VPN gateway with
**split-tunnel** routing: only the services you list go through your VPN server, everything
else stays direct (local speed, real IP). Works for **TCP and UDP** (games, voice) via TPROXY.

Originally built for a **Cudy WR3000** (MediaTek MT7981 / `aarch64`) on OpenWrt 25.12, but it
should work on any OpenWrt 24.10+/snapshot device with the `apk` package manager and the
`kmod-nft-tproxy` module available.

> You bring your own VLESS server (a `vless://` link). No keys are bundled in this repo.

### Features

- **Transparent proxy** for the whole LAN — no per-device setup.
- **Split tunnel**: a curated default list (Telegram, YouTube, Google, Instagram, Discord,
  WhatsApp, ChatGPT, Claude, Roblox, Clash Royale/Supercell, TikTok, …) routes through the VPN;
  everything else goes direct. Fully editable.
- **TCP + UDP** via nftables **TPROXY** (so game UDP and QUIC can be tunnelled).
- **Tiny on flash**: the Xray binary (~35 MB) lives in **RAM** and is downloaded from the
  official Xray-core GitHub release at every boot. Only a small config + minimal geo files
  (~40 KB) stay on flash.
- **Fail-open**: if the binary can't be fetched at boot, the internet still works (directly).
- Optional **GUI** to edit the routed list over SSH (`tools/vpn_manager.py`).

### How it works

```
LAN client ──▶ nftables TPROXY (mark, tcp+udp) ──▶ Xray dokodemo-door
                                                      │  (sniffs SNI / matches geo)
                          ┌───────────────────────────┤
            listed sites  ▼                           ▼  everything else
                    VLESS outbound ──▶ your server          direct (WAN)
```

DNS from the LAN is sent through the tunnel (anti-poisoning). IPv6 forwarding from the LAN is
dropped to avoid leaks (clients use IPv4). QUIC (UDP/443) is dropped so apps fall back to TCP,
which routes reliably by SNI — comment that one line out in `etc/init.d/xray` to tunnel QUIC.

### Requirements

- OpenWrt **24.10 / 25.x / snapshot** (uses the `apk` package manager).
- `kmod-nft-tproxy`, `kmod-nft-socket`, `unzip` available in the repo (installer adds them).
- Architecture: defaults to `aarch64` (`linux-arm64-v8a`). Others are auto-detected; if yours is
  exotic, set `XRAY_ARCH` in `/etc/xray/xray.conf` after install.
- Your own **VLESS** server (Reality or WS+TLS), as a `vless://` link.

### Install

On the router (SSH in as `root`):

```sh
cd /tmp
wget -O xr.tar.gz https://github.com/CMAR4OK/WR3000-v1-VLESS-VPN-Readdy-RU-/archive/refs/heads/main.tar.gz
tar xzf xr.tar.gz
cd WR3000-v1-VLESS-VPN-Readdy-RU--main

# run the installer (it will ask for your vless:// link)
sh install.sh
```

Paste your `vless://` link when asked. Verify with `logread -e xray`.

### Configure which sites use the VPN

Edit the routed lists in **`/etc/xray/config.json`** (`routing.rules`), then `/etc/init.d/xray restart`.

- Add a site: `"domain:example.com"` in the proxy `domain` rule.
- Add an IP/subnet: `"1.2.3.0/24"` in the proxy `ip` rule.
- `geosite:<cat>` / `geoip:<cat>` work only for categories in the bundled geo files. Regenerate
  with more via `geo/geofilter.py`.
- **All traffic through the VPN**: replace the whole `rules` array with a single rule
  `{ "type":"field", "outboundTag":"proxy", "network":"tcp,udp" }` (keep `dns-in -> proxy` first).

### Optional GUI (Windows)

`tools/vpn_manager.py` — a small Tkinter app to edit the domain/IP lists over SSH (uses PuTTY's
`plink.exe`). It validates the config (`xray -test`) before applying. No secrets stored — enter
your router IP/password in the app; the host key is fetched automatically.

### Change the VPN server / Xray version

Edit the `proxy` outbound in `/etc/xray/config.json` (or re-run `install.sh`). Xray version/arch
are in `etc/init.d/xray` and overridable in `/etc/xray/xray.conf`:

```sh
XRAY_VERSION="v26.3.27"
XRAY_ARCH="linux-arm64-v8a"
XRAY_SHA256=""               # optional: pin the unzipped binary's sha256
```

### Regenerate geo / Uninstall

```sh
python geo/geofilter.py list   geosite-full.dat                       # show categories
python geo/geofilter.py filter geosite-full.dat geo/geosite.dat "telegram,youtube,netflix"
sh uninstall.sh
```

### Limitations / notes

- **IPv6** is not tunnelled; LAN IPv6 forwarding is dropped to avoid leaks (clients are IPv4).
- DNS for the LAN goes through the VPN. Apps using DoH/encrypted DNS bypass this.
- Some apps use CDNs with **ECH** (encrypted SNI) — if a service half-works, add its CDN IP range
  to the proxy `ip` rule (find it via `logread -e xray` → `[transparent -> direct]`).
- This is **not** a DPI-bypass tool. Traffic goes through *your* VLESS server; the server bypasses
  blocks. Fixed-port apps (e.g. Supercell games on 9339) are caught by a `port` rule regardless of IP.

### Authors

- **Nazar ([@CMAR4OK](https://github.com/CMAR4OK))** — idea, bought & tested the hardware and
  servers, configuration and debugging on real devices.
- **Claude (Anthropic)** — code, scripts and documentation assistance.

### Credits / License / Disclaimer

[XTLS/Xray-core](https://github.com/XTLS/Xray-core) (MPL-2.0) ·
[Loyalsoldier/v2ray-rules-dat](https://github.com/Loyalsoldier/v2ray-rules-dat) (geo data) ·
[OpenWrt](https://openwrt.org/). MIT license for this repo's scripts/config. For lawful use only;
you are responsible for complying with the laws and terms that apply to you.
