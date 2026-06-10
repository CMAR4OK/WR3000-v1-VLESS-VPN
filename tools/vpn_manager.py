# -*- coding: utf-8 -*-
"""
xray-router VPN Manager — a small GUI to manage which sites/IPs go through the VPN
on your OpenWrt router, over SSH (via PuTTY's plink.exe on Windows, or `ssh`).

What it does:
  - connects to your router by SSH;
  - reads /etc/xray/config.json and shows the proxied DOMAINS and IPs;
  - lets you add / remove entries;
  - "Apply & Restart": validates the new config (xray -test) and only applies it
    if it is valid, then restarts Xray.

No secrets are stored in this file. On first run, enter your router IP / password;
the SSH host key is fetched and saved automatically. Settings are saved next to
this script in vpn_manager_settings.json.

Dependencies: Python 3 with tkinter (bundled with python.org installers) + plink.exe
(PuTTY) on Windows. On Linux/macOS set "plink" to "ssh" in the connection box.
"""

import json
import os
import queue
import re
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(APP_DIR, "vpn_manager_settings.json")

DEFAULT_SETTINGS = {
    "ip": "192.168.1.1",
    "user": "root",
    "password": "",
    "plink": r"C:\Program Files\PuTTY\plink.exe",
    "hostkey": "",
    "remote_config": "/etc/xray/config.json",
    "asset_dir": "/etc/xray",
    "xray_bin": "/tmp/xray",
}

# Categories present in the bundled minimal geo files (geo/geoip.dat, geo/geosite.dat).
GEOSITE_CATS = ["telegram", "youtube", "google", "instagram", "facebook", "discord", "openai"]
GEOIP_CATS = ["telegram", "facebook"]

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            s.update(json.load(f))
    except Exception:
        pass
    return s


def save_settings(s):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("settings save error:", e)


class Router:
    def __init__(self, settings):
        self.s = settings

    def _target(self):
        return f'{self.s["user"]}@{self.s["ip"]}'

    def fetch_hostkey(self):
        """Connect once in batch mode to learn the host key fingerprint."""
        args = [self.s["plink"], "-ssh", "-batch", "-pw", self.s["password"], self._target(), "echo ok"]
        try:
            r = subprocess.run(args, capture_output=True, timeout=20, creationflags=NO_WINDOW)
            out = (r.stdout + r.stderr).decode("utf-8", "replace")
        except Exception as e:
            return None, str(e)
        m = re.search(r"(SHA256:[A-Za-z0-9+/=]+)", out)
        if m:
            return m.group(1), None
        return None, out.strip() or "could not read host key"

    def run(self, remote_cmd, input_bytes=None, timeout=60):
        hk = self.s.get("hostkey", "").strip()
        base = [self.s["plink"], "-ssh", "-batch"]
        if hk:
            base += ["-hostkey", hk]
        base += ["-pw", self.s["password"], self._target(), remote_cmd]
        try:
            r = subprocess.run(base, input=input_bytes, capture_output=True,
                               timeout=timeout, creationflags=NO_WINDOW)
            return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            return 255, "", "TIMEOUT"
        except FileNotFoundError:
            return 255, "", f"plink not found: {self.s['plink']}"
        except Exception as e:
            return 255, "", str(e)

    def ensure_hostkey(self):
        if self.s.get("hostkey", "").strip():
            return True, None
        hk, err = self.fetch_hostkey()
        if hk:
            self.s["hostkey"] = hk
            save_settings(self.s)
            return True, hk
        return False, err

    def fetch_config(self):
        rc, out, err = self.run(f'cat {self.s["remote_config"]}')
        if rc != 0:
            raise RuntimeError(err or out or "could not read config")
        return json.loads(out)

    def push_file(self, remote_path, text):
        data = text.replace("\r\n", "\n").encode("utf-8")
        rc, out, err = self.run(f'cat > {remote_path}', input_bytes=data)
        if rc != 0:
            raise RuntimeError(err or "could not write file")

    def xray_test(self, remote_path):
        cmd = f'XRAY_LOCATION_ASSET={self.s["asset_dir"]} {self.s["xray_bin"]} -test -config {remote_path} 2>&1'
        return self.run(cmd, timeout=40)

    def apply_and_restart(self, tmp_path):
        cmd = (f'cp {tmp_path} {self.s["remote_config"]} && /etc/init.d/xray restart && sleep 7 && '
               f'(pidof xray >/dev/null && nft list table inet xray >/dev/null 2>&1 && echo APPLIED_OK || echo APPLY_PROBLEM)')
        return self.run(cmd, timeout=60)


def extract_lists(cfg):
    domains, ips = [], []
    for r in cfg.get("routing", {}).get("rules", []):
        if r.get("outboundTag") == "proxy" and "domain" in r:
            domains = list(r["domain"])
        if r.get("outboundTag") == "proxy" and "ip" in r and r.get("network") != "udp":
            ips = list(r["ip"])
    return domains, ips


def apply_lists(cfg, domains, ips):
    rules = cfg.setdefault("routing", {}).setdefault("rules", [])
    drule = irule = None
    for r in rules:
        if r.get("outboundTag") == "proxy" and "domain" in r:
            drule = r
        if r.get("outboundTag") == "proxy" and "ip" in r and r.get("network") != "udp":
            irule = r
    if domains:
        if drule is None:
            drule = {"type": "field", "outboundTag": "proxy", "domain": []}
            _insert_before_catchall(rules, drule)
        drule["domain"] = domains
    elif drule is not None:
        rules.remove(drule)
    if ips:
        if irule is None:
            irule = {"type": "field", "outboundTag": "proxy", "ip": []}
            _insert_before_catchall(rules, irule)
        irule["ip"] = ips
    elif irule is not None:
        rules.remove(irule)
    return cfg


def _insert_before_catchall(rules, new_rule):
    for i, r in enumerate(rules):
        if r.get("outboundTag") == "direct":
            rules.insert(i, new_rule)
            return
    rules.append(new_rule)


def normalize_domain(text):
    text = text.strip()
    if not text:
        return None
    if text.startswith(("geosite:", "domain:", "full:", "regexp:", "keyword:")):
        return text
    return "domain:" + text.lstrip("*.").lower()


def normalize_ip(text):
    return text.strip() or None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("xray-router — VPN list manager")
        self.geometry("900x640")
        self.minsize(820, 560)
        self.settings = load_settings()
        self.router = Router(self.settings)
        self.cfg = None
        self.q = queue.Queue()
        self._busy = False
        self._build_ui()
        self.after(150, self._poll_queue)

    def _build_ui(self):
        pad = {"padx": 6, "pady": 4}
        conn = ttk.LabelFrame(self, text="Router connection (SSH)")
        conn.pack(fill="x", **pad)
        self.var_ip = tk.StringVar(value=self.settings["ip"])
        self.var_user = tk.StringVar(value=self.settings["user"])
        self.var_pw = tk.StringVar(value=self.settings["password"])
        self.var_plink = tk.StringVar(value=self.settings["plink"])
        ttk.Label(conn, text="IP:").grid(row=0, column=0, sticky="e", **pad)
        ttk.Entry(conn, textvariable=self.var_ip, width=16).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(conn, text="User:").grid(row=0, column=2, sticky="e", **pad)
        ttk.Entry(conn, textvariable=self.var_user, width=12).grid(row=0, column=3, sticky="w", **pad)
        ttk.Label(conn, text="Password:").grid(row=0, column=4, sticky="e", **pad)
        self.ent_pw = ttk.Entry(conn, textvariable=self.var_pw, width=16, show="*")
        self.ent_pw.grid(row=0, column=5, sticky="w", **pad)
        self.var_showpw = tk.BooleanVar(value=False)
        ttk.Checkbutton(conn, text="show", variable=self.var_showpw, command=self._toggle_pw).grid(row=0, column=6, **pad)
        ttk.Label(conn, text="plink/ssh:").grid(row=1, column=0, sticky="e", **pad)
        ttk.Entry(conn, textvariable=self.var_plink, width=50).grid(row=1, column=1, columnspan=4, sticky="we", **pad)
        ttk.Button(conn, text="Test connection", command=self.on_test_conn).grid(row=1, column=5, columnspan=2, sticky="we", **pad)

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, **pad)
        mid.columnconfigure(0, weight=1); mid.columnconfigure(1, weight=1); mid.rowconfigure(0, weight=1)
        self.lb_domains, self.ent_domain = self._panel(mid, 0, "Domains / sites via VPN",
                                                       "site (e.g. netflix.com) or geosite:category",
                                                       self.on_add_domain, self.on_del_domain)
        self.lb_ips, self.ent_ip = self._panel(mid, 1, "IPs / subnets via VPN",
                                               "IP or CIDR (e.g. 1.2.3.0/24) or geoip:category",
                                               self.on_add_ip, self.on_del_ip)

        hint = ("geosite categories available: " + ", ".join(GEOSITE_CATS) +
                "\ngeoip categories available: " + ", ".join(GEOIP_CATS) +
                "\nPlain domains and IPs/CIDRs always work. (To add more geo categories, regenerate the geo files with geo/geofilter.py.)")
        ttk.Label(self, text=hint, foreground="#555", justify="left").pack(anchor="w", padx=12)

        bar = ttk.Frame(self); bar.pack(fill="x", **pad)
        ttk.Button(bar, text="Load from router", command=self.on_refresh).pack(side="left", padx=6)
        self.btn_apply = ttk.Button(bar, text="Apply & Restart", command=self.on_apply)
        self.btn_apply.pack(side="left", padx=6)
        self.status = ttk.Label(bar, text="ready", foreground="#0a0"); self.status.pack(side="right", padx=10)

        logf = ttk.LabelFrame(self, text="Log"); logf.pack(fill="both", expand=False, **pad)
        self.txt = tk.Text(logf, height=9, wrap="word", state="disabled", bg="#111", fg="#ddd", font=("Consolas", 9))
        self.txt.pack(fill="both", expand=True, padx=4, pady=4)

    def _panel(self, parent, col, title, ph, add_cb, del_cb):
        f = ttk.LabelFrame(parent, text=title)
        f.grid(row=0, column=col, sticky="nsew", padx=6, pady=4)
        f.rowconfigure(0, weight=1); f.columnconfigure(0, weight=1)
        lb = tk.Listbox(f, selectmode="extended", activestyle="none", font=("Consolas", 10))
        lb.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=4, pady=4)
        sb = ttk.Scrollbar(f, orient="vertical", command=lb.yview); sb.grid(row=0, column=2, sticky="ns")
        lb.config(yscrollcommand=sb.set)
        ent = ttk.Entry(f); ent.grid(row=1, column=0, sticky="we", padx=4, pady=4)
        ent.insert(0, ph); ent.config(foreground="#999")
        ent.bind("<FocusIn>", lambda e: self._clear_ph(ent, ph))
        ent.bind("<FocusOut>", lambda e: self._restore_ph(ent, ph))
        ent.bind("<Return>", lambda e: add_cb())
        btns = ttk.Frame(f); btns.grid(row=1, column=1, sticky="e", padx=4)
        ttk.Button(btns, text="+", width=3, command=add_cb).pack(side="left", padx=2)
        ttk.Button(btns, text="-", width=3, command=del_cb).pack(side="left", padx=2)
        ent._ph = ph
        return lb, ent

    def _clear_ph(self, ent, ph):
        if ent.get() == ph:
            ent.delete(0, "end"); ent.config(foreground="#000")

    def _restore_ph(self, ent, ph):
        if not ent.get().strip():
            ent.insert(0, ph); ent.config(foreground="#999")

    def _val(self, ent):
        v = ent.get().strip()
        return "" if v == ent._ph else v

    def _toggle_pw(self):
        self.ent_pw.config(show="" if self.var_showpw.get() else "*")

    def log(self, msg):
        self.txt.config(state="normal"); self.txt.insert("end", msg + "\n"); self.txt.see("end"); self.txt.config(state="disabled")

    def set_status(self, text, color="#0a0"):
        self.status.config(text=text, foreground=color)

    def _sync(self):
        self.settings["ip"] = self.var_ip.get().strip()
        self.settings["user"] = self.var_user.get().strip()
        self.settings["password"] = self.var_pw.get()
        self.settings["plink"] = self.var_plink.get().strip()
        save_settings(self.settings)
        self.router = Router(self.settings)

    def on_add_domain(self):
        v = normalize_domain(self._val(self.ent_domain))
        if v:
            if v not in self.lb_domains.get(0, "end"):
                self.lb_domains.insert("end", v)
            self.ent_domain.delete(0, "end")

    def on_del_domain(self):
        for i in reversed(self.lb_domains.curselection()):
            self.lb_domains.delete(i)

    def on_add_ip(self):
        v = normalize_ip(self._val(self.ent_ip))
        if v:
            if v not in self.lb_ips.get(0, "end"):
                self.lb_ips.insert("end", v)
            self.ent_ip.delete(0, "end")

    def on_del_ip(self):
        for i in reversed(self.lb_ips.curselection()):
            self.lb_ips.delete(i)

    def _run_bg(self, fn):
        if self._busy:
            return
        self._busy = True
        self.btn_apply.config(state="disabled")
        self.set_status("working...", "#a60")
        threading.Thread(target=fn, daemon=True).start()

    def _done(self):
        self.q.put(("_done", None))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "status":
                    self.set_status(*payload)
                elif kind == "fill":
                    self._fill(*payload)
                elif kind == "_done":
                    self._busy = False
                    self.btn_apply.config(state="normal")
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def _fill(self, domains, ips):
        self.lb_domains.delete(0, "end")
        for d in domains:
            self.lb_domains.insert("end", d)
        self.lb_ips.delete(0, "end")
        for ip in ips:
            self.lb_ips.insert("end", ip)

    def _prep(self):
        ok, info = self.router.ensure_hostkey()
        if not ok:
            self.q.put(("log", "Could not get host key: " + str(info)))
            return False
        if info is not True and info:
            self.q.put(("log", "Saved router host key: " + str(info)))
        return True

    def on_test_conn(self):
        self._sync()
        def work():
            self.q.put(("log", "Connecting..."))
            if not self._prep():
                self.q.put(("status", ("no connection", "#c00"))); self._done(); return
            rc, out, err = self.router.run("echo OK")
            if rc == 0 and "OK" in out:
                self.q.put(("log", "Connected OK.")); self.q.put(("status", ("connected", "#0a0")))
            else:
                self.q.put(("log", "Error: " + (err or out).strip())); self.q.put(("status", ("no connection", "#c00")))
            self._done()
        self._run_bg(work)

    def on_refresh(self):
        self._sync()
        def work():
            self.q.put(("log", "Reading config..."))
            try:
                if not self._prep():
                    self.q.put(("status", ("error", "#c00"))); self._done(); return
                cfg = self.router.fetch_config()
                self.cfg = cfg
                d, ips = extract_lists(cfg)
                self.q.put(("fill", (d, ips)))
                self.q.put(("log", f"Loaded: {len(d)} domains, {len(ips)} IP entries."))
                self.q.put(("status", ("loaded", "#0a0")))
            except Exception as e:
                self.q.put(("log", "Load failed: " + str(e))); self.q.put(("status", ("error", "#c00")))
            self._done()
        self._run_bg(work)

    def on_apply(self):
        self._sync()
        if self.cfg is None:
            messagebox.showwarning("No config", "Press 'Load from router' first.")
            return
        domains = list(self.lb_domains.get(0, "end"))
        ips = list(self.lb_ips.get(0, "end"))
        if not messagebox.askyesno("Apply?", f"Apply and restart Xray?\n\nDomains: {len(domains)}\nIP entries: {len(ips)}\n\nThe config is validated (xray -test) before applying."):
            return
        def work():
            try:
                cfg = json.loads(json.dumps(self.cfg))
                apply_lists(cfg, domains, ips)
                text = json.dumps(cfg, indent=2, ensure_ascii=False)
                self.q.put(("log", "Uploading temp config..."))
                self.router.push_file("/tmp/config.new.json", text)
                self.q.put(("log", "Validating (xray -test)..."))
                rc, out, err = self.router.xray_test("/tmp/config.new.json")
                if "Configuration OK" not in out:
                    self.q.put(("log", "INVALID — not applied:\n" + ("\n".join(out.strip().splitlines()[-4:]) or err)))
                    self.q.put(("status", ("invalid config", "#c00"))); self._done(); return
                self.q.put(("log", "Valid. Applying + restarting..."))
                rc, out, err = self.router.apply_and_restart("/tmp/config.new.json")
                if "APPLIED_OK" in out:
                    self.cfg = cfg
                    self.q.put(("log", "Applied. Xray running, redirect active."))
                    self.q.put(("status", ("applied", "#0a0")))
                else:
                    self.q.put(("log", "Restart done but check failed:\n" + (out or err).strip()))
                    self.q.put(("status", ("check log", "#a60")))
            except Exception as e:
                self.q.put(("log", "Apply error: " + str(e))); self.q.put(("status", ("error", "#c00")))
            self._done()
        self._run_bg(work)


if __name__ == "__main__":
    App().mainloop()
