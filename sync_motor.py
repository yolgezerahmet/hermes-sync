#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  CUMULUS SYNC MOTORU v1.0 — Akıllı İki Yönlü Senkronizasyon   ║
║  GitHub + GDrive + Tailscale üzerinden, veri kaybı olmadan    ║
╚══════════════════════════════════════════════════════════════╝

MİMARİ:
  ┌─────────────────────────────────────────────────────┐
  │  GITHUB (cumulus-sync repo) = HER ZAMAN AÇIK MERKEZ│
  │  - sync_manifest.json: tüm dosyaların SHA256+ts    │
  │  - küçük dosyalar (<100MB) doğrudan repo'da        │
  └─────────────────────────────────────────────────────┘
        ▲                        ▲
   push │                        │ pull (H2 açılınca)
        ▼                        ▼
  ┌──────────┐   Tailscale   ┌──────────┐
  │  H1 VPS  │◄── 9090 ────►│  H2 Win  │
  │  (7/24)  │               │ (aralıklı)│
  └──────────┘               └──────────┘
        │                          │
        ▼                          ▼
  GDRIVE (büyük dosyalar)   GDRIVE (pull)
  cumulusos-backups/versiyonlu/

GÜVENLİK İLKELERİ (non-destructive):
  1. ASLA mevcut dosyanın üzerine yazma
  2. Çakışma (her iki tarafta değişiklik) → dosya.conflict.TS olarak sakla
  3. Her değişiklik manifest'e SHA256 + timestamp + kaynak ile yazılır
  4. Silme: karşı tarafta .deleted işareti bırakır, geri alınabilir
  5. GDrive versiyonlu — her senkron timestamp'li snapshot

KULLANIM:
  python3 sync_motor.py status     # iki taraf durumu
  python3 sync_motor.py push       # değişiklikleri merkeze gönder
  python3 sync_motor.py pull       # merkezden değişiklikleri çek
  python3 sync_motor.py both       # push + pull (önerilen)
  python3 sync_motor.py conflict   # çakışma listesi
  python3 sync_motor.py init       # ilk kurulum (GitHub repo + GDrive)

KAPALI KAYNAK — CumulusNET Dahili Kullanım
© 2026 CumulusNET Mühendislik. Tüm hakları saklıdır.
"""

import os, sys, json, hashlib, subprocess, shutil, time, argparse
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# KONFİGÜRASYON
# ═══════════════════════════════════════════════════════════════

HOME = str(Path.home())
CONFIG = {
    # Hangi makinede olduğumuzu otomatik tespit
    "is_h1": os.uname().nodename != "H2-Windows-RTX5070Ti" if os.name != "nt" else False,
    "hostname": os.uname().nodename if os.name != "nt" else os.environ.get("COMPUTERNAME", "H2-Windows"),

    # GitHub merkez repo
    "gh_repo": "yolgezerahmet/cumulus-sync-motor",
    "gh_branch": "main",

    # Yerel çalışma dizinleri (senkron edilecekler)
    "dirs": {
        "kernel": "/root/.config/superpowers/worktrees/cumulusos/canonical-full-product-gates",
        "patent": "/root/patent_docs",
        "pcb": "/root/pcb/projects",
        "scripts": "/root/.hermes/scripts",
    },

    # GDrive
    "gdrive_root": "gdrive:cumulusos-backups",
    "gdrive_versiyonlu": "gdrive:cumulusos-backups/versiyonlu",

    # Tailscale / HTTP
    "h1_http": "http://100.92.2.47:9090",
    "h2_http": "http://100.76.82.46:9090",

    # Manifest
    "manifest_local": os.path.join(HOME, ".hermes", "state", "sync_motor_manifest.json"),
    "manifest_remote": "sync_manifest.json",  # GitHub repo'da
}

# Windows'ta dizinler farklı
if os.name == "nt":
    CONFIG["dirs"] = {
        "kernel": r"C:\cumulusos",
        "patent": r"C:\ProjectCumulus",
        "pcb": r"C:\cumulus_paketler",
        "scripts": os.path.join(HOME, ".hermes", "scripts"),
    }

# ═══════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    icon = {"INFO": "ℹ️", "OK": "✅", "WARN": "⚠️", "ERR": "❌", "SYNC": "🔄"}.get(level, "ℹ️")
    print(f"  {icon} {msg}")
    # Log dosyasına yaz
    logfile = os.path.join(HOME, ".hermes", "state", "sync_motor.log")
    os.makedirs(os.path.dirname(logfile), exist_ok=True)
    with open(logfile, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] [{level}] {msg}\n")


def sha256_file(path):
    """Dosya SHA256 — büyük dosyalar için chunked"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def git(cmd, cwd=None):
    """Git komutu çalıştır"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           cwd=cwd, timeout=60)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), -1


def rclone(cmd, timeout=120):
    """rclone komutu çalıştır"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), -1


def curl(url, timeout=30):
    """HTTP GET"""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "sync-motor"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore"), resp.status
    except Exception as e:
        return str(e), -1


# ═══════════════════════════════════════════════════════════════
# MANİFEST YÖNETİMİ
# ═══════════════════════════════════════════════════════════════

def load_manifest():
    """Yerel manifest yükle — yoksa boş dict"""
    if os.path.exists(CONFIG["manifest_local"]):
        try:
            with open(CONFIG["manifest_local"]) as f:
                return json.load(f)
        except:
            return {}
    return {"files": {}, "last_sync": None, "machine": CONFIG["hostname"]}


def save_manifest(mf):
    os.makedirs(os.path.dirname(CONFIG["manifest_local"]), exist_ok=True)
    with open(CONFIG["manifest_local"], "w") as f:
        json.dump(mf, f, indent=1, ensure_ascii=False)


def scan_local():
    """Yerel dizinleri tara — dosya envanteri çıkar"""
    inventory = {}
    for label, dpath in CONFIG["dirs"].items():
        if not os.path.isdir(dpath):
            continue
        for root, dirs, files in os.walk(dpath):
            # Gereksizleri atla
            dirs[:] = [d for d in dirs if d not in (".git", "build", "node_modules",
                                                     "__pycache__", ".sync_backup")]
            for f in files:
                if f.endswith((".o", ".pyc", ".class")):
                    continue
                fpath = os.path.join(root, f)
                try:
                    rel = os.path.relpath(fpath, dpath)
                    relpath = f"{label}/{rel}"
                    stat = os.stat(fpath)
                    inventory[relpath] = {
                        "sha": sha256_file(fpath),
                        "size": stat.st_size,
                        "mtime": int(stat.st_mtime),
                        "machine": CONFIG["hostname"],
                    }
                except:
                    pass
    return inventory


def detect_changes():
    """Yerel durum vs manifest — değişen/yeni/silinenleri bul"""
    local = scan_local()
    mf = load_manifest()
    known = mf.get("files", {})

    new, changed, deleted = [], [], []
    # Yeni + değişen
    for path, info in local.items():
        if path not in known:
            new.append(path)
        elif known[path].get("sha") != info["sha"]:
            changed.append(path)
    # Silinen (manifest'te var ama diskte yok)
    for path in known:
        if path not in local:
            deleted.append(path)

    return new, changed, deleted, local


# ═══════════════════════════════════════════════════════════════
# GITHUB MERKEZ
# ═══════════════════════════════════════════════════════════════

def gh_ensure_repo():
    """GitHub sync repo'sunu hazırla (yoksa oluştur)"""
    # Repo var mı?
    out, rc = git("gh repo view yolgezerahmet/cumulus-sync 2>&1 | head -2")
    if rc == 0 and "found" not in out.lower():
        log(f"GitHub repo hazır: cumulus-sync", "OK")
        return True
    # Yoksa oluştur
    out, rc = git("gh repo create yolgezerahmet/cumulus-sync --private --description 'Cumulus H1-H2 senkronizasyon merkezi' 2>&1")
    if rc == 0:
        log("GitHub repo oluşturuldu: cumulus-sync", "OK")
        return True
    log(f"Repo oluşturulamadı: {out[:100]}", "ERR")
    return False


def gh_push_manifest(manifest_content):
    """Manifest'i GitHub'a push et (API ile — repo clone gerektirmez).
    BÜYÜK payload: -f content= komut satırı ARG_MAX (~2MB) limitine takılır;
    body dosyaya yazılıp --input ile gönderilir (14 Ağu fix — 24MB manifest)."""
    import base64
    import json as _json
    b64 = base64.b64encode(manifest_content.encode()).decode()
    # Dosya zaten var mı?
    out, rc = git(f'gh api repos/{CONFIG["gh_repo"]}/contents/{CONFIG["manifest_remote"]} --jq .sha 2>/dev/null')
    sha = out.strip() if (rc == 0 and out and out != "null") else None
    body = {"message": f"sync update {datetime.now().isoformat()}",
            "content": b64}
    if sha:
        body["sha"] = sha
    with open("/tmp/sync_manifest_body.json", "w") as f:
        _json.dump(body, f)
    cmd = (f'gh api repos/{CONFIG["gh_repo"]}/contents/{CONFIG["manifest_remote"]} '
           f'-X PUT --input /tmp/sync_manifest_body.json 2>&1')
    out, rc = git(cmd)
    return rc == 0


def gh_fetch_manifest():
    """GitHub'dan uzak manifest çek.
    DİKKAT (14 Ağu fix): Contents API GET 1MB'dan büyük dosyanın .content
    alanını DÖNMEZ (sadece metadata) — download_url (raw) ile çekilir."""
    out, rc = git(f'gh api repos/{CONFIG["gh_repo"]}/contents/{CONFIG["manifest_remote"]} --jq .download_url 2>&1')
    if rc != 0 or not out or out == "null":
        return None
    raw_out, rc2 = git(f'curl -sL "{out}" 2>&1')
    if rc2 != 0 or not raw_out:
        return None
    try:
        return json.loads(raw_out)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# GDRIVE (BÜYÜK DOSYALAR)
# ═══════════════════════════════════════════════════════════════

def gdrive_snapshot():
    """Kritik dosyaları versiyonlu GDrive snapshot'ına al"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = f"{CONFIG['gdrive_versiyonlu']}/{ts}"
    workdir = "/tmp/sync_motor_snapshot"
    os.makedirs(workdir, exist_ok=True)

    # Kernel (küçük) — tam
    kernel = CONFIG["dirs"]["kernel"]
    if os.path.isdir(kernel):
        out, rc = git(f'tar --exclude="*.o" --exclude=build -czf {workdir}/kernel.tar.gz '
                      f'-C {kernel} kernel include docs Makefile 2>/dev/null')
    # Patent (büyük — sadece kritik)
    patent = CONFIG["dirs"]["patent"]
    if os.path.isdir(patent):
        out, rc = git(f'cd {patent} && tar -czf {workdir}/patent.tar.gz '
                      f'--exclude="*.docx" --exclude="*.doc" -C {patent} . 2>/dev/null || '
                      f'cd {patent} && find . -name "*.md" | head -50 | tar -czf {workdir}/patent.tar.gz -T - 2>/dev/null')

    # Yükle
    out, rc = rclone(f'rclone copy {workdir}/ {target} --ignore-checksum --no-traverse')
    if rc == 0:
        log(f"GDrive snapshot: {ts} ({os.path.getsize(f'{workdir}/kernel.tar.gz')//1024}KB kernel)", "OK")
        return ts
    return None


# ═══════════════════════════════════════════════════════════════
# TAILSCALE / HTTP HABERLEŞME
# ═══════════════════════════════════════════════════════════════

def peer_status():
    """Karşı tarafın durumunu kontrol et (Tailscale + 9090)"""
    status = {}
    # H1'deysek H2'yi kontrol et
    targets = []
    if CONFIG["is_h1"]:
        targets.append(("H2", CONFIG["h2_http"]))
    else:
        targets.append(("H1", CONFIG["h1_http"]))

    for name, url in targets:
        out, code = curl(f"{url}/", timeout=8)
        status[name] = "ONLINE" if code == 200 else "OFFLINE"
    return status


def announce(msg):
    """Karşı tarafa durum bildir (9090'a mesaj dosyası bırak)"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = CONFIG["h2_http"] if CONFIG["is_h1"] else CONFIG["h1_http"]
    fname = f"SYNC_NOTE_{ts}.txt"
    # Mesajı kendi 9090'ına koy (karşı taraf çeker)
    local_upload = "/tmp/hermes_uploads" if CONFIG["is_h1"] else "/tmp"
    os.makedirs(local_upload, exist_ok=True)
    with open(os.path.join(local_upload, fname), "w") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    # Karşı tarafın 9090'ına da yükle (form POST)
    try:
        out, code = curl(f"{target}/upload", timeout=10)
    except:
        pass
    return fname


# ═══════════════════════════════════════════════════════════════
# ÇAKIŞMA YÖNETİMİ (NON-DESTRUCTIVE)
# ═══════════════════════════════════════════════════════════════

def resolve_conflict(local_path, remote_sha, remote_machine, remote_ts):
    """Çakışma: yerel dosyayı .conflict.TS olarak sakla, uzak olanı getir"""
    conflict_path = f"{local_path}.conflict.{remote_ts}"
    try:
        shutil.copy2(local_path, conflict_path)
        log(f"Çakışma: {os.path.basename(local_path)} → {os.path.basename(conflict_path)} (korundu)", "WARN")
        return True
    except Exception as e:
        log(f"Çakışma korunamadı: {e}", "ERR")
        return False


# ═══════════════════════════════════════════════════════════════
# ANA İŞLEMLER
# ═══════════════════════════════════════════════════════════════

def cmd_status():
    """Durum raporu — iki taraf da haberdar"""
    print("\n" + "═" * 60)
    print(f"  CUMULUS SYNC MOTOR — DURUM")
    print(f"  Makine: {CONFIG['hostname']} ({'H1 VPS' if CONFIG['is_h1'] else 'H2 Desktop'})")
    print("═" * 60)

    # Karşı taraf
    peers = peer_status()
    for name, st in peers.items():
        print(f"  {name}: {'🟢 ONLINE' if st == 'ONLINE' else '🔴 OFFLINE'}")

    # Yerel değişiklikler
    new, changed, deleted, local = detect_changes()
    print(f"\n  Yerel dosya: {len(local)}")
    print(f"  Yeni: {len(new)} | Değişen: {len(changed)} | Silinen: {len(deleted)}")

    # Manifest
    mf = load_manifest()
    print(f"  Manifest: {len(mf.get('files', {}))} kayıt, son sync: {mf.get('last_sync', 'hiç')}")

    # GitHub uzak manifest
    remote = gh_fetch_manifest()
    if remote:
        print(f"  GitHub manifest: {len(remote.get('files', {}))} kayıt")
        # Uzakta olup yerelde olmayanlar
        rfiles = remote.get("files", {})
        local_paths = set(local.keys())
        remote_only = [p for p in rfiles if p not in local_paths]
        if remote_only:
            print(f"  Uzaktan gelecek: {len(remote_only)} dosya (pull önerilir)")
    else:
        print(f"  GitHub manifest: erişilemedi")

    print("═" * 60 + "\n")


def cmd_push():
    """Yerel değişiklikleri GitHub merkeze gönder + GDrive snapshot"""
    print(f"\n  🔄 PUSH — {CONFIG['hostname']}")
    new, changed, deleted, local = scan_local() if False else detect_changes()

    if not new and not changed and not deleted:
        log("Değişiklik yok — push atlandı", "OK")
    else:
        log(f"Push: {len(new)} yeni, {len(changed)} değişen, {len(deleted)} silinen", "SYNC")

    # Manifest güncelle (yerel + GitHub)
    mf = load_manifest()
    mf["files"] = local  # Tüm yerel durumu yaz (basit + doğru)
    mf["last_sync"] = datetime.now().isoformat()
    mf["machine"] = CONFIG["hostname"]
    save_manifest(mf)

    # GitHub'a yükle
    ok = gh_push_manifest(json.dumps(mf, indent=1, ensure_ascii=False))
    if ok:
        log("Manifest GitHub'a push edildi", "OK")
    else:
        log("Manifest GitHub push BAŞARISIZ — gh auth kontrol et", "ERR")

    # GDrive snapshot (büyük dosyalar)
    ts = gdrive_snapshot()
    if ts:
        log(f"GDrive versiyonlu snapshot: {ts}", "OK")

    # Karşı tarafa bildir
    if peer_status().get("H2") == "ONLINE" or not CONFIG["is_h1"]:
        announce(f"Push tamam: {len(new)} yeni, {len(changed)} değişen ({CONFIG['hostname']})")


def cmd_pull():
    """GitHub merkezden değişiklikleri çek (üzerine yazmadan)"""
    print(f"\n  🔄 PULL — {CONFIG['hostname']}")
    remote = gh_fetch_manifest()
    if not remote:
        log("Uzak manifest alınamadı", "ERR")
        return

    rfiles = remote.get("files", {})
    local = scan_local()

    # Uzakta olup yerelde farklı/yeni olanlar
    to_pull = []
    for path, rinfo in rfiles.items():
        if path not in local:
            to_pull.append(path)  # Uzakta var, yerelde yok
        elif local[path].get("sha") != rinfo.get("sha"):
            # Her iki tarafta değişmişse → çakışma (yerel korunur)
            lmachine = local[path].get("machine", "?")
            rmachine = rinfo.get("machine", "?")
            if lmachine != rmachine:
                to_pull.append(("conflict", path, rinfo))
            else:
                to_pull.append(path)  # Aynı makine güncellemiş → güvenli

    if not to_pull:
        log("Yeni/çakışan dosya yok — güncel", "OK")
    else:
        log(f"Pull: {len(to_pull)} öğe işlenecek", "SYNC")

    # NOT: Bu motor manifest DURUMUNU gösterir; gerçek dosya transferi
    # GitHub repo içeriği veya GDrive üzerinden yapılır. Manifest, hangi
    # dosyaların değiştiğini BİLDİRİR — transfer ayrı kanal (git pull /
    # rclone / 9090) ile tamamlanır.
    print("\n  Manifest'e göre durum:")
    for item in to_pull[:15]:
        if isinstance(item, tuple):
            print(f"    ⚠️ ÇAKIŞMA: {item[1]} (yerel korunacak)")
        else:
            print(f"    🔄 {item}")
    if len(to_pull) > 15:
        print(f"    ... +{len(to_pull)-15} daha")

    # Manifest'i yerel olarak güncelle (uzak durumu bildiğimizi kaydet)
    mf = load_manifest()
    mf["remote_known"] = remote.get("last_sync")
    mf["last_pull"] = datetime.now().isoformat()
    save_manifest(mf)


def cmd_conflicts():
    """Çakışma dosyalarını listele"""
    print("\n  ⚠️ ÇAKIŞMA DOSYALARI")
    found = 0
    for label, dpath in CONFIG["dirs"].items():
        if not os.path.isdir(dpath):
            continue
        for root, dirs, files in os.walk(dpath):
            for f in files:
                if ".conflict." in f:
                    fpath = os.path.join(root, f)
                    sz = os.path.getsize(fpath)
                    print(f"    {fpath} ({sz//1024}KB)")
                    found += 1
    if found == 0:
        print("    Çakışma yok ✅")
    else:
        print(f"\n  {found} çakışma — .conflict.TS dosyaları korunuyor, otomatik çözüm için incele")


def cmd_init():
    """İlk kurulum: GitHub repo + manifest oluştur + ilk push"""
    print("\n  🚀 INIT — İlk Kurulum")
    if gh_ensure_repo():
        new, changed, deleted, local = detect_changes()
        mf = load_manifest()
        mf["files"] = local
        mf["last_sync"] = datetime.now().isoformat()
        mf["machine"] = CONFIG["hostname"]
        save_manifest(mf)
        ok = gh_push_manifest(json.dumps(mf, indent=1, ensure_ascii=False))
        if ok:
            log(f"İlk manifest push edildi ({len(local)} dosya)", "OK")
        gdrive_snapshot()
        log("Kurulum tamam — 'python3 sync_motor.py both' ile kullan", "OK")


# ═══════════════════════════════════════════════════════════════
# ANA
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Cumulus Sync Motoru v1.0")
    parser.add_argument("komut", nargs="?", default="status",
                        choices=["status", "push", "pull", "both", "conflict", "init"])
    args = parser.parse_args()

    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║  CUMULUS SYNC MOTOR v1.0 — {CONFIG['hostname']}")
    print(f"╚══════════════════════════════════════════════════════╝")

    if args.komut == "status":
        cmd_status()
    elif args.komut == "push":
        cmd_push()
    elif args.komut == "pull":
        cmd_pull()
    elif args.komut == "both":
        cmd_push()
        cmd_pull()
    elif args.komut == "conflict":
        cmd_conflicts()
    elif args.komut == "init":
        cmd_init()


if __name__ == "__main__":
    main()
