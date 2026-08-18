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

__version__ = "1.6.0"
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
    "identity": {
        "user_id": "cumulusnet",      # GDrive alanı: gdrive:hermes-sync/<user_id>/
        "machine_id": "",             # boş = otomatik (hostname)
    },
    "github": {
        "repo": "yolgezerahmet/cumulus-sync",
        "branch": "main",
        "manifest_file": "sync_manifest.json",
    },
    "gdrive": {
        "root": "gdrive:hermes-sync",      # EVRENSEL: her kullanıcı kendi alanında
        "versioned_dir": "gdrive:hermes-sync/cumulusnet/versiyonlu",
    },
    "network": {
        "h1_http": "http://100.92.2.47:9090",
        "h2_http": "http://100.76.82.46:9090",
        "timeout_s": 10,
    },
    "machines": {
        "h1_hostnames": ["CumulusNET-Hermes-1", "hal-server-801964"],
        "h2_hostnames": ["H2-Windows-RTX5070Ti"],
        "openclaw_hostnames": ["openclaw"],
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
        "openclaw": {
            "path": "~/.openclaw",
            "include": ["*.md", "*.json", "*.yaml", "*.yml", "*.py"],
            "exclude_dirs": ["cache", "logs", "sessions", "workspace",
                             "skills", "scripts", "__pycache__", "models"],
            "max_size_kb": 1024,
            "gdrive": True,
        },
        "hermes-full": {
            "path": "~/.hermes",
            "include": ["*.yaml", "*.yml", "*.json", "*.md", "*.py", "*.sh"],
            "exclude_dirs": ["cache", "logs", "audio_cache", "models",
                             "venv", "__pycache__", "state", "kanban"],
            "max_size_kb": 2048,
            "gdrive": True,
        },
    },
    # AKILLI KURULUM KATALOĞU (v1.6):
    # - check: araç varlık kontrolü (HERHANGİ BİRİ kuruluysa "kurulu" sayılır)
    # - gpu: True ise GPU öncelikli — öneri listesinde öne alınır ve GPU'suz
    #   makinelere kurulum ÖNERİLMEZ (kaynak kontrolü)
    # - min_cpus/min_ram_gb/min_disk_gb: kurulum için asgari kaynak eşikleri
    # - install: onay sonrası çalıştırılacak kurulum komutu (kendi config'inizden
    #   gelir; kabuk operatörleri için string form kullanılır — run_cmd shell=True)
    # Kurulum ASLA otomatik değildir: 'propose' öneri sunar, 'apply --yes' (veya
    # interaktif onay) sonrası çalışır. Üzerine yazma YOKTUR (zaten kuruluysa RED).
    "tools": {
        "cuda-toolkit": {
            "check": ["nvcc", "/usr/local/cuda/bin/nvcc"],
            "gpu": True, "min_ram_gb": 8, "min_disk_gb": 25, "min_cpus": 4,
            "desc": "NVIDIA CUDA toolkit — GPU hesaplama (vLLM/torch)",
            "install": ("curl -fsSL https://developer.download.nvidia.com/compute/"
                        "cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb "
                        "-o /tmp/cuda-keyring.deb && sudo dpkg -i /tmp/cuda-keyring.deb "
                        "&& sudo apt-get update && sudo apt-get -y install cuda-toolkit-12-8"),
        },
        "vllm": {
            "check": ["vllm"],
            "gpu": True, "min_ram_gb": 16, "min_disk_gb": 30, "min_cpus": 4,
            "desc": "vLLM — yüksek verimli LLM serving (GPU zorunlu)",
            "install": "pip install vllm",
        },
        "ollama": {
            "check": ["ollama"],
            "gpu": False, "min_ram_gb": 8, "min_disk_gb": 20, "min_cpus": 2,
            "desc": "Ollama — yerel LLM runtime (CPU/GPU)",
            "install": "curl -fsSL https://ollama.com/install.sh | sh",
        },
        "docker": {
            "check": ["docker"],
            "gpu": False, "min_ram_gb": 4, "min_disk_gb": 10, "min_cpus": 2,
            "desc": "Docker — konteyner runtime (nRF SDK dahil)",
            "install": "curl -fsSL https://get.docker.com | sh",
        },
        "zephyr-sdk": {
            "check": ["west"],
            "gpu": False, "min_ram_gb": 4, "min_disk_gb": 15, "min_cpus": 2,
            "desc": "Zephyr/NCS build zinciri (west)",
            "install": "pip install west",
        },
        "kicad-cli": {
            "check": ["kicad-cli"],
            "gpu": False, "min_ram_gb": 2, "min_disk_gb": 3, "min_cpus": 2,
            "desc": "KiCad komut satırı — PCB DRC/ERC/üretim",
            "install": "sudo apt-get -y install kicad",
        },
        "arm-none-eabi-gcc": {
            "check": ["arm-none-eabi-gcc"],
            "gpu": False, "min_ram_gb": 1, "min_disk_gb": 1, "min_cpus": 1,
            "desc": "ARM gömülü derleyici (Cortex-M)",
            "install": "sudo apt-get -y install gcc-arm-none-eabi",
        },
        "qemu-system-arm": {
            "check": ["qemu-system-arm"],
            "gpu": False, "min_ram_gb": 1, "min_disk_gb": 1, "min_cpus": 1,
            "desc": "QEMU ARM emülasyonu",
            "install": "sudo apt-get -y install qemu-system-arm",
        },
        "ns3": {
            "check": ["ns3"],
            "gpu": False, "min_ram_gb": 2, "min_disk_gb": 2, "min_cpus": 2,
            "desc": "ns-3 ağ simülatörü",
            "install": "sudo apt-get -y install ns3",
        },
    },
    "state": {
        "manifest_local": "~/.hermes/state/sync_motor_manifest.json",
        "logfile": "~/.hermes/state/sync_motor.log",
    },
}


def detect_machine(hostname=None):
    """H1 mi H2 mi OpenClaw mu? hostname + OS kombinasyonu ile."""
    hostname = hostname or (os.uname().nodename if os.name != "nt"
                            else os.environ.get("COMPUTERNAME", ""))
    hn = hostname.lower()

    for h1 in DEFAULT_CONFIG["machines"]["h1_hostnames"]:
        if h1.lower() in hn:
            return "H1"
    for h2 in DEFAULT_CONFIG["machines"]["h2_hostnames"]:
        if h2.lower() in hn:
            return "H2"
    for oc in DEFAULT_CONFIG["machines"].get("openclaw_hostnames", []):
        if oc.lower() in hn:
            return "OPENCLAW"
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

    # Kimlik: user_id + machine_id (GDrive yolu buna bağlı)
    user_id = cfg.get("identity", {}).get("user_id", "default")
    machine_id = cfg.get("identity", {}).get("machine_id", "")
    if not machine_id:
        machine_id = (os.uname().nodename if os.name != "nt"
                      else os.environ.get("COMPUTERNAME", "unknown"))
        machine_id = machine_id.replace(" ", "_").lower()
        cfg["identity"]["machine_id"] = machine_id
    # GDrive versiyonlu yol: gdrive:hermes-sync/<user_id>/<machine_id>/versiyonlu
    cfg["gdrive"]["versioned_dir"] = (
        f"gdrive:hermes-sync/{user_id}/{machine_id}/versiyonlu")
    cfg["gdrive"]["user_root"] = f"gdrive:hermes-sync/{user_id}"

    # Windows'ta dizin yollarını çevir
    if os.name == "nt":
        cfg["dirs"]["kernel"]["paths"] = [r"C:\cumulusos"]
        cfg["dirs"]["patent"]["path"] = r"C:\ProjectCumulus"
        cfg["dirs"]["scripts"]["path"] = str(Path.home() / ".hermes" / "scripts")
        cfg["dirs"]["openclaw"]["path"] = str(Path.home() / ".openclaw")

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
    Çoklu yol çakışması: aynı göreli yol iki kökte varsa → çakışma
    uyarısı loglanır, son kökün kaydı KULLANILMAZ (veri kaybı önlemi).
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
    # GÜVENLİK: hassas dizin adları — yol bileşeninden reddedilir
    SECRET_DIRS = ("secrets", "credentials", "service-account",
                   ".aws", ".ssh", "private", "keys", "tokens")

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
            dirs[:] = [d for d in dirs
                       if not should_exclude_dir(d, exclude_dirs)
                       and d.lower() not in SECRET_DIRS]
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
                key = f"{label}/{rel}"
                # Çoklu yol çakışması: aynı anahtar zaten varsa
                if key in inventory:
                    # SHA aynıysa → aynı içerik, sorun yok (sessiz)
                    # SHA farklıysa → GERÇEK çakışma (uyar + ilki koru)
                    existing_sha = inventory[key].get("sha")
                    new_sha = sha256_file(fpath)
                    if existing_sha != new_sha:
                        log.debug(f"Çoklu yol farkı: {key} iki kökte "
                                  f"FARKLI içerik — ilki korunuyor "
                                  f"(worktree + ana repo farklı branch)")
                    continue
                inventory[key] = {
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


def run_cmd(cmd, timeout=60, shell=False):
    """
    Komut çalıştır — (stdout, returncode).
    Güvenlik: shell=True KAPALI — komut enjeksiyonuna karşı.
    shell=True gereken pipe komutları için shell=True AÇIKÇA verilir
    ve giriş değerleri config'den (kullanıcının kendi dosyası) gelir.
    """
    try:
        if shell:
            r = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True, timeout=timeout)
        else:
            r = subprocess.run(cmd.split(), capture_output=True,
                               text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "timeout", -1
    except Exception as e:
        return str(e), -1


# ═══════════════════════════════════════════════════════════════
# AKILLI KURULUM — KAYNAK FARKINDALIĞI (v1.6)
# ═══════════════════════════════════════════════════════════════
# Felsefe: eşitleme SIRASINDA hiçbir kurulum otomatik yapılmaz.
# Kaynak node'da kurulu araçlar, hedef node için ÖNERİ olarak sunulur;
# öneri CPU/GPU/RAM/disk kaynak kontrolünden geçer. Kullanıcı onayı
# (apply --yes veya interaktif) sonrası kurulur. Üzerine yazma YOKTUR.

def resource_probe():
    """Yerel kaynakları ölç: CPU çekirdek, RAM (GB), disk boş (GB), GPU.

    GPU tespiti: nvidia-smi → lspci (VGA/3D/Display sınıfı) → vulkaninfo.
    Hiçbiri yoksa gpu=False. Ölçülemeyen değer 0 döner (fail-closed:
    'bilinmiyor' yerine 'yetersiz' kabul edilir → kurulum önerilmez).
    """
    res = {
        "cpus": os.cpu_count() or 0,
        "ram_gb": 0.0,
        "disk_gb": 0.0,
        "gpu": False,       # genel GPU (lspci/vulkan dahil)
        "nvidia": False,    # NVIDIA GPU (nvidia-smi doğrulanmış — CUDA için şart)
        "gpu_name": None,
    }
    # RAM — Linux /proc/meminfo; macOS sysctl; Windows GlobalMemoryStatusEx
    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        res["ram_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
                        break
        elif os.name == "posix":
            out, rc = run_cmd("sysctl -n hw.memsize", timeout=5)
            if rc == 0 and out.isdigit():
                res["ram_gb"] = round(int(out) / 1e9, 1)
        elif os.name == "nt":
            import ctypes
            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = _MS()
            ms.dwLength = ctypes.sizeof(_MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            res["ram_gb"] = round(ms.ullTotalPhys / 1e9, 1)
    except Exception:
        pass
    # Disk — kullanıcı ev dizininin birimi (bulunamazsa kök)
    try:
        res["disk_gb"] = round(shutil.disk_usage(
            os.path.expanduser("~")).free / 1e9, 1)
    except Exception:
        try:
            res["disk_gb"] = round(shutil.disk_usage("/").free / 1e9, 1)
        except Exception:
            pass
    # GPU
    try:
        out, rc = run_cmd(
            "nvidia-smi --query-gpu=name --format=csv,noheader", timeout=10)
        if rc == 0 and out:
            res["gpu"] = True
            res["nvidia"] = True
            res["gpu_name"] = out.splitlines()[0].strip()[:60]
        else:
            out2, rc2 = run_cmd(
                "lspci 2>/dev/null | grep -iE 'vga|3d|display'",
                timeout=10, shell=True)
            if rc2 == 0 and out2:
                res["gpu"] = True
                res["gpu_name"] = out2.splitlines()[0].strip()[:60]
            else:
                out3, rc3 = run_cmd("vulkaninfo --summary", timeout=10)
                if rc3 == 0 and out3:
                    res["gpu"] = True
                    res["gpu_name"] = "vulkan"
    except Exception:
        pass
    return res


def tool_installed(tool_cfg):
    """Araç kurulu mu? check listesindeki HERHANGİ BİRİ bulunursa 'kurulu'."""
    checks = tool_cfg.get("check") or []
    if not checks:
        return False
    for c in checks:
        if shutil.which(c):
            return True
    return False


def scan_tools(cfg):
    """Config'teki tools kataloğunu tara → {ad: kurulum durumu}."""
    tools = cfg.get("tools", {})
    state = {}
    for name, t in tools.items():
        state[name] = {
            "installed": tool_installed(t),
            "gpu": bool(t.get("gpu", False)),
            "min_ram_gb": t.get("min_ram_gb", 0),
            "min_disk_gb": t.get("min_disk_gb", 0),
            "min_cpus": t.get("min_cpus", 1),
        }
    return state


def propose_install(tool_name, tool_cfg, local_res, local_tools, remote_tools):
    """Uzak node'da kurulu bir aracı bu makineye kurmayı değerlendir.

    Dönüş: (durum, mesaj)
      ALREADY            — zaten kurulu (kurma — üzerine asla yazma)
      NOT_ON_SOURCE      — kaynak node'da kurulu değil (öneri yok)
      GPU_MISSING        — GPU gerekli, bu makinede GPU yok
      DISK_INSUFFICIENT  — boş disk min_disk_gb'dan az
      RAM_INSUFFICIENT   — RAM min_ram_gb'dan az
      CPU_INSUFFICIENT   — çekirdek sayısı min_cpus'tan az
      INSTALLABLE        — kaynaklar yeterli, kurulabilir (öneri)
    """
    local_inst = bool(local_tools.get(tool_name, {}).get("installed", False))
    if local_inst:
        return "ALREADY", "zaten kurulu"
    remote_inst = bool(remote_tools.get(tool_name, {}).get("installed", False))
    if not remote_inst:
        return "NOT_ON_SOURCE", "kaynak node'da kurulu değil"

    if tool_cfg.get("gpu") and not local_res.get("nvidia"):
        return "GPU_MISSING", "NVIDIA GPU gerekli — bu makinede CUDA uyumlu GPU yok"
    min_disk = float(tool_cfg.get("min_disk_gb", 0) or 0)
    free_disk = float(local_res.get("disk_gb", 0) or 0)
    if free_disk < min_disk:
        return ("DISK_INSUFFICIENT",
                f"boş disk {free_disk:.1f}GB < {min_disk:.0f}GB gerekli")
    min_ram = float(tool_cfg.get("min_ram_gb", 0) or 0)
    ram = float(local_res.get("ram_gb", 0) or 0)
    if ram < min_ram:
        return "RAM_INSUFFICIENT", f"RAM {ram:.1f}GB < {min_ram:.0f}GB gerekli"
    min_cpus = int(tool_cfg.get("min_cpus", 1) or 1)
    cpus = int(local_res.get("cpus", 0) or 0)
    if cpus < min_cpus:
        return "CPU_INSUFFICIENT", f"CPU {cpus} < {min_cpus} gerekli"
    return "INSTALLABLE", "kurulabilir"


def gh_ensure_repo(cfg):
    repo = cfg["github"]["repo"]
    # PIPE YOK: gh RC doğrudan alınır (pipe RC'yi yutuyordu)
    # shell=True: --jq .name + 2>&1 .split() ile parçalanıyor
    out, rc = run_cmd(
        f"gh repo view {repo} --json name --jq .name 2>&1",
        timeout=30, shell=True)
    if rc == 0 and out and "not found" not in out.lower():
        log.info(f"GitHub repo hazır: {repo}")
        return True
    out, rc = run_cmd(
        f"gh repo create {repo} --private "
        f"--description 'Hermes Sync manifest merkezi'",
        timeout=30, shell=True)
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
            f'tar -czf "{pkg}" -T - 2>/dev/null', timeout=120, shell=True)
        if rc != 0 or not os.path.exists(pkg) or os.path.getsize(pkg) == 0:
            log.warning(f"{label}: paket oluşturulamadı "
                        f"(rc={rc}, boyut={os.path.exists(pkg) and os.path.getsize(pkg)})")
            continue

        # Node'a özel GDrive hedef
        target = f"{cfg['gdrive']['versioned_dir']}/{label}/{ts}"
        out, rc = run_cmd(
            f'rclone copy "{pkg}" "{target}" --ignore-checksum '
            f'--no-traverse', timeout=180, shell=True)
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

def cmd_push(cfg, node=None, dry_run=False):
    print(f"\n  🔄 PUSH — {cfg['machine']}"
          + (f" [node: {node}]" if node else " [tüm node'lar]")
          + (" [DRY-RUN]" if dry_run else ""))
    if node and node not in cfg["dirs"]:
        log.error(f"Bilinmeyen node: {node} — mevcut: {list(cfg['dirs'].keys())}")
        return

    if node:
        # Tek node: sadece o dizini tara
        new, changed, deleted, local = detect_changes_node(cfg, node)
    else:
        new, changed, deleted, local = detect_changes(cfg)

    # DRY-RUN: ne yapılacağını göster, hiçbir şeye dokunma (v1.4)
    if dry_run:
        print(f"  DRY-RUN: {len(new)} yeni, {len(changed)} değişen, "
              f"{len(deleted)} silinen push edilecek")
        for f in (new + changed)[:10]:
            print(f"    + {f}")
        if len(new) + len(changed) > 10:
            print(f"    ... ve {len(new)+len(changed)-10} dosya daha")
        for f in deleted[:10]:
            print(f"    - {f}")
        print("  DRY-RUN: manifest, GitHub ve GDrive'a HİÇBİR ŞEY yazılmadı")
        return

    # AKILLI GATE: kernel node'da kod değiştiyse önce build doğrula
    affected_kernel = (node in (None, "kernel")) and bool(new or changed)
    if affected_kernel and "kernel" in cfg["dirs"]:
        log.info("Kernel değişikliği tespit — build gate çalışıyor...")
        if not verify_build(cfg):
            log.error("Build FAIL — bozuk kod eşitlenmiyor! "
                      "Hata düzeltilmeden push YAPILMAYACAK.")
            # Manifest'e build_break kaydı (farkındalık)
            mf = load_manifest(cfg)
            mf["build_break"] = {
                "time": datetime.now().isoformat(),
                "machine": cfg["machine"],
                "new": len(new), "changed": len(changed),
            }
            save_manifest(cfg, mf)
            return  # PUSH DURDURULDU — veri bütünlüğü korundu
        else:
            log.info("Build PASS — kod sağlıklı, push devam")

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

    # AKILLI (v1.6): push sırasında kaynak + araç durumunu manifest'e ekle.
    # Karşı node 'pull' + 'propose' ile bunları okur; kurulum önerisi
    # CPU/GPU/RAM/disk kontrolünden geçirilir. Kurulum ASLA otomatik değil.
    mf["resources"] = resource_probe()
    mf["tools_state"] = scan_tools(cfg)
    mf["probe_time"] = datetime.now().isoformat()
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


def cmd_add_node(cfg, name, path, include="*", max_kb=1024):
    """
    Yeni node ekle — config.json'a yazar. Node sayısı SINIRSIZ.
    Kullanım: python3 sync_motor.py add-node docs --path ~/docs --include "*.md"
    """
    import json as _json
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "config.json")
    # Mevcut config'i yükle (varsa)
    user_cfg = {}
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                user_cfg = _json.load(f)
        except Exception:
            user_cfg = {}

    # Node ekle
    dirs = user_cfg.setdefault("dirs", {})
    if name in dirs:
        log.warning(f"Node zaten var: {name} (güncelleniyor)")
    dirs[name] = {
        "path": os.path.expanduser(path),
        "include": include.split(",") if isinstance(include, str) else include,
        "exclude_dirs": [".git", "build", "__pycache__"],
        "max_size_kb": max_kb,
        "gdrive": True,
    }

    with open(config_path, "w") as f:
        _json.dump(user_cfg, f, indent=2, ensure_ascii=False)
    log.info(f"Node eklendi: {name} → {path} (config.json)")
    log.info("Şimdi: python3 sync_motor.py push --node " + name)


def cmd_share(cfg, node, target_user):
    """
    Node'u başka kullanıcıyla PAYLAŞ — GDrive'a kopyalar.
    A kullanıcısının node'u → gdrive:hermes-sync/<target_user>/shared/<node>/
    Kullanım: python3 sync_motor.py share kernel --to ahmet
    """
    import shutil as _shutil
    if node not in cfg["dirs"]:
        log.error(f"Bilinmeyen node: {node}")
        return

    # En son versiyonu paylaşım alanına kopyala
    src_root = cfg["gdrive"]["versioned_dir"]
    dst_root = f"gdrive:hermes-sync/{target_user}/shared"
    out, rc = run_cmd(
        f'rclone copy "{src_root}/{node}/" "{dst_root}/{node}/" '
        f'--ignore-checksum --no-traverse', timeout=180, shell=True)
    if rc == 0:
        log.info(f"Node paylaşıldı: {node} → {target_user}/shared/{node}")
        log.info(f"Hedef kullanıcı çeker: sync_motor.py pull --from-shared {node}")
    else:
        log.error(f"Paylaşım başarısız: {out[:100]}")


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
                f'2>/dev/null | wc -l', timeout=30, shell=True)
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
        f'2>/dev/null | tail -1', timeout=30, shell=True)
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
        f'/tmp/sync_pull_{node}/ --ignore-checksum --no-traverse '
        f'--drive-acknowledge-abuse',
        timeout=180, shell=True)
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
            # SEKANSİYEL iterasyon: gzip akışı tek geçişte açılır.
            # Eski kod getmembers() + rastgele extractfile() yapıyordu;
            # gzip geriye seek desteklemediği için her üye baştan
            # açılıyordu → 420MB/5000 dosyalık arşivde O(n²) → saatlerce %100 CPU.
            for member in tf:
                if not member.isfile():
                    continue
                # Göreli yol — ./ önekini kaldır
                name = member.name.lstrip("./")
                if not name:
                    continue
                dest = os.path.join(target, name)
                # Çakışma kontrolü: hedef var + farklı içerik
                if os.path.exists(dest):
                    # Önce BOYUT: farklıysa içerik okumaya gerek yok (hızlı yol)
                    if os.path.getsize(dest) != member.size:
                        conflict = f"{dest}.conflict.{ts}"
                        shutil.copy2(dest, conflict)
                        log.warning(f"Çakışma: {name} → {conflict}")
                        continue  # yereli koru, uzak yazılmaz
                    src = tf.extractfile(member)
                    if src:
                        content = src.read()
                        local_content = open(dest, "rb").read()
                        if content == local_content:
                            # İçerik AYNI — yeniden yazmaya gerek yok (hızlı yol)
                            continue
                        # Çakışma — yerel korunur, kopya .conflict.TS ile saklanır
                        conflict = f"{dest}.conflict.{ts}"
                        shutil.copy2(dest, conflict)
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
    """Kernel pull sonrası build doğrulama — Cumulus kritik.
    PIPE BUG: 'make | tail' make RC'sini yutuyor → çıktı dosyaya yaz,
    RC doğrudan make'ten alınır."""
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
        # RC'yi doğrudan make'ten al — pipe YOK
        out, rc = run_cmd(
            f'cd "{pexp}" && make clean >/dev/null 2>&1 && '
            f'make >/tmp/sync_motor_build.log 2>&1; echo "RC=$?"',
            timeout=300, shell=True)
        # Son satırda RC=... var
        rc_line = [l for l in out.splitlines() if l.startswith("RC=")]
        build_rc = int(rc_line[-1].split("=")[1]) if rc_line else -1
        if build_rc != 0:
            log.error(f"Build BAŞARISIZ: {pexp} (RC={build_rc})")
            tail = "\n".join(out.splitlines()[-5:])
            log.error(f"Son çıktı: {tail[:200]}")
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


def cmd_probe(cfg):
    """Yerel kaynakları ve kurulu araçları ölç; manifest'e yaz (push ile paylaşılır)."""
    res = resource_probe()
    tools = scan_tools(cfg)
    mf = load_manifest(cfg)
    mf["resources"] = res
    mf["tools_state"] = tools
    mf["probe_time"] = datetime.now().isoformat()
    save_manifest(cfg, mf)

    print("\n  🧭 PROBE — Yerel Kaynaklar ve Araçlar\n")
    gpu_line = str(res["gpu_name"]) if res["gpu"] else "YOK"
    print(f"  CPU : {res['cpus']} çekirdek")
    print(f"  RAM : {res['ram_gb']:.1f} GB")
    print(f"  DISK: {res['disk_gb']:.1f} GB boş")
    nvidia_tag = " | NVIDIA VAR" if res.get("nvidia") else " | NVIDIA YOK"
    print(f"  GPU : {gpu_line}{nvidia_tag}")
    print("\n  Kurulu araçlar (katalog):")
    for name, t in sorted(tools.items()):
        mark = "✅" if t["installed"] else "⬜"
        gpu_tag = " [GPU]" if t["gpu"] else ""
        print(f"    {mark} {name}{gpu_tag}")
    print("\n  Manifest'e yazıldı — 'push' ile karşı node'a gider.")
    return 0


def cmd_propose(cfg):
    """Karşı node'un kurulu araçlarını KAYNAK KONTROLLÜ öneri olarak sun.

    GPU öncelikli: GPU gerektiren araçlar listede öne alınır; GPU'suz
    makinede GPU zorunlu araçlar 'kaynak engelli' bölümüne düşer.
    Kurulum burada HİÇBİR ŞEY yapmaz — sadece öneri listesi basar.
    """
    mf = load_manifest(cfg)
    remote_tools = mf.get("tools_state", {})
    remote_res = mf.get("resources", {})
    if not remote_tools:
        print("\n  💡 ÖNERİ — uzak node manifest'inde araç durumu YOK.\n"
              "  Karşı node'da önce 'probe' + 'push', sonra burada 'pull' "
              "çalıştırın.")
        return 0
    local_res = resource_probe()
    local_tools = scan_tools(cfg)

    print("\n  💡 ÖNERİ — Kaynak Kontrollü Kurulum Önerileri\n")
    print(f"  Bu makine : CPU {local_res['cpus']} | RAM {local_res['ram_gb']:.1f}GB "
          f"| DISK {local_res['disk_gb']:.1f}GB | "
          f"GPU {'VAR' if local_res['gpu'] else 'YOK'}")
    print(f"  Kaynak node: CPU {remote_res.get('cpus','?')} | "
          f"RAM {remote_res.get('ram_gb','?')}GB | "
          f"GPU {'VAR' if remote_res.get('gpu') else 'YOK'}")

    results = []
    for name, t in cfg.get("tools", {}).items():
        status, msg = propose_install(name, t, local_res, local_tools,
                                      remote_tools)
        if status in ("ALREADY", "NOT_ON_SOURCE"):
            continue
        results.append((name, status, msg, bool(t.get("gpu"))))

    # GPU öncelikli sıralama: INSTALLABLE önce (GPU olanlar içinde ilk),
    # sonra kaynak engelliler; aynı grup içinde GPU olanlar öne gelir.
    pri = {"INSTALLABLE": 0, "GPU_MISSING": 1, "DISK_INSUFFICIENT": 2,
           "RAM_INSUFFICIENT": 3, "CPU_INSUFFICIENT": 4}
    results.sort(key=lambda r: (pri.get(r[1], 5), 0 if r[3] else 1, r[0]))

    installable = [r for r in results if r[1] == "INSTALLABLE"]
    blocked = [r for r in results if r[1] != "INSTALLABLE"]

    print("\n  ✅ KURULABİLİR (kaynaklar yeterli):")
    if not installable:
        print("    (yok — karşı node'da kurulu ekstra araç bulunmuyor)")
    for name, status, msg, gpu in installable:
        tag = " [GPU-ÖNCELİKLİ]" if gpu else ""
        print(f"    ▶ {name}{tag}")
        print(f"      {cfg['tools'][name].get('desc','-')}")
        print(f"      kur: {cfg['tools'][name].get('install','(tanımsız)')}")
    print("\n  ⚠️  KAYNAK ENGELLİ (bu makinede önerilmez — neden):")
    if not blocked:
        print("    (yok)")
    reason = {"GPU_MISSING": "GPU yok", "DISK_INSUFFICIENT": "disk yetmez",
              "RAM_INSUFFICIENT": "RAM yetmez",
              "CPU_INSUFFICIENT": "CPU yetmez"}
    for name, status, msg, gpu in blocked:
        print(f"    ⛔ {name} [{reason.get(status, status)}]: {msg}")
    print("\n  Kurmak için: sync_motor.py apply --tool <ad> [--yes]")
    return 0


def cmd_apply(cfg, tool_name, yes=False):
    """Önerilen bir aracı KULLANICI ONAYI SONRASI kur. Non-destructive.

    Kurallar:
      - zaten kuruluysa RED (üzerine asla yazma)
      - kaynak yetersizse RED (GPU yok / disk / RAM / CPU)
      - --yes yoksa interaktif onay istenir; onay yoksa HİÇBİR ŞEY çalışmaz
      - kurulum komutu config'ten gelir (kullanıcının kendi kataloğu)
    """
    tools = cfg.get("tools", {})
    if tool_name not in tools:
        print(f"\n  ❌ Bilinmeyen araç: {tool_name} — katalog: {list(tools)}")
        return 1
    t = tools[tool_name]

    # 1) Zaten kurulu mu? → RED (non-destructive garantisi)
    if tool_installed(t):
        print(f"\n  ⛔ {tool_name} ZATEN KURULU — kurulum reddedildi "
              "(üzerine yazılmaz).")
        return 1

    # 2) Kaynak kontrolü — uzak durum gerekmez: bu makine yeterli mi?
    res = resource_probe()
    local_tools = scan_tools(cfg)
    fake_remote = {tool_name: {"installed": True}}
    status, msg = propose_install(tool_name, t, res, local_tools, fake_remote)
    if status in ("GPU_MISSING", "DISK_INSUFFICIENT", "RAM_INSUFFICIENT",
                  "CPU_INSUFFICIENT"):
        print(f"\n  ⛔ {tool_name} kurulamaz — {msg}")
        return 1

    # 3) Komutu göster, onay al
    inst = t.get("install", "")
    print(f"\n  🔧 KURULUM: {tool_name}")
    print(f"    açıklama   : {t.get('desc','-')}")
    print(f"    gereksinim : {t.get('min_ram_gb',0)}GB RAM | "
          f"{t.get('min_disk_gb',0)}GB disk | "
          f"CPU {t.get('min_cpus',1)}+ | "
          f"GPU={'gerekli' if t.get('gpu') else 'gerekmez'}")
    print(f"    komut      : {inst}")
    if not inst:
        print("  ❌ install komutu tanımsız — kurulum yapılamaz.")
        return 1
    if not yes:
        try:
            ans = input("  Onaylıyor musunuz? [e/Evet / h/Hayır] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("e", "evet", "y", "yes"):
            print("  Kurulum İPTAL — hiçbir şey değiştirilmedi (non-destructive).")
            return 1
    print("  Kurulum başlıyor...")
    out, rc = run_cmd(inst, timeout=600, shell=True)
    if rc != 0:
        print(f"  ❌ Kurulum BAŞARISIZ (rc={rc}):\n    {str(out)[-400:]}")
        return 1
    print(f"  ✅ {tool_name} kuruldu.\n    {str(out)[-200:]}")
    cmd_probe(cfg)   # durumu tazele (manifest'e yazar)
    return 0


def cmd_doctor(cfg):
    """Ortam sağlık kontrolü: bağımlılıklar + yapılandırma + bağlantılar (v1.4)."""
    import shutil
    ok = True
    print("\n  🩺 DOCTOR — Ortam Sağlık Kontrolü\n")

    # 1. Bağımlılıklar
    for tool in ("rclone", "git", "gh", "python3"):
        found = shutil.which(tool) is not None
        print(f"  {'✅' if found else '❌'} {tool}: {'mevcut' if found else 'YOK'}")
        if tool in ("rclone", "git") and not found:
            ok = False

    # 2. Yapılandırma — node dizinleri
    dirs = cfg.get("dirs", {})
    print(f"\n  📁 Node'lar ({len(dirs)}):")
    for name, d in dirs.items():
        path = d.get("path", "")
        paths = d.get("paths") or []
        targets = ([path] if path else []) + list(paths)
        if not targets:
            print(f"  ❌ {name}: yol tanımsız")
            ok = False
            continue
        for t in targets:
            exists = os.path.isdir(os.path.expanduser(t))
            print(f"  {'✅' if exists else '❌'} {name}: {t}")
            if not exists:
                ok = False

    # 3. GDrive remote
    out, rc = run_cmd("rclone listremotes", timeout=30, shell=True)
    gdrive = "gdrive:" in (out or "")
    print(f"\n  {'✅' if gdrive else '❌'} GDrive remote (rclone): "
          f"{'tanımlı' if gdrive else 'YOK'}")
    if not gdrive:
        ok = False

    # 4. GitHub repo erişimi
    repo = cfg.get("github", {}).get("repo", "")
    if repo:
        if not repo.startswith(("http://", "https://", "git@")):
            repo_url = f"https://github.com/{repo}.git"
        else:
            repo_url = repo
        out2, rc2 = run_cmd(f"git ls-remote {repo_url} HEAD", timeout=30, shell=True)
        print(f"  {'✅' if rc2 == 0 else '❌'} GitHub repo: {repo}")
        if rc2 != 0:
            ok = False
        # gh auth durumu (private repo için)
        gh_out, gh_rc = run_cmd("gh auth status", timeout=15, shell=True)
        gh_ok = gh_rc == 0
        print(f"  {'✅' if gh_ok else '⚠️'} gh auth: "
              f"{'oturum açık' if gh_ok else 'yok — private repo için gerekli'}")

    print(f"\n  SONUÇ: {'✅ SAĞLIKLI' if ok else '❌ SORUN VAR'}")
    return 0 if ok else 1


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
                                 "add-node", "share", "doctor", "version",
                                 "probe", "propose", "apply"])
    parser.add_argument("hedef", nargs="?",
                        help="add-node: node adı | share: node adı")
    parser.add_argument("--config", default=None,
                        help="config.json yolu")
    parser.add_argument("--node", default=None,
                        help="sadece belirli node'u eşitle (kernel, patent, "
                             "scripts, pcb, hermes, openclaw... veya add-node "
                             "ile eklenen herhangi biri)")
    parser.add_argument("--path", default=None,
                        help="add-node: yeni node dizini")
    parser.add_argument("--include", default="*",
                        help="add-node: dahil edilecek pattern (örn: *.md,*.txt)")
    parser.add_argument("--max-kb", type=int, default=1024,
                        help="add-node: maksimum dosya boyutu KB")
    parser.add_argument("--to", default=None,
                        help="share: hedef kullanıcı")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="debug log")
    parser.add_argument("--dry-run", action="store_true",
                        help="push/both: ne yapılacağını göster, HİÇBİR ŞEY yazma (v1.4)")
    parser.add_argument("--tool", default=None,
                        help="apply: kurulacak araç adı (katalogdan)")
    parser.add_argument("--yes", action="store_true",
                        help="apply: onay sormadan kur (varsayılan: interaktif onay)")
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
        cmd_push(cfg, node=args.node, dry_run=args.dry_run)
    elif args.komut == "pull":
        cmd_pull(cfg)
    elif args.komut == "both":
        cmd_push(cfg, node=args.node, dry_run=args.dry_run)
        if not args.dry_run:
            cmd_pull(cfg)
    elif args.komut == "doctor":
        return cmd_doctor(cfg)
    elif args.komut == "probe":
        return cmd_probe(cfg)
    elif args.komut == "propose":
        return cmd_propose(cfg)
    elif args.komut == "apply":
        if not args.tool:
            print("Kullanım: sync_motor.py apply --tool <ad> [--yes]")
            return 1
        return cmd_apply(cfg, args.tool, yes=args.yes)
    elif args.komut == "conflicts":
        cmd_conflicts(cfg)
    elif args.komut == "init":
        cmd_init(cfg)
    elif args.komut == "nodes":
        cmd_nodes(cfg)
    elif args.komut == "select":
        cmd_select(cfg)
    elif args.komut == "add-node":
        node_name = args.hedef or args.node
        if not node_name or not args.path:
            print("Kullanım: sync_motor.py add-node <ad> --path <dizin> "
                  "[--include '*.md,*.txt'] [--max-kb 1024]")
            return 1
        cmd_add_node(cfg, node_name, args.path, args.include, args.max_kb)
    elif args.komut == "share":
        node_name = args.hedef or args.node
        if not node_name or not args.to:
            print("Kullanım: sync_motor.py share <node> --to <kullanıcı>")
            return 1
        cmd_share(cfg, node_name, args.to)

    return 0


if __name__ == "__main__":
    sys.exit(main())
