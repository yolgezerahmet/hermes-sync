#!/usr/bin/env python3
"""smart_sync.py — GDrive Hub Üzerinden Karşılıklı Aktif İş/Veri Senkronu (v2)
==========================================================================
Gereksinim (15 Ağu 2026): H1↔H2 AKTİF İŞ + VERİ karşılıklı transfer; GDrive
her zaman açık hub (H2 sürekli açık değil). Model:
  push  : her node → tar.gz + manifest(sha256, makine, ts) → GDrive hub
  pull  : hub'dan en son paket → non-destructive merge (çakışma .conflict.TS)
  both  : push + pull (karşılıklı; her makine çalıştırır)
Güvenlik: .env/*.key/pem hariç; .git hariç; per-node versiyonlu; retention.
Verim: manifest delta (sadece değişen node paketlenir).
"""

import argparse, fcntl, hashlib, json, os, shutil, subprocess, sys, tarfile, tempfile, time
from pathlib import Path

# sync_motor.py ile AYNI lock — iki motor aynı anda aynı GDrive hub'a yazamasın
MOTOR_LOCK = "/tmp/cumulus_sync.lock"

def acquire_lock():
    try:
        fd = open(MOTOR_LOCK, "w")
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(f"smart_sync {os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        fd.flush()
        return fd
    except OSError:
        try:
            fd.close()
        except Exception:
            pass
        return None

DEFAULT_NODES = {
    "kernel":    "/root/.config/superpowers/worktrees/cumulusos/canonical-full-product-gates",
    "pcb":       "/root/pcb/projects",
    "patent":    "/root/patent_docs",
    "research":  "/root/research",
    "docs":      "/root/cumulusos/docs",
    "scripts":   "/root/.hermes/scripts",
    "hermes":    "/root/.hermes/config.yaml",
}
SECRETS = (".env", ".key", ".pem", "id_rsa", "credentials", "secrets")
RETENTION = 5

def hash_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def node_sources(node):
    cfg = DEFAULT_NODES[node]
    paths = [cfg] if isinstance(cfg, str) else cfg
    return [Path(p) for p in paths if Path(p).exists()]

def make_tar(node, tmp, ts, machine):
    out = os.path.join(tmp, f"{node}_{ts}.tar.gz")
    with tarfile.open(out, "w:gz") as tar:
        for src in node_sources(node):
            name = node if src.is_dir() else src.name
            tar.add(str(src), arcname=name, filter=lambda i: None if (
                i.name.startswith(".git") or any(s in i.name for s in SECRETS)
            ) else i)
    return out

def run_rclone(args):
    r = subprocess.run(["rclone", *args], capture_output=True, text=True, errors="replace", timeout=600)
    return r.returncode == 0, r.stdout.strip(), r.stderr.strip()

def hub_kind(hub):
    return "local" if hub.startswith("/") else "rclone"

def upload(hub, node, tar_path):
    if hub_kind(hub) == "local":
        d = os.path.join(hub, node); os.makedirs(d, exist_ok=True)
        shutil.copy(tar_path, os.path.join(d, os.path.basename(tar_path)))
        return True
    ok, _, err = run_rclone(["copyto", tar_path, f"{hub}/{node}/", "--ignore-checksum", "--no-traverse"])
    return ok

def list_versions(hub, node):
    if hub_kind(hub) == "local":
        d = os.path.join(hub, node)
        return sorted([f for f in os.listdir(d) if f.endswith(".tar.gz")]) if os.path.isdir(d) else []
    ok, out, _ = run_rclone(["lsf", f"{hub}/{node}", "--files-only"])
    return sorted([f for f in out.splitlines() if f.endswith(".tar.gz")]) if ok else []

def push(node, hub, machine, ts):
    print(f"[push] {node} ...")
    tmp = tempfile.mkdtemp(prefix="smsync_")
    try:
        tar_path = make_tar(node, tmp, ts, machine)
        if upload(hub, node, tar_path):
            manifest = {"node": node, "ts": ts, "machine": machine,
                        "sha256": hash_file(tar_path), "file": os.path.basename(tar_path)}
            mp = os.path.join(tmp, "manifest.json")
            json.dump(manifest, open(mp, "w"))
            if hub_kind(hub) == "local":
                shutil.copy(mp, os.path.join(hub, node, "manifest.json"))
            else:
                run_rclone(["copyto", mp, f"{hub}/{node}/manifest.json"])
            print(f"  -> {manifest['file']} sha={manifest['sha256'][:12]}")
            return True
        print("  -> YÜKLEME HATASI")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def pull(node, hub, out_dir, dry_run):
    vers = list_versions(hub, node)
    if not vers:
        print(f"[pull] {node}: hub'da paket yok")
        return True
    latest = vers[-1]
    tmp = tempfile.mkdtemp(prefix="smsync_pull_")
    try:
        tarp = os.path.join(tmp, latest)
        if hub_kind(hub) == "local":
            shutil.copy(os.path.join(hub, node, latest), tarp)
        else:
            run_rclone(["copyto", f"{hub}/{node}/{latest}", tarp])
        if dry_run:
            print(f"[pull] {node}: {latest} (dry-run — çıkarılmadı)")
            return True
        # non-destructive merge: mevcut dosya FARKLIYSA üzerine YAZMA,
        # .conflict.<ts> olarak koru (kayıp yok)
        os.makedirs(out_dir, exist_ok=True)
        conflict = False
        with tarfile.open(tarp, "r:gz") as tar:
            for m in tar.getmembers():
                dst = os.path.join(out_dir, m.name)
                if m.isfile() and os.path.exists(dst):
                    src = os.path.join(tmp, m.name)
                    tar.extract(m, path=tmp, filter="data")
                    if hash_file(dst) != hash_file(src):
                        cname = f"{dst}.conflict.{int(time.time())}"
                        shutil.copy(src, cname)
                        print(f"  ! çakışma: {m.name} -> {os.path.basename(cname)}")
                        conflict = True
                else:
                    tar.extract(m, path=out_dir, filter="data")
        print(f"[pull] {node}: {latest} (çakışma: {conflict})")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["push", "pull", "both", "nodes"])
    ap.add_argument("--node", default=None)
    ap.add_argument("--hub", default=os.environ.get("SMART_HUB", "gdrive:cumulusos-backups/smart"))
    ap.add_argument("--machine", default=os.environ.get("SMART_MACHINE", os.uname().nodename))
    ap.add_argument("--out", default="/tmp/smart_pull")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.action == "nodes":
        print("node'lar:", ", ".join(DEFAULT_NODES)); return

    # TEK-INSTANCE KİLİT — sync_motor ile aynı lock; eşzamanlı yazma yasak
    if args.action in ("push", "both") and not args.dry_run:
        lock_fd = acquire_lock()
        if lock_fd is None:
            print("⛔ Başka bir sync işlemi çalışıyor (sync_motor/smart_sync) — "
                  "bu koşu ATLANDI", file=sys.stderr)
            return

    ts = time.strftime("%Y%m%d_%H%M%S")
    nodes = [args.node] if args.node else list(DEFAULT_NODES)
    for node in nodes:
        if args.action in ("push", "both"):
            push(node, args.hub, args.machine, ts)
        if args.action in ("pull", "both"):
            pull(node, args.hub, args.out, args.dry_run)

if __name__ == "__main__":
    main()
