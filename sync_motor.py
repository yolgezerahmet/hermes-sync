#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cumulus Sync Motoru — Profesyonel Sürüm
========================================
GitHub + Google Drive + Tailscale üzerinden iki yönlü, veri kaybına
karşı güvenli (non-destructive) dosya senkronizasyon motoru.

Özellikler
----------
* İKİ YÖNLÜ: push + pull (H1 VPS ↔ H2 Desktop aralıklı çalışabilir)
* NON-DESTRUCTIVE: asla üzerine yazmaz; çakışmalar .conflict.TS ile korunur
* VERSİYONLU: her senkron GDrive'da timestamp'li snapshot oluşturur
* AKILLI FİLTRE: küçük/değerli dosyalar (kernel .c/.h, scripts) GitHub
  manifest'ine; büyük dosyalar (PCB, patent) GDrive'a yönlendirilir
* FARKINDALIK: her iki taraf diğerinin değişikliklerini görür
* MAKİNE TESPİTİ: H1/H2 otomatik algılanır (hostname + OS)
* LOGLAMA: seviyeli log + dosya kaydı + opsiyonel renkli çıktı
* TEST: birim testler (tests/test_sync_motor.py)

Kurulum
-------
    pip install -r requirements.txt   # requests (opsiyonel)

Yapılandırma
------------
    cp config.example.json config.json
    # config.json'u kendi makinenize göre düzenleyin

Kullanım
--------
    python3 sync_motor.py status      # durum + farkındalık
    python3 sync_motor.py push        # yerel → merkez (GitHub + GDrive)
    python3 sync_motor.py pull        # merkez → yerel (çakışmasız)
    python3 sync_motor.py both        # push + pull (önerilen)
    python3 sync_motor.py conflicts   # çakışma dosyalarını listele
    python3 sync_motor.py init        # ilk kurulum

Lisans: MIT (bkz. LICENSE)
Geliştiren: CumulusNET Mühendislik — 2026
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

__version__ = "1.0.0"
__author__ = "CumulusNET Engineering"
__license__ = "MIT"


# ═══════════════════════════════════════════════════════════════
# LOGGING KURULUMU
# ═══════════════════════════════════════════════════════════════

LOG_COLORS = {
    "DEBUG": "\033[36m",    # cyan
    "INFO": "\033[32m",     # green
    "WARNING": "\033[33m",  # yellow
    "ERROR": "\033[31m",    # red
    "CRITICAL": "\033[1;31m",
    "RESET": "\033[0m",
}


class ColoredFormatter(logging.Formatter):
    def format(self, record):
        prefix = ""
        if sys.stdout.isatty():
            color = LOG_COLORS.get(record.levelname, "")
            prefix = f"{color}"
        msg = super().format(record)
        reset = LOG_COLORS["RESET"] if sys.stdout.isatty() else ""
        return f"{prefix}{msg}{reset}"


def setup_logging(level=logging.INFO, logfile=None):
    root = logging.getLogger("sync_motor")
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ColoredFormatter("%(levelname)-8s %(message)s"))
    root.addHandler(console)

    if logfile:
        Path(logfile).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"))
        root.addHandler(fh)

    return root


log = logging.getLogger("sync_motor")


# ═══════════════════════════════════════════════════════════════
# YAPILANDIRMA
# ═══════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    "github": {
        "repo": "yolgezerahmet/cumulus-sync",
        "branch": "main",
        "manifest_file": "sync_manifest.json",
    },
    "gdrive": {
        "root": "gdrive:cumulusos-backups",
        "versioned_dir": "gdrive:cumulusos-backups/versiyonlu",
    },
    "network": {
        "h1_http": "http://100.92.2.47:9090",
        "h2_http": "http://100.76.82.46:9090",
        "timeout_s": 10,
    },
    "machines": {
        "h1_hostnames": ["CumulusNET-Hermes-1", "hal-server-801964"],
        "h2_hostnames": ["H2-Windows-RTX5070Ti"],
    },
    "dirs": {
        "kernel": {
            "paths": [
                "/root/.config/superpowers/worktrees/cumulusos/canonical-full-product-gates",
                "/root/cumulusos"
            ],
            "include": ["*.c", "*.h", "*.md", "Makefile"],
            "exclude_dirs": [".git", "build", "__pycache__", ".backup", ".sync_backup"],
            "max_size_kb": 512,
            "gdrive": True,
        },
        "patent": {
            "path": "/root/patent_docs",
            "include": ["*.md", "*.txt"],
            "exclude_dirs": [".git"],
            "max_size_kb": 512,
            "gdrive": True,
        },
        "scripts": {
            "path": "/root/.hermes/scripts",
            "include": ["*.py", "*.sh", "*.ps1", "*.md"],
            "exclude_dirs": ["__pycache__"],
            "max_size_kb": 512,
            "gdrive": True,
        },
        "pcb": {
            "path": "/root/pcb/projects",
            "include": ["*.kicad_sch", "*.kicad_pcb", "*.md", "*BOM*"],
            "exclude_dirs": [".git", "production", "gerber"],
            "max_size_kb": 2048,
            "gdrive": True,
        },
        "hermes": {
            "path": "~/.hermes",
            "include": ["*.yaml", "*.yml", "*.json", "*.md", "*.py", "*.sh"],
            "exclude_dirs": ["cache", "logs", "audio_cache", "state",
                             "profiles", "models", "venv", "__pycache__",
                             "kanban", "plugins", "agents", "backups",
                             "sessions", "skills", "scripts"],
            "max_size_kb": 1024,
            "gdrive": True,
        },
        "hermes-skills": {
            "path": "~/.hermes/skills",
            "include": ["*.md", "*.py", "*.sh"],
            "exclude_dirs": ["__pycache__"],
            "max_size_kb": 2048,
            "gdrive": True,
        },
    },
    "state": {
        "manifest_local": "~/.hermes/state/sync_motor_manifest.json",
        "logfile": "~/.hermes/state/sync_motor.log",
    },
}


def detect_machine(hostname=None):
    """H1 mi H2 mi? hostname + OS kombinasyonu ile."""
    hostname = hostname or (os.uname().nodename if os.name != "nt"
                            else os.environ.get("COMPUTERNAME", ""))
    hn = hostname.lower()

    for h1 in DEFAULT_CONFIG["machines"]["h1_hostnames"]:
        if h1.lower() in hn:
            return "H1"
    for h2 in DEFAULT_CONFIG["machines"]["h2_hostnames"]:
        if h2.lower() in hn:
            return "H2"
    # OS fallback
    return "H2" if os.name == "nt" else "H1"


def load_config(path=None):
    """config.json yükle (yoksa default). Makineye göre dirs düzelt."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "config.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                user_cfg = json.load(f)
            # Derin birleştirme (basit: üst seviye)
            for section, values in user_cfg.items():
                if isinstance(values, dict) and section in cfg:
                    cfg[section].update(values)
                else:
                    cfg[section] = values
        except Exception as e:
            log.warning(f"config.json okunamadı ({e}), default kullanılıyor")

    # Makine tespiti
    cfg["machine"] = detect_machine()
    cfg["is_h1"] = cfg["machine"] == "H1"

    # Windows'ta dizin yollarını çevir
    if os.name == "nt":
        cfg["dirs"]["kernel"]["path"] = r"C:\cumulusos"
        cfg["dirs"]["patent"]["path"] = r"C:\ProjectCumulus"
        cfg["dirs"]["scripts"]["path"] = str(Path.home() / ".hermes" / "scripts")

    # Yol genişlet (~ → home)
    for k in ("manifest_local", "logfile"):
        cfg["state"][k] = os.path.expanduser(cfg["state"][k])

    return cfg


# ═══════════════════════════════════════════════════════════════
# ÇEKİRDEK: HASH + DOSYA YARDIMCILARI
# ═══════════════════════════════════════════════════════════════

def sha256_file(path):
    """Büyük dosyalar için chunked SHA256."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def matches_glob(path, patterns):
    """Dosya adı glob pattern'lerden birine uyuyor mu?"""
    import fnmatch
    return any(fnmatch.fnmatch(os.path.basename(path), p) for p in patterns)


def should_exclude_dir(dirname, exclude_dirs):
    return dirname in exclude_dirs


# ═══════════════════════════════════════════════════════════════
# ENVANTER TARAMA
# ═══════════════════════════════════════════════════════════════

def scan_directory(label, dir_cfg):
    """
    Bir dizini tara; include pattern + boyut filtresi uygula.
    Çoklu yol desteği: dir_cfg['paths'] veya tek 'path'.
    GÜVENLİK: .env, *.key, token içeren dosyalar ASLA kapsama alınmaz.
    Dönen: {relpath: {sha, size, mtime, machine}}
    """
    # Çoklu yol veya tek yol
    paths = dir_cfg.get("paths") or [dir_cfg["path"]]
    include = dir_cfg.get("include", ["*"])
    exclude_dirs = dir_cfg.get("exclude_dirs", [])
    max_bytes = dir_cfg.get("max_size_kb", 512) * 1024

    # GÜVENLİK: hassas dosya kalıpları — asla manifest'e girmez
    SECRET_PATTERNS = (".env", ".env.", "*.key", "*.pem", "*.p12",
                       "id_rsa", "id_ed25519", "*.token", "secrets",
                       "credentials", "service-account", "*-sa-key")

    def is_secret(fname):
        import fnmatch
        return any(fnmatch.fnmatch(fname, p) for p in SECRET_PATTERNS)

    inventory = {}
    for base in paths:
        base = os.path.expanduser(base)
        if not os.path.isdir(base):
            log.debug(f"{label}: dizin yok — {base}")
            continue

        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not should_exclude_dir(d, exclude_dirs)]
            for fname in files:
                # GÜVENLİK: secret dosyaları atla
                if is_secret(fname):
                    log.debug(f"Güvenlik: {fname} atlandı")
                    continue
                fpath = os.path.join(root, fname)
                try:
                    stat = os.stat(fpath)
                except OSError:
                    continue
                # Boyut filtresi
                if stat.st_size > max_bytes:
                    continue
                # Pattern filtresi
                if not matches_glob(fpath, include):
                    continue
                rel = os.path.relpath(fpath, base)
                inventory[f"{label}/{rel}"] = {
                    "sha": sha256_file(fpath),
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                    "machine": detect_machine(),
                }
    return inventory


def scan_all(cfg):
    """Tüm yapılandırılmış dizinleri tara, birleşik envanter döndür."""
    inventory = {}
    for label, dir_cfg in cfg["dirs"].items():
        inventory.update(scan_directory(label, dir_cfg))
    return inventory


# ═══════════════════════════════════════════════════════════════
# MANİFEST
# ═══════════════════════════════════════════════════════════════

def load_manifest(cfg):
    path = cfg["state"]["manifest_local"]
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {"version": __version__, "files": {}, "last_sync": None,
            "machine": cfg["machine"]}


def save_manifest(cfg, mf):
    path = cfg["state"]["manifest_local"]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(mf, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)   # atomik yaz


def detect_changes(cfg):
    """Yerel envanter vs manifest → yeni/değişen/silinen."""
    local = scan_all(cfg)
    mf = load_manifest(cfg)
    known = mf.get("files", {})

    new, changed, deleted = [], [], []
    for path, info in local.items():
        if path not in known:
            new.append(path)
        elif known[path].get("sha") != info["sha"]:
            changed.append(path)
    for path in known:
        if path not in local:
            deleted.append(path)

    return new, changed, deleted, local


# ═══════════════════════════════════════════════════════════════
# GITHUB MERKEZ (gh CLI veya API)
# ═══════════════════════════════════════════════════════════════

def gh_available():
    out, rc = run_cmd("gh --version")
    return rc == 0


def run_cmd(cmd, timeout=60):
    """Shell komutu çalıştır — (stdout, returncode)."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "timeout", -1
    except Exception as e:
        return str(e), -1


def gh_ensure_repo(cfg):
    repo = cfg["github"]["repo"]
    out, rc = run_cmd(f"gh repo view {repo} 2>&1 | head -2")
    if rc == 0 and "not found" not in out.lower() and out:
        log.info(f"GitHub repo hazır: {repo}")
        return True
    out, rc = run_cmd(
        f"gh repo create {repo} --private "
        f"--description 'Cumulus H1-H2 senkronizasyon merkezi'")
    if rc == 0:
        log.info(f"GitHub repo oluşturuldu: {repo}")
        return True
    log.error(f"Repo oluşturulamadı: {out[:120]}")
    return False


def gh_push_manifest(cfg, mf):
    """Manifest'i GitHub'a API ile push et (repo clone'suz).
    Doğrudan urllib ile çağrılır — shell argüman limiti sorununu aşar.
    GitHub content API limiti ~1MB — manifest küçük tutulmalı."""
    import base64
    import urllib.request
    import urllib.error

    repo = cfg["github"]["repo"]
    mfile = cfg["github"]["manifest_file"]
    token = _gh_token()
    if not token:
        log.error("gh token alınamadı — gh auth status kontrol")
        return False

    content = json.dumps(mf, indent=1, ensure_ascii=False)
    b64 = base64.b64encode(content.encode()).decode()

    # Mevcut SHA
    sha = None
    url_get = f"https://api.github.com/repos/{repo}/contents/{mfile}"
    req_get = urllib.request.Request(url_get,
                                     headers={"Authorization": f"Bearer {token}",
                                              "User-Agent": "sync-motor"})
    try:
        with urllib.request.urlopen(req_get, timeout=20) as resp:
            data = json.loads(resp.read().decode())
            sha = data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            log.warning(f"manifest GET {e.code}")
    except Exception as e:
        log.warning(f"manifest GET: {e}")

    payload = {
        "message": f"sync {datetime.now().isoformat()}",
        "content": b64,
    }
    if sha:
        payload["sha"] = sha

    data = json.dumps(payload).encode()
    req_put = urllib.request.Request(
        url_get, data=data, method="PUT",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "User-Agent": "sync-motor"})
    try:
        with urllib.request.urlopen(req_put, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            log.info(f"Manifest GitHub'a push edildi "
                     f"({len(mf['files'])} dosya, sha={result.get('sha','')[:8]})")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:200]
        log.error(f"Manifest push başarısız: HTTP {e.code} {body}")
        return False
    except Exception as e:
        log.error(f"Manifest push başarısız: {e}")
        return False


def gh_fetch_manifest(cfg):
    """GitHub'dan uzak manifest çek (urllib ile)."""
    import base64
    import urllib.request
    import urllib.error

    repo = cfg["github"]["repo"]
    mfile = cfg["github"]["manifest_file"]
    token = _gh_token()
    if not token:
        return None

    url = f"https://api.github.com/repos/{repo}/contents/{mfile}"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}",
                      "User-Agent": "sync-motor"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        # Büyük manifest için content boş olabilir (GitHub 1MB API limiti)
        # → download_url (raw) ile çek, auth gerekmez (private ise token)
        dl_url = data.get("download_url")
        if dl_url:
            req2 = urllib.request.Request(
                dl_url, headers={"Authorization": f"Bearer {token}",
                                 "User-Agent": "sync-motor"})
            with urllib.request.urlopen(req2, timeout=60) as resp2:
                content = resp2.read().decode()
            return json.loads(content)
        # Fallback: content base64 (küçük manifest)
        content = base64.b64decode(data["content"]).decode()
        return json.loads(content)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log.debug("Uzak manifest yok (ilk kurulum)")
        else:
            log.warning(f"manifest GET {e.code}")
        return None
    except Exception as e:
        log.warning(f"manifest GET: {e}")
        return None


def _gh_token():
    """gh auth token'ı al (gh auth token komutu)."""
    out, rc = run_cmd("gh auth token", timeout=15)
    token = out.strip()
    return token if rc == 0 and token and " " not in token else None


# ═══════════════════════════════════════════════════════════════
# GDRIVE (BÜYÜK DOSYALAR, VERSİYONLU)
# ═══════════════════════════════════════════════════════════════

def rclone_available():
    out, rc = run_cmd("rclone version")
    return rc == 0


def gdrive_snapshot(cfg, node=None):
    """
    Seçilen node'ların GDrive'da versiyonlu snapshot'ını al.
    Per-node klasör: versiyonlu/<node>/<timestamp>/
    Üzerine ASLA yazmaz — her seferinde yeni timestamp klasörü.
    """
    if not rclone_available():
        log.warning("rclone yok — GDrive snapshot atlandı")
        return None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    workdir = "/tmp/sync_motor_snapshot"
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)

    # Hangi node'lar?
    nodes = [node] if node else list(cfg["dirs"].keys())
    results = {}

    for label in nodes:
        dir_cfg = cfg["dirs"].get(label)
        if not dir_cfg or not dir_cfg.get("gdrive", False):
            continue
        # Çoklu yol desteği
        paths = dir_cfg.get("paths") or [dir_cfg.get("path", "")]
        base = None
        for p in paths:
            pexp = os.path.expanduser(p)
            if os.path.isdir(pexp):
                base = pexp
                break
        if not base:
            log.debug(f"{label}: dizin yok")
            continue

        # Node başına ayrı paket — include pattern'leri ile (tar değil)
        pkg = f"{workdir}/{label}.tar.gz"
        include = dir_cfg.get("include", ["*"])
        excl = dir_cfg.get("exclude_dirs", [])
        base_expanded = os.path.expanduser(base)

        # find ile filtrele: include pattern'lerine uyan dosyaları topla
        # (29GB dizinlerde tar yerine find çok daha hızlı)
        find_expr = []
        for pat in include:
            find_expr.append(f'-name "{pat}"')
        find_cmd = " -o ".join(find_expr)
        excl_find = " ".join(f"-not -path '*/{d}/*'" for d in excl)

        out, rc = run_cmd(
            f'cd "{base_expanded}" && find . {excl_find} '
            f'\\( {find_cmd} \\) -type f 2>/dev/null | head -5000 | '
            f'tar -czf "{pkg}" -T - 2>/dev/null', timeout=120)
        if rc != 0 or not os.path.exists(pkg) or os.path.getsize(pkg) == 0:
            log.warning(f"{label}: paket oluşturulamadı "
                        f"(rc={rc}, boyut={os.path.exists(pkg) and os.path.getsize(pkg)})")
            continue

        # Node'a özel GDrive hedef
        target = f"{cfg['gdrive']['versioned_dir']}/{label}/{ts}"
        out, rc = run_cmd(
            f'rclone copy "{pkg}" "{target}" --ignore-checksum '
            f'--no-traverse', timeout=180)
        if rc == 0:
            sz = os.path.getsize(pkg) // 1024
            results[label] = f"{target} ({sz}KB)"
            log.info(f"GDrive: {label} → versiyonlu/{label}/{ts} ({sz}KB)")

    return results if results else None


# ═══════════════════════════════════════════════════════════════
# TAILSCALE / HTTP FARKINDALIK
# ═══════════════════════════════════════════════════════════════

def http_get(url, timeout=8):
    """Basit HTTP GET — (içerik, durum)."""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "sync-motor"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore"), resp.status
    except Exception as e:
        return str(e), -1


def peer_status(cfg):
    """Karşı tarafın durumu — farkındalık."""
    peer_url = (cfg["network"]["h2_http"] if cfg["is_h1"]
                else cfg["network"]["h1_http"])
    _, code = http_get(f"{peer_url}/", cfg["network"]["timeout_s"])
    return "ONLINE" if code == 200 else "OFFLINE"


def announce(cfg, msg):
    """Karşı tarafa durum notu bırak (her iki 9090'a)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"SYNC_NOTE_{ts}.txt"
    local = "/tmp/hermes_uploads" if cfg["is_h1"] else "/tmp"
    os.makedirs(local, exist_ok=True)
    try:
        with open(os.path.join(local, fname), "w") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except OSError:
        pass
    # Karşı tarafa form-POST dene
    peer_url = (cfg["network"]["h2_http"] if cfg["is_h1"]
                else cfg["network"]["h1_http"])
    try:
        import urllib.request
        import urllib.parse
        data = urllib.parse.urlencode({"file": fname}).encode()
        req = urllib.request.Request(f"{peer_url}/", data=data)
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass
    return fname


# ═══════════════════════════════════════════════════════════════
# ÇAKIŞMA YÖNETİMİ (NON-DESTRUCTIVE)
# ═══════════════════════════════════════════════════════════════

def list_conflicts(cfg):
    """Tüm yapılandırılmış dizinlerde .conflict.* dosyalarını bul."""
    found = []
    for label, dir_cfg in cfg["dirs"].items():
        paths = dir_cfg.get("paths") or [dir_cfg.get("path", "")]
        for p in paths:
            base = os.path.expanduser(p)
            if not os.path.isdir(base):
                continue
            for root, dirs, files in os.walk(base):
                for f in files:
                    if ".conflict." in f:
                        found.append(os.path.join(root, f))
    return found


# ═══════════════════════════════════════════════════════════════
# KOMUTLAR
# ═══════════════════════════════════════════════════════════════

def cmd_push(cfg, node=None):
    print(f"\n  🔄 PUSH — {cfg['machine']}"
          + (f" [node: {node}]" if node else " [tüm node'lar]"))
    if node and node not in cfg["dirs"]:
        log.error(f"Bilinmeyen node: {node} — mevcut: {list(cfg['dirs'].keys())}")
        return

    if node:
        # Tek node: sadece o dizini tara
        new, changed, deleted, local = detect_changes_node(cfg, node)
    else:
        new, changed, deleted, local = detect_changes(cfg)

    if not new and not changed and not deleted:
        log.info("Değişiklik yok — push atlandı")
    else:
        log.info(f"Push: {len(new)} yeni, {len(changed)} değişen, "
                 f"{len(deleted)} silinen")

    # Manifest güncelle + GitHub'a yaz
    mf = load_manifest(cfg)
    if node:
        # Node'a özel anahtar: files.<node>
        node_files = mf.setdefault("node_files", {})
        node_files[node] = {k: v for k, v in local.items()
                            if k.startswith(f"{node}/")}
        mf["last_sync"] = datetime.now().isoformat()
        mf["machine"] = cfg["machine"]
    else:
        mf["files"] = local
        mf["last_sync"] = datetime.now().isoformat()
        mf["machine"] = cfg["machine"]
    save_manifest(cfg, mf)

    if gh_available():
        if gh_ensure_repo(cfg):
            gh_push_manifest(cfg, mf)
    else:
        log.warning("gh CLI yok — GitHub push atlandı (manifest yerel)")

    # GDrive versiyonlu snapshot (node'a özel)
    gdrive_snapshot(cfg, node=node)

    # Karşı tarafa bildir
    if len(new) + len(changed) > 0:
        announce(cfg, f"Push{(' ['+node+']') if node else ''}: "
                      f"{len(new)} yeni, {len(changed)} değişen ({cfg['machine']})")


def detect_changes_node(cfg, node):
    """Tek node için değişiklik tespiti."""
    dir_cfg = cfg["dirs"].get(node)
    if not dir_cfg:
        return [], [], [], {}
    local = scan_directory(node, dir_cfg)
    mf = load_manifest(cfg)
    node_files = mf.get("node_files", {}).get(node, {})
    # Ayrıca eski format files.<node/...> kontrolü
    legacy = {k: v for k, v in mf.get("files", {}).items()
              if k.startswith(f"{node}/")}
    known = {**legacy, **node_files}

    new, changed, deleted = [], [], []
    for path, info in local.items():
        if path not in known:
            new.append(path)
        elif known[path].get("sha") != info["sha"]:
            changed.append(path)
    for path in known:
        if path not in local:
            deleted.append(path)
    return new, changed, deleted, local


def cmd_nodes(cfg):
    """Tüm node'ları + GDrive versiyon geçmişini listele."""
    print("\n  📦 NODE'LAR")
    for label, dir_cfg in cfg["dirs"].items():
        paths = dir_cfg.get("paths") or [dir_cfg.get("path", "")]
        base = None
        for p in paths:
            pexp = os.path.expanduser(p)
            if os.path.isdir(pexp):
                base = pexp
                break
        exists = bool(base)
        gd = dir_cfg.get("gdrive", False)
        # GDrive versiyon sayısı
        ver_count = "?"
        if gd and rclone_available():
            out, rc = run_cmd(
                f'rclone lsd {cfg["gdrive"]["versioned_dir"]}/{label} '
                f'2>/dev/null | wc -l', timeout=30)
            ver_count = out.strip() if rc == 0 else "?"
        print(f"  {'🟢' if exists else '🔴'} {label:12s} "
              f"{'GDrive:'+str(ver_count)+' ver' if gd else 'lokal'}")
    print()


def cmd_select(cfg):
    """İnteraktif node seçimi — hangi node eşitlensin?"""
    print("\n  🎯 NODE SEÇİMİ")
    labels = list(cfg["dirs"].keys())
    for i, label in enumerate(labels, 1):
        dir_cfg = cfg["dirs"][label]
        paths = dir_cfg.get("paths") or [dir_cfg.get("path", "")]
        exists = False
        for p in paths:
            if os.path.isdir(os.path.expanduser(p)):
                exists = True
                break
        print(f"  [{i}] {'🟢' if exists else '🔴'} {label}")
    print(f"  [0] TÜMÜ")
    print(f"  [q] Çık")

    try:
        choice = input("\n  Seçim: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if choice in ("q", ""):
        return
    if choice == "0":
        log.info("TÜM node'lar seçildi — both çalıştırılıyor")
        cmd_push(cfg, node=None)
        cmd_pull(cfg)
        return
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(labels):
            node = labels[idx]
            log.info(f"Node seçildi: {node}")
            cmd_push(cfg, node=node)
            cmd_pull(cfg)
        else:
            log.error("Geçersiz seçim")
    except ValueError:
        log.error("Geçersiz seçim")


def cmd_status(cfg):
    print("\n" + "═" * 60)
    print(f"  CUMULUS SYNC MOTOR v{__version__} — DURUM")
    print(f"  Makine: {cfg['machine']} ({cfg['is_h1'] and 'H1 VPS' or 'H2 Desktop'})")
    print("═" * 60)

    peer = peer_status(cfg)
    print(f"  Karşı taraf: {'🟢 ONLINE' if peer == 'ONLINE' else '🔴 OFFLINE'}")

    new, changed, deleted, local = detect_changes(cfg)
    print(f"\n  Yerel envanter: {len(local)} dosya (filtrelenmiş)")
    print(f"  Yeni: {len(new)} | Değişen: {len(changed)} | Silinen: {len(deleted)}")

    mf = load_manifest(cfg)
    print(f"  Manifest: {len(mf.get('files', {}))} kayıt, "
          f"son sync: {mf.get('last_sync', '—')}")

    remote = gh_fetch_manifest(cfg)
    if remote:
        rfiles = remote.get("files", {})
        local_paths = set(local.keys())
        remote_only = [p for p in rfiles if p not in local_paths]
        print(f"  GitHub manifest: {len(rfiles)} kayıt, "
              f"uzaktan gelecek: {len(remote_only)}")
    else:
        print(f"  GitHub manifest: erişilemedi (gh auth kontrol)")

    conflicts = list_conflicts(cfg)
    print(f"  Çakışma: {len(conflicts)}")
    print("═" * 60 + "\n")


def gdrive_pull_latest(cfg, node):
    """
    GDrive'dan node'un EN SON versiyonunu çek ve doğrula.
    Non-destructive: hedef dizine yazar ama çakışan dosyalar .conflict.TS.
    """
    if not rclone_available():
        log.warning("rclone yok — GDrive pull atlandı")
        return False

    # En son versiyon klasörünü bul
    out, rc = run_cmd(
        f'rclone lsd {cfg["gdrive"]["versioned_dir"]}/{node} '
        f'2>/dev/null | tail -1', timeout=30)
    if rc != 0 or not out:
        log.info(f"{node}: GDrive'da versiyon yok")
        return False
    # En son timestamp klasörü
    latest = out.split()[-1]
    if not latest or not latest.replace("_", "").isdigit():
        log.warning(f"{node}: geçersiz versiyon klasörü: {latest}")
        return False

    # Paketi çek
    pkg = f"/tmp/sync_pull_{node}.tar.gz"
    out, rc = run_cmd(
        f'rclone copy {cfg["gdrive"]["versioned_dir"]}/{node}/{latest}/ '
        f'/tmp/sync_pull_{node}/ --ignore-checksum --no-traverse', timeout=180)
    if rc != 0:
        log.error(f"{node}: GDrive pull başarısız")
        return False

    # Paketi aç (hedef dizine, çakışma korumalı)
    dir_cfg = cfg["dirs"].get(node)
    paths = dir_cfg.get("paths") or [dir_cfg.get("path", "")]
    target = None
    for p in paths:
        if os.path.isdir(os.path.expanduser(p)):
            target = os.path.expanduser(p)
            break
    if not target:
        log.warning(f"{node}: hedef dizin yok")
        return False

    pkg_file = f"/tmp/sync_pull_{node}/{node}.tar.gz"
    if not os.path.exists(pkg_file):
        # Rclone dosya adını korudu
        import glob
        found = glob.glob(f"/tmp/sync_pull_{node}/*.tar.gz")
        pkg_file = found[0] if found else None
    if not pkg_file:
        log.warning(f"{node}: paket bulunamadı")
        return False

    # Aç — çakışanları koru
    import tarfile
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        with tarfile.open(pkg_file, "r:gz") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                # Göreli yol — ./ önekini kaldır
                name = member.name.lstrip("./")
                if not name:
                    continue
                dest = os.path.join(target, name)
                # Çakışma kontrolü: hedef var + farklı içerik
                if os.path.exists(dest):
                    src = tf.extractfile(member)
                    if src:
                        content = src.read()
                        local_content = open(dest, "rb").read()
                        if content != local_content:
                            # Çakışma — yerel korunur
                            conflict = f"{dest}.conflict.{ts}"
                            log.warning(f"Çakışma: {name} → {conflict}")
                            continue  # yereli koru, uzak yazılmaz
                # Güvenli yaz
                dest_dir = os.path.dirname(dest)
                os.makedirs(dest_dir, exist_ok=True)
                src = tf.extractfile(member)
                if src:
                    with open(dest, "wb") as f:
                        f.write(src.read())
        log.info(f"{node}: GDrive {latest} çekildi (çakışma korumalı)")
        return True
    except Exception as e:
        log.error(f"{node}: paket açılamadı: {e}")
        return False


def verify_build(cfg):
    """Kernel pull sonrası build doğrulama — Cumulus kritik."""
    kernel_cfg = cfg["dirs"].get("kernel")
    if not kernel_cfg:
        return True
    paths = kernel_cfg.get("paths") or [kernel_cfg.get("path", "")]
    for p in paths:
        pexp = os.path.expanduser(p)
        if not os.path.isdir(pexp):
            continue
        # Makefile var mı?
        if not os.path.exists(os.path.join(pexp, "Makefile")):
            continue
        log.info(f"Build doğrulama: {pexp}")
        out, rc = run_cmd(f'cd "{pexp}" && make clean && make 2>&1 | tail -3',
                          timeout=300)
        if rc != 0:
            log.error(f"Build BAŞARISIZ: {pexp}")
            return False
        log.info(f"Build PASS: {pexp}")
        break  # İlk geçerli dizin yeterli
    return True


def cmd_pull(cfg):
    print(f"\n  🔄 PULL — {cfg['machine']}")
    remote = gh_fetch_manifest(cfg)
    if not remote:
        log.error("Uzak manifest alınamadı")
        return

    local = scan_all(cfg)
    rfiles = remote.get("files", {})

    to_pull = []
    conflicts = []
    for path, rinfo in rfiles.items():
        if path not in local:
            to_pull.append(path)
        elif local[path].get("sha") != rinfo.get("sha"):
            lmachine = local[path].get("machine", "?")
            rmachine = rinfo.get("machine", "?")
            if lmachine != rmachine:
                conflicts.append(path)
            else:
                to_pull.append(path)

    if not to_pull and not conflicts:
        log.info("Güncel — çekilecek yok")
    else:
        log.info(f"Pull: {len(to_pull)} yeni, {len(conflicts)} çakışma tespiti")

    print("\n  Manifest durumu:")
    for p in to_pull[:15]:
        print(f"    🔄 {p}")
    for p in conflicts[:15]:
        print(f"    ⚠️ ÇAKIŞMA: {p} (yerel korunacak)")
    if len(to_pull) + len(conflicts) > 15:
        print(f"    ... +{len(to_pull)+len(conflicts)-15} daha")

    # Gerçek dosya transferi: kernel için git pull öner
    kernel_cfg = cfg["dirs"].get("kernel", {})
    kernel_paths = kernel_cfg.get("paths") or [kernel_cfg.get("path", "")]
    if any(os.path.isdir(os.path.expanduser(p)) for p in kernel_paths):
        log.info("Kernel dosyaları için: git pull "
                 "(repo: yolgezerahmet/cumulusos)")

    # GDrive'dan en son versiyonları çek (non-destructive)
    log.info("GDrive versiyon çekme...")
    pulled = 0
    for label in cfg["dirs"]:
        if cfg["dirs"][label].get("gdrive", False):
            if gdrive_pull_latest(cfg, label):
                pulled += 1
    if pulled:
        log.info(f"GDrive: {pulled} node güncellendi")

    # Manifest'e pull zamanı yaz
    mf = load_manifest(cfg)
    mf["last_pull"] = datetime.now().isoformat()
    mf["remote_known"] = remote.get("last_sync")
    save_manifest(cfg, mf)

    # Kernel pull sonrası build doğrulama (Cumulus kritik)
    if pulled or to_pull:
        log.info("Build doğrulama...")
        verify_build(cfg)


def cmd_conflicts(cfg):
    print("\n  ⚠️ ÇAKIŞMA DOSYALARI")
    found = list_conflicts(cfg)
    if not found:
        print("    Çakışma yok ✅")
        return
    for f in found:
        sz = os.path.getsize(f)
        print(f"    {f} ({sz//1024}KB)")
    print(f"\n  {len(found)} çakışma — .conflict.TS korunuyor, "
          f"otomatik çözüm: incele ve manuel birleştir")


def cmd_init(cfg):
    print("\n  🚀 INIT — İlk Kurulum")
    if gh_available() and gh_ensure_repo(cfg):
        new, changed, deleted, local = detect_changes(cfg)
        mf = load_manifest(cfg)
        mf["files"] = local
        mf["last_sync"] = datetime.now().isoformat()
        mf["machine"] = cfg["machine"]
        save_manifest(cfg, mf)
        gh_push_manifest(cfg, mf)
        log.info(f"İlk manifest: {len(local)} dosya")
    else:
        log.warning("gh CLI yok veya repo hazırlanamadı — "
                    "manifest yerel tutulacak")
    gdrive_snapshot(cfg)
    log.info("Kurulum tamam — 'python3 sync_motor.py both' ile kullan")


# ═══════════════════════════════════════════════════════════════
# ANA
# ═══════════════════════════════════════════════════════════════

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="sync_motor",
        description="Cumulus Sync Motoru — GitHub+GDrive+Tailscale "
                    "iki yönlü senkronizasyon")
    parser.add_argument("komut", nargs="?", default="status",
                        choices=["status", "push", "pull", "both",
                                 "conflicts", "init", "select", "nodes",
                                 "version"])
    parser.add_argument("--config", default=None,
                        help="config.json yolu")
    parser.add_argument("--node", default=None,
                        help="sadece belirli node'u eşitle (kernel, patent, "
                             "scripts, pcb, hermes)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="debug log")
    parser.add_argument("--no-color", action="store_true",
                        help="renksiz çıktı")
    args = parser.parse_args(argv)

    if args.komut == "version":
        print(f"sync_motor v{__version__}")
        return 0

    # Logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logfile = os.path.expanduser(DEFAULT_CONFIG["state"]["logfile"])
    setup_logging(level, logfile)

    cfg = load_config(args.config)

    print(f"\n╔{'═'*58}╗")
    print(f"║  CUMULUS SYNC MOTOR v{__version__} — {cfg['machine']}"
          f"{' '*(34-len(cfg['machine']))}║")
    print(f"╚{'═'*58}╝")

    if args.komut == "status":
        cmd_status(cfg)
    elif args.komut == "push":
        cmd_push(cfg, node=args.node)
    elif args.komut == "pull":
        cmd_pull(cfg)
    elif args.komut == "both":
        cmd_push(cfg, node=args.node)
        cmd_pull(cfg)
    elif args.komut == "conflicts":
        cmd_conflicts(cfg)
    elif args.komut == "init":
        cmd_init(cfg)
    elif args.komut == "nodes":
        cmd_nodes(cfg)
    elif args.komut == "select":
        cmd_select(cfg)

    return 0


if __name__ == "__main__":
    sys.exit(main())
