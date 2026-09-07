#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VLESS Reality subscription manager — shared core logic.

Used by both the CLI (`vpn`) and the TUI (`vpntui.py`). Fetches a VLESS
subscription, lists nodes, tests latency / exit country / download speed
through each node, and switches the global sing-box TUN VPN.
"""
import base64
import concurrent.futures
import copy
import datetime
import ipaddress
import json
import os
import socket
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

HOME = os.path.expanduser("~")
DIR = os.path.dirname(os.path.abspath(__file__))

SUB_URL_FILE = os.path.join(DIR, "sub_url")
RAW_FILE = os.path.join(DIR, "cache", "sub.raw")
DEC_FILE = os.path.join(DIR, "cache", "sub.txt")
NODES_FILE = os.path.join(DIR, "cache", "nodes.json")
RESULTS_FILE = os.path.join(DIR, "cache", "results.json")
HISTORY_FILE = os.path.join(DIR, "cache", "history.jsonl")
AUTOCHECK_LOG = os.path.join(DIR, "cache", "autocheck.log")

SINGBOX = "/usr/local/bin/sing-box"
ETC_CFG = "/etc/sing-box/config.json"
SUDO_PASS = os.path.join(HOME, ".sudo_password")

SOCKS_PORT = 10880
TEST_PORT_BASE = 10800          # per-node socks ports for parallel tests
TEST_URL_IP = "https://ipinfo.io/json"   # returns {ip,country,city}
SPEED_URL = "https://speed.cloudflare.com/__down?bytes=10485760"  # 10 MB


# ---------------------------------------------------------------- helpers
def log(msg):
    sys.stderr.write(msg.rstrip("\n") + "\n")
    sys.stderr.flush()


def sudo(args, stdin=None):
    if stdin is None and os.path.isfile(SUDO_PASS):
        with open(SUDO_PASS) as f:
            stdin = f.read().strip() + "\n"
    return subprocess.run(
        ["sudo", "-S"] + args,
        input=(stdin or "").encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def curl_proxy(port, url, timeout=12):
    """Curl through a local socks5 proxy; returns (exit_code, body_or_err)."""
    p = subprocess.run(
        ["curl", "-s", "-x", "socks5h://127.0.0.1:%d" % port,
         "--max-time", str(timeout), url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, (p.stdout or b"").decode("utf-8", "replace")


def read_url():
    if not os.path.isfile(SUB_URL_FILE):
        log("Файл sub_url не найден в %s" % SUB_URL_FILE)
        sys.exit(1)
    with open(SUB_URL_FILE) as f:
        return f.read().strip()


# ---------------------------------------------------------------- subscription
def fetch_subscription():
    url = read_url()
    log("Скачиваю подписку: %s ..." % url)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            raw = r.read()
    except Exception as e:
        log("Ошибка загрузки подписки: %s" % e)
        sys.exit(1)
    os.makedirs(os.path.dirname(RAW_FILE), exist_ok=True)
    with open(RAW_FILE, "wb") as f:
        f.write(raw)
    text = None
    try:
        decoded = base64.b64decode(raw.strip()).decode("utf-8", "replace")
        if "vless://" in decoded:
            text = decoded
    except Exception:
        pass
    if text is None:
        text = raw.decode("utf-8", "replace")
    with open(DEC_FILE, "w") as f:
        f.write(text)
    return text


def parse_nodes(text):
    nodes = []
    for idx, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line.startswith("vless://"):
            continue
        p = urllib.parse.urlparse(line)
        q = urllib.parse.parse_qs(p.query)
        host = p.hostname
        port = p.port or 443
        name = urllib.parse.unquote(p.fragment or "")
        nodes.append({
            "uuid": p.username or "",
            "host": host,
            "port": int(port),
            "flow": q.get("flow", ["xtls-rprx-vision"])[0],
            "sni": q.get("sni", [host])[0],
            "fp": q.get("fp", ["chrome"])[0],
            "pbk": q.get("pbk", [""])[0],
            "sid": q.get("sid", [""])[0],
            "name": name,
            "tag": "s%d" % idx,
        })
    return nodes


def load_nodes(refresh=False):
    if refresh or not os.path.isfile(NODES_FILE):
        text = fetch_subscription()
        nodes = parse_nodes(text)
        with open(NODES_FILE, "w") as f:
            json.dump(nodes, f, ensure_ascii=False, indent=2)
    else:
        with open(NODES_FILE) as f:
            nodes = json.load(f)
    return nodes


def load_results():
    if os.path.isfile(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {}


def save_results(results):
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


def record_history(node, res):
    """Append one test datapoint to the rolling history log (jsonl)."""
    rec = {
        "ts": int(time.time()),
        "host": node["host"],
        "port": node["port"],
        "name": node.get("name", ""),
        "country": res.get("country"),
        "exit_ip": res.get("exit_ip"),
        "exit_ms": res.get("exit_ms"),
        "speed_mbps": res.get("speed_mbps"),
    }
    try:
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_history():
    if not os.path.isfile(HISTORY_FILE):
        return []
    out = []
    with open(HISTORY_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def best_node_index(nodes, results):
    """Pick the best working non-RU node. Prefer measured speed, then latency.

    Returns (index, results_dict) or (None, None) if no working foreign node.
    """
    best, best_key = None, None
    for i, n in enumerate(nodes):
        r = results.get(node_key(n), {})
        if not r.get("exit_ip") or r.get("country") == "RU":
            continue
        speed = r.get("speed_mbps")
        lat = r.get("exit_ms")
        if speed is None and lat is None:
            continue
        key = (0 if speed is not None else 1, -(speed or 0),
               lat if lat is not None else 10 ** 9)
        if best_key is None or key < best_key:
            best_key, best = key, i
    if best is None:
        return None, None
    return best, results.get(node_key(nodes[best]), {})


def node_key(node):
    return "%s:%d" % (node["host"], node["port"])


# ---------------------------------------------------------------- tests
def is_ip(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def resolve_ip(node):
    """Resolve node host to an IPv4 address (for route exclusion)."""
    if is_ip(node["host"]):
        return node["host"]
    try:
        return socket.gethostbyname(node["host"])
    except Exception:
        return node["host"]


def handshake_ms(node, timeout=2.5):
    """Quick TCP latency to the server itself."""
    t0 = time.time()
    try:
        with socket.create_connection((node["host"], node["port"]), timeout=timeout):
            return round((time.time() - t0) * 1000)
    except Exception:
        return None


def node_outbound_json(node):
    return {
        "type": "vless",
        "tag": node.get("tag") or "srv_%s_%d" % (node["host"], node["port"]),
        "server": node["host"],
        "server_port": node["port"],
        "uuid": node["uuid"],
        "flow": node["flow"],
        "tls": {
            "enabled": True,
            "server_name": node["sni"],
            "utls": {"enabled": True, "fingerprint": node["fp"]},
            "reality": {"enabled": True, "public_key": node["pbk"],
                        "short_id": node["sid"]},
        },
    }


def run_singbox(cfg, workdir, name="_tmp_cfg.json"):
    """Start sing-box with given config (no TUN), return Popen."""
    cfgfile = os.path.join(workdir, name)
    with open(cfgfile, "w") as f:
        json.dump(cfg, f)
    devnull = open(os.devnull, "w")
    p = subprocess.Popen([SINGBOX, "run", "-c", cfgfile],
                         stdout=devnull, stderr=subprocess.PIPE,
                         cwd=workdir)
    return p


def stop_singbox(p):
    try:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
    except Exception:
        pass


def full_test(node, port=SOCKS_PORT, timeout=12):
    """Start a socks sing-box for the node, measure exit country/IP and exit
    latency. Returns dict or None."""
    cfgfile = "_tmp_cfg_%d.json" % port
    cfg = {
        "log": {"level": "error"},
        "inbounds": [{"type": "socks", "listen": "127.0.0.1",
                      "listen_port": port}],
        "outbounds": [node_outbound_json(node)],
    }
    p = run_singbox(cfg, DIR, name=cfgfile)
    try:
        time.sleep(2)
        t0 = time.time()
        rc, body = curl_proxy(port, TEST_URL_IP, timeout=timeout)
        exit_ms = round((time.time() - t0) * 1000) if rc == 0 and body else None
        info = {}
        try:
            info = json.loads(body)
        except Exception:
            pass
        if not info or "ip" not in info:
            return None
        return {
            "exit_ip": info.get("ip"),
            "country": info.get("country"),
            "city": info.get("city"),
            "exit_ms": exit_ms,
        }
    finally:
        stop_singbox(p)
        try:
            os.remove(os.path.join(DIR, cfgfile))
        except OSError:
            pass


def speed_test(node, port=SOCKS_PORT, timeout=30):
    """Download speed through the node (Mbps)."""
    cfgfile = "_tmp_cfg_%d.json" % port
    cfg = {
        "log": {"level": "error"},
        "inbounds": [{"type": "socks", "listen": "127.0.0.1",
                      "listen_port": port}],
        "outbounds": [node_outbound_json(node)],
    }
    p = run_singbox(cfg, DIR, name=cfgfile)
    try:
        time.sleep(2)
        t0 = time.time()
        rc, body = curl_proxy(port, SPEED_URL, timeout=timeout)
        dt = time.time() - t0
        if rc != 0 or dt <= 0:
            return None
        mbps = round(10.0 * 8 / dt, 1)
        return {"speed_mbps": mbps, "speed_ms": round(dt * 1000)}
    finally:
        stop_singbox(p)
        try:
            os.remove(os.path.join(DIR, cfgfile))
        except OSError:
            pass


# ---------------------------------------------------------------- apply
def base_config():
    """Start from current live config to keep tun/dns/route settings."""
    try:
        with open(ETC_CFG) as f:
            base = json.load(f)
        return base
    except Exception:
        return None


def build_global_config(nodes, final, auto_tags=None):
    base = base_config()
    if base is None:
        base = {
            "log": {"level": "info", "timestamp": True},
            "inbounds": [{
                "type": "tun", "tag": "tun0", "interface_name": "tun0",
                "mtu": 1500, "address": ["172.19.0.1/30"],
                "auto_route": True, "strict_route": True, "stack": "system",
            }],
            "dns": {"servers": [{"type": "https", "server": "1.1.1.1",
                                 "tag": "dn"}]},
            "route": {"auto_detect_interface": True, "rules": [], "final": ""},
        }
    cfg = copy.deepcopy(base)

    for i, n in enumerate(nodes):
        n["tag"] = "n%d" % i
    outbounds = [{"type": "direct", "tag": "direct"}]
    for n in nodes:
        outbounds.append(node_outbound_json(n))
    cfg["outbounds"] = outbounds

    route = cfg.get("route", {})
    if "rules" not in route:
        route["rules"] = []
    has_private = any(
        r.get("ip_cidr") and "192.168.0.0/16" in r["ip_cidr"]
        for r in route["rules"])
    if not has_private:
        route["rules"].insert(0, {
            "ip_cidr": ["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12",
                        "127.0.0.0/8", "169.254.0.0/16"],
            "outbound": "direct",
        })
    route["auto_detect_interface"] = True

    if final == "auto":
        route["final"] = "auto"
        tags = auto_tags or ["n%d" % i for i in range(len(nodes))]
        if not tags:
            tags = ["n%d" % i for i in range(len(nodes))]
        if not any(o.get("type") == "urltest" for o in cfg["outbounds"]):
            cfg["outbounds"].append({
                "type": "urltest", "tag": "auto",
                "outbounds": tags,
                "interval": "1m",
            })
    else:
        route["final"] = final
        cfg["outbounds"] = [o for o in cfg["outbounds"]
                            if o.get("tag") != "auto"]

    tun = cfg["inbounds"][0]
    excludes = ["%s/32" % resolve_ip(n) for n in nodes]
    tun["route_exclude_address"] = excludes

    cfg["route"] = route
    return cfg


def apply_node(nodes, selection, results=None):
    results = results or {}
    if selection == "auto":
        final = "auto"
        label = "auto (лучший из зарубежных)"
        auto_tags = []
        for i, n in enumerate(nodes):
            r = results.get(node_key(n), {})
            if r.get("exit_ip") and r.get("country") != "RU":
                auto_tags.append("n%d" % i)
    elif selection == "best":
        idx, r = best_node_index(nodes, results)
        if idx is None:
            log("Нет рабочих зарубежных узлов в results.json — сначала: "
                "vpn test all")
            return False
        final = "n%d" % idx
        label = "#%d %s (best)" % (idx, short_name(nodes[idx]))
        auto_tags = None
    else:
        idx = int(selection)
        final = "n%d" % idx
        label = "#%d %s" % (idx, short_name(nodes[idx]))
        auto_tags = None
    log("Собираю конфиг с узлом: %s" % label)
    cfg = build_global_config(nodes, final, auto_tags)

    tmp = os.path.join(DIR, "_apply.json")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    r = sudo(["cp", tmp, ETC_CFG])
    if r.returncode != 0:
        log("Ошибка записи конфига: %s" % r.stderr.decode())
        return False
    log("Перезапускаю sing-box...")
    sudo(["systemctl", "restart", "sing-box"])
    time.sleep(4)
    st = subprocess.run(["systemctl", "is-active", "sing-box"],
                        stdout=subprocess.PIPE).stdout.decode().strip()
    if st != "active":
        log("sing-box не активен! Откат: включаю авто из бекапа")
        sudo(["cp", os.path.join(DIR, "configs", "singbox-last.json"), ETC_CFG])
        sudo(["systemctl", "restart", "sing-box"])
        return False
    egress = None
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
            egress = r.read().decode().strip()
    except Exception:
        pass
    log("VPN активен (final=%s), egress IP: %s" % (final, egress))
    with open(os.path.join(DIR, "configs", "singbox-last.json"), "w") as f:
        json.dump(cfg, f, indent=2)
    return True


def vpn_enabled():
    st = subprocess.run(["systemctl", "is-active", "sing-box"],
                        stdout=subprocess.PIPE).stdout.decode().strip()
    return st == "active"


def set_vpn_enabled(on):
    """Start/stop the sing-box service. Returns the new active state."""
    action = "start" if on else "stop"
    sudo(["systemctl", action, "sing-box"])
    time.sleep(3 if on else 1)
    return vpn_enabled()


# ---------------------------------------------------------------- display
def disp_width(s):
    """Display width of a string (wide chars count as 2)."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in s)


def fit(s, w):
    """Truncate s to display width w and pad with spaces to exactly w."""
    out, width = [], 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if width + cw > w:
            break
        out.append(c)
        width += cw
    return "".join(out) + " " * (w - width)


def short_name(node):
    base = node.get("name") or ""
    if base:
        base = " ".join(base.split())
        if len(base) > 40:
            base = base[:39] + "…"
    return base or "%s:%d" % (node["host"], node["port"])


def print_table(nodes, results=None):
    results = results or {}
    print("\n%-3s %-24s %-6s %-22s %-9s %-8s %-9s" %
          ("#", "имя/узел", "порт", "host", "handshake", "exit", "ms"))
    print("-" * 90)
    for i, n in enumerate(nodes):
        r = results.get(node_key(n), {})
        hs = r.get("handshake_ms")
        exit_ms = r.get("exit_ms")
        country = r.get("country") or ""
        col = "OK" if hs is not None else "-"
        hs_s = ("%dms" % hs) if hs is not None else "  ✗"
        if exit_ms is not None:
            ex = "%s %s" % (country, exit_ms)
        else:
            ex = ""
        print("%-3d %s %-6d %s %-9s %-8.8s %s" %
              (i, fit(short_name(n), 24), n["port"],
               fit(n["host"], 22), hs_s, col, ex))
    print()


# ---------------------------------------------------------------- commands
def cmd_refresh(nodes):
    log("Обновляю подписку...")
    nodes = load_nodes(refresh=True)
    log("Узлов в подписке: %d" % len(nodes))
    return nodes


def get_status(nodes):
    """Return a dict with sing-box active state, current target and egress."""
    st = subprocess.run(["systemctl", "is-active", "sing-box"],
                        stdout=subprocess.PIPE).stdout.decode().strip()
    target = "?"
    final = ""
    r = sudo(["cat", ETC_CFG])
    if r.returncode == 0:
        try:
            cfg = json.loads(r.stdout.decode("utf-8", "replace"))
            final = cfg.get("route", {}).get("final") or ""
            if final == "auto":
                target = "auto"
            elif final.startswith("n") and final[1:].isdigit():
                idx = int(final[1:])
                target = ("#%d %s" % (idx, short_name(nodes[idx]))
                          if idx < len(nodes) else final)
            elif final:
                target = final
        except Exception:
            pass
    egress, country = "n/a", ""
    try:
        info = json.loads(urllib.request.urlopen(
            "https://ipinfo.io/json", timeout=5).read().decode())
        egress = info.get("ip") or "n/a"
        country = info.get("country") or ""
    except Exception:
        pass
    return {"active": st, "target": target, "egress": egress,
            "country": country, "final": final}


def cmd_status(nodes, results):
    s = get_status(nodes)
    print("sing-box: %s" % s["active"])
    print("target: %s" % s["target"])
    print("egress: %s  country=%s" % (s["egress"], s["country"]))


def cmd_history(nodes, results, n=30):
    hist = load_history()
    if not hist:
        print("История пуста. Запусти 'vpn test all'.")
        return
    idx_by_key = {node_key(node): i for i, node in enumerate(nodes)}
    name_by_key = {node_key(node): short_name(node) for node in nodes}
    print("\nПоследние %d тестов (всего в истории: %d):"
          % (min(n, len(hist)), len(hist)))
    print("%-4s %-24s %-8s %-16s %-8s %-7s %s" %
          ("#", "узел", "country", "exit_ip", "ms", "speed", "время"))
    print("-" * 96)
    for rec in hist[-n:]:
        k = "%s:%d" % (rec["host"], rec["port"])
        idx = idx_by_key.get(k)
        name = name_by_key.get(k, rec.get("name", k))
        spd = ("%sM" % rec["speed_mbps"]) if rec.get("speed_mbps") else ""
        ts = datetime.datetime.fromtimestamp(rec["ts"]).strftime(
            "%m-%d %H:%M:%S")
        print("%-4s %-24.24s %-8s %-16s %-8s %-7s %s" %
              (("#%d" % idx) if idx is not None else "-", name,
               rec.get("country") or "-", rec.get("exit_ip") or "-",
               rec.get("exit_ms") or "-", spd, ts))
    print()


def cmd_autocheck(nodes, results, jobs=6):
    """Periodic health check: re-test nodes and recover to a working foreign
    node if the current egress degraded. Returns True on success."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log("[%s] autocheck: полный тест узлов" % ts)
    results = cmd_full_test(nodes, results, "all", jobs=jobs)

    cur = None
    try:
        info = json.loads(urllib.request.urlopen(
            "https://ipinfo.io/json", timeout=8).read().decode())
        cur = info.get("country")
    except Exception:
        cur = None
    log("[%s] текущий egress country: %s" % (ts, cur))

    if cur != "RU" and cur is not None:
        log("[%s] egress в норме, оставляю как есть" % ts)
        return True

    log("[%s] egress деградировал — восстанавливаю (auto)" % ts)
    if apply_node(nodes, "auto", results):
        log("[%s] переключён на auto" % ts)
        return True
    log("[%s] auto не удался — пробую best" % ts)
    if apply_node(nodes, "best", results):
        log("[%s] переключён на best" % ts)
        return True
    log("[%s] восстановление не удалось" % ts)
    return False


def cmd_cron(action):
    marker = os.path.join(DIR, "vpn") + " autocheck"
    cur = ""
    try:
        cur = subprocess.run(["crontab", "-l"], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE).stdout.decode()
    except Exception:
        cur = ""
    lines = [l for l in cur.splitlines() if l.strip() and marker not in l]
    if action == "install":
        lines.append("0 * * * * %s >> %s 2>&1" %
                     (os.path.join(DIR, "vpn") + " autocheck", AUTOCHECK_LOG))
        msg = "cron установлен: авто-проверка каждый час"
    elif action == "remove":
        msg = "cron autocheck удалён"
    else:
        log("используй: vpn cron [install|remove]")
        return
    p = subprocess.run(["crontab", "-"],
                       input=("\n".join(lines) + "\n").encode(),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        log("Ошибка crontab: %s" % p.stderr.decode())
        return
    log(msg)


def cmd_ping_all(nodes, results):
    print("Проверяю TCP handshake до каждого сервера...")
    for i, n in enumerate(nodes):
        r = results.setdefault(node_key(n), {})
        ms = handshake_ms(n)
        r["handshake_ms"] = ms
        mark = "%dms" % ms if ms is not None else "✗ unreachable"
        log("  #%d %-24s %s" % (i, short_name(n), mark))
    save_results(results)
    return results


def cmd_full_test(nodes, results, which, jobs=6):
    idxs = list(range(len(nodes))) if which in ("all", None) else [int(which)]
    log("Тестирую %d узел(ов) параллельно (%d потоков)..."
        % (len(idxs), jobs))

    def worker(i):
        n = nodes[i]
        res = full_test(n, port=TEST_PORT_BASE + i)
        return i, res

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(worker, i): i for i in idxs}
        for fut in concurrent.futures.as_completed(futs):
            i, res = fut.result()
            n = nodes[i]
            r = results.setdefault(node_key(n), {})
            if res is None:
                r["exit_ip"] = None
                r["country"] = None
                r["exit_ms"] = None
                log("  #%d %-24s ✗ не работает (reality/нет сети)"
                    % (i, short_name(n)))
            else:
                r.update(res)
                record_history(n, res)
                log("  #%d %-24s ✓ выход %s %s, %dms" %
                    (i, short_name(n), res.get("country"),
                     res.get("exit_ip"), res.get("exit_ms")))
    save_results(results)
    return results


def cmd_speed(nodes, results, which):
    i = int(which)
    n = nodes[i]
    log("Speedtest через узел #%d %s (10 MB)..." % (i, short_name(n)))
    res = speed_test(n, port=TEST_PORT_BASE + i)
    r = results.setdefault(node_key(n), {})
    if res is None:
        log("  ✗ скорость не измерилась")
        r["speed_mbps"] = None
    else:
        r.update(res)
        record_history(n, res)
        log("  ✓ %s Mbps за %s ms" % (res["speed_mbps"], res["speed_ms"]))
    save_results(results)
