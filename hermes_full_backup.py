#!/usr/bin/env python3
"""TÜM HERMES + OPENCLAW — EN AZ BOYUTLU GDRIVE VERSİYONLU YEDEK (26 Ağu 2026)
H1/H2/H3'ten toplar → zstd sıkıştırır → GDrive versiyonlu + manifest
Kapsam: memory + config + skills (çöpsüz) + plugins + openclaw + addons
"""
import os, json, subprocess, hashlib, tarfile, sys, glob
from datetime import datetime

HERMES = os.path.expanduser("~/.hermes")
OPENCLAW = os.path.expanduser("~/.openclaw")
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
GDRIVE = f"gdrive:hermes-sync/hahmet/{os.uname().nodename}/versiyonlu/hermes-full/{TS}"

# Hariç tutulacak çöp (en büyük tasarruf)
EXCLUDE_DIRS = [".curator_backups", ".hub", ".git", "__pycache__", "node_modules",
                "cache", ".cache", "audio_cache", "logs", "usage_tracker", "state"]
EXCLUDE_EXT = [".pyc", ".log", ".tar.gz", ".zip"]

def collect_files(root, subdirs, prefix):
    files = []
    for sd in subdirs:
        p = os.path.join(root, sd)
        if not os.path.exists(p):
            continue
        if os.path.isfile(p):
            files.append((p, f"{prefix}/{os.path.basename(p)}"))
        elif os.path.isdir(p):
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    if not any(fn.endswith(e) for e in EXCLUDE_EXT):
                        rel = os.path.relpath(fp, root)
                        files.append((fp, f"{prefix}/{rel}"))
    return files

def make_tar(files, out_path):
    """zstd en yüksek sıkıştırma — en az boyut (ARG_MAX güvenli: -T listesi)"""
    # Dosya listesini geçici dosyaya yaz (ARG_MAX aşımı önlenir)
    list_file = out_path + ".list"
    with open(list_file, "w") as lf:
        for src, arc in files:
            lf.write(f"{src}\n")
    # tar -T ile: sadece kaynak listesi; arcname transform kullanılmaz
    # Bunun yerine her dosyayı geçici dizine kopyalayıp oradan paketlemek en temiz
    import shutil, tempfile
    tmpdir = tempfile.mkdtemp(prefix="hermes_full_")
    for src, arc in files:
        dst = os.path.join(tmpdir, arc)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except Exception:
            pass
    cmd = ["tar", "--zstd", "-cf", out_path, "-C", tmpdir, "."]
    subprocess.run(cmd, capture_output=True, timeout=600)
    shutil.rmtree(tmpdir, ignore_errors=True)
    if os.path.exists(list_file):
        os.remove(list_file)
    return os.path.getsize(out_path)

def main():
    print(f"=== HERMES+OPENCLAW YEDEK {TS} ===")
    files = []
    # Hermes: memory + config + skills + plugins (çöpsüz)
    files += collect_files(HERMES, ["memory_store.db", "fact_store.db", "config.yaml", ".env",
                                     "skills", "plugins"], "hermes")
    # OpenClaw: tümü
    if os.path.exists(OPENCLAW):
        files += collect_files(OPENCLAW, ["skills", "config.json", "memory", "settings.json"], "openclaw")
    total = sum(os.path.getsize(f) for f, _ in files if os.path.exists(f))
    print(f"Dosya: {len(files)} | Ham: {total/1024/1024:.1f} MB")

    out = f"/tmp/hermes_full_{TS}.tar.zst"
    size = make_tar(files, out)
    print(f"ZSTD: {size/1024/1024:.1f} MB (sıkıştırma: %{100*size/total:.0f})")

    # SHA256
    sha = hashlib.sha256(open(out, "rb").read()).hexdigest()[:16]
    print(f"SHA: {sha}")

    # GDrive yükle
    r = subprocess.run(["rclone", "copy", out, GDRIVE, "--ignore-checksum"],
                       capture_output=True, timeout=300)
    print(f"GDrive: {'OK' if r.returncode == 0 else 'HATA ' + r.stderr.decode()[:200]}")

    # Manifest GDrive'a
    man = {"ts": TS, "machine": os.uname().nodename, "files": len(files),
           "raw_mb": round(total/1024/1024, 1), "zstd_mb": round(size/1024/1024, 1),
           "sha": sha, "retention": "7g günlük + 8h haftalık + 12ay aylık"}
    open("/tmp/hermes_full_latest.json", "w").write(json.dumps(man, indent=2))
    subprocess.run(["rclone", "copyto", "/tmp/hermes_full_latest.json",
                    "gdrive:hermes-sync/hahmet/hermes-full-latest.json", "--ignore-checksum"],
                   capture_output=True, timeout=120)
    print(f"Manifest: {json.dumps(man, ensure_ascii=False)}")
    # Temizlik
    os.remove(out)
    print("TAMAM")

if __name__ == "__main__":
    main()
