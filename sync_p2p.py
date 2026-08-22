#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_motor v1.7.0 — P2P Mesh senkron
Çok noktadan çok noktaya: H1 ⇄ H2 ⇄ H3 doğrudan Tailscale üzerinden.
GitHub/GDrive merkez + P2P doğrudan kanal (3 kanal).
"""
import json, os, sys, subprocess, socket, time, hashlib, urllib.request

CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_cfg():
    return json.load(open(CFG))

def save_cfg(cfg):
    json.dump(cfg, open(CFG, "w"), indent=1, ensure_ascii=False)

# --- Makine keşfi (Tailscale MagicDNS) ---
def detect_machine():
    """Hostname'den makine kimliği: h1/h2/h3/openclaw"""
    host = socket.gethostname().lower()
    cfg = load_cfg()
    machines = cfg.get("machines", {})
    for mid, names in machines.items():
        for n in names:
            if n.lower() in host or host in n.lower():
                return mid.replace("_hostnames", "")
    return "unknown"

def list_peers():
    """Tailscale peers — diğer makinelerin IP'leri"""
    try:
        r = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return {}
        d = json.loads(r.stdout)
        peers = {}
        for pid, p in d.get("Peer", {}).items():
            name = p.get("HostName", "")
            addrs = p.get("TailscaleIPs", [])
            if addrs:
                peers[name.lower()] = addrs[0]
        return peers
    except Exception as e:
        return {}

# --- P2P transfer (doğrudan makineden makineye) ---
def p2p_status(cfg):
    """Tüm makinelerin durum matrisi"""
    me = detect_machine()
    peers = list_peers()
    out = []
    out.append(f"=== P2P MESH DURUMU (bu makine: {me}) ===")
    out.append(f"Bilinmeyen makine: {me == 'unknown'}")
    for name, ip in sorted(peers.items()):
        # HTTP 9090 kontrol
        try:
            r = urllib.request.urlopen(f"http://{ip}:9090/health", timeout=3)
            status = f"UP ({r.status})"
        except:
            status = "DOWN"
        out.append(f"  {name} ({ip}): {status}")
    return "\n".join(out)

def p2p_pull(cfg, node, src_machine=None):
    """Doğrudan kaynak makineden node çek (HTTP 9090 üzerinden)"""
    peers = list_peers()
    me = detect_machine()
    if not peers:
        return "HATA: Tailscale peer yok (tailscale up gerekli)"
    
    # Hedef makine seçimi: src_machine veya ilk UP peer
    if src_machine:
        ip = peers.get(src_machine.lower())
        if not ip:
            return f"HATA: {src_machine} bulunamadı (peers: {list(peers.keys())})"
    else:
        # İlk ulaşılabilir peer
        ip = None
        for name, addr in peers.items():
            try:
                urllib.request.urlopen(f"http://{addr}:9090/health", timeout=3)
                ip = addr
                break
            except:
                continue
        if not ip:
            return "HATA: Ulaşılabilir peer yok"
    
    dirs = cfg.get("dirs", {})
    if node not in dirs:
        return f"HATA: node '{node}' yok (mevcut: {list(dirs.keys())})"
    
    node_cfg = dirs[node]
    dest = node_cfg["path"]
    os.makedirs(dest, exist_ok=True)
    
    # Uzak makineden dosya listesi iste
    try:
        url = f"http://{ip}:9090/sync/{node}/list"
        r = urllib.request.urlopen(url, timeout=5)
        files = json.loads(r.read())
        out = [f"P2P pull: {node} ← {ip} ({len(files)} dosya)"]
        pulled = 0
        for fname in files:
            fpath = os.path.join(dest, fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            try:
                fr = urllib.request.urlopen(f"http://{ip}:9090/sync/{node}/get?f={fname}", timeout=30)
                data = fr.read()
                with open(fpath, "wb") as f:
                    f.write(data)
                pulled += 1
            except Exception as e:
                out.append(f"  ✗ {fname}: {e}")
        out.append(f"✅ {pulled}/{len(files)} dosya çekildi")
        return "\n".join(out)
    except Exception as e:
        return f"HATA: {e}"

# --- H3 config güncelleme ---
def add_h3(cfg):
    """config.json'a h3_hostnames ekle"""
    machines = cfg.setdefault("machines", {})
    if "h3_hostnames" not in machines:
        machines["h3_hostnames"] = ["H3-LOCAL-HERMES"]
    # network'e h3 ekle
    net = cfg.setdefault("network", {})
    if "h3_http" not in net:
        net["h3_http"] = "http://100.96.0.1:9090"  # placeholder — Tailscale IP sonra
    save_cfg(cfg)
    return "✅ h3_hostnames + h3_http eklendi (Tailscale IP güncellenecek)"

if __name__ == "__main__":
    args = sys.argv[1:]
    cfg = load_cfg()
    if not args:
        print(__doc__)
        sys.exit(0)
    cmd = args[0]
    if cmd == "mesh":
        print(p2p_status(cfg))
    elif cmd == "p2p-pull" and len(args) >= 2:
        node = args[1]
        src = args[2] if len(args) > 2 else None
        print(p2p_pull(cfg, node, src))
    elif cmd == "add-h3":
        print(add_h3(cfg))
    elif cmd == "me":
        print(detect_machine())
    elif cmd == "peers":
        print(json.dumps(list_peers(), indent=1))
    else:
        print(f"Bilinmeyen: {cmd}")
        print("Kullanım: mesh | p2p-pull <node> [makine] | add-h3 | me | peers")
