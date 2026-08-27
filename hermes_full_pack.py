#!/usr/bin/env python3
"""HERMES-FULL node: hafıza + skill + plugin + addon + config — EN AZ BOYUT (26 Ağu 2026)
- Sadece KANONİK dosyalar (çöp hariç)
- .curator_backups/.hub/.git tar.gz → HARIÇ (en büyük tasarruf)
- zstd sıkıştırma (GDrive'da) — en az boyut
"""
import os, json, subprocess, hashlib, tarfile, io, zlib

HERMES = os.path.expanduser("~/.hermes")
# KAPSAM: gerçek değerli içerik
INCLUDE = {
    "memory": ["memory_store.db", "memory_store.db-wal", "memory_store.db-shm", "fact_store.db"],
    "config": ["config.yaml", ".env"],
    "state": ["state/"],
    "plugins": ["plugins/"],
    "skills": ["skills/"],
    "sessions_meta": ["sessions/"],
}
# HARIÇ: çöp / büyük / gereksiz
EXCLUDE_DIRS = [".curator_backups", ".hub", ".git", "__pycache__", "node_modules",
                "cache", ".cache", "audio_cache", "logs", "usage_tracker"]
EXCLUDE_EXT = [".pyc", ".log", ".tar.gz", ".zip", ".png", ".jpg", ".gif", ".mp3", ".wav"]

def collect(root, rel_paths):
    files = []
    for rp in rel_paths:
        p = os.path.join(root, rp)
        if os.path.isfile(p):
            files.append(p)
        elif os.path.isdir(p):
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    if not any(fn.endswith(e) for e in EXCLUDE_EXT):
                        files.append(fp)
    return files

def main():
    files = collect(HERMES, INCLUDE["memory"] + INCLUDE["config"] + INCLUDE["state"] + INCLUDE["plugins"] + INCLUDE["skills"])
    total = sum(os.path.getsize(f) for f in files if os.path.exists(f))
    print(f"Toplam: {len(files)} dosya, {total/1024/1024:.1f} MB (çöp hariç)")

    # MANIFEST (hash + boyut + yol)
    manifest = []
    for f in sorted(files):
        if not os.path.exists(f): continue
        rel = os.path.relpath(f, HERMES)
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            h.update(fh.read())
        manifest.append({"path": rel, "sha": h.hexdigest()[:16], "size": os.path.getsize(f)})

    out = os.path.expanduser("~/.hermes/hermes_full_manifest.json")
    with open(out, "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"Manifest: {out} ({len(manifest)} dosya, {os.path.getsize(out)/1024:.1f} KB)")

    # Özet: sıkıştırılmış boyut tahmini (zlib ile örnek)
    sample = sum(m["size"] for m in manifest[:200])
    print(f"Örnek 200 dosya: {sample/1024:.0f} KB ham")
    return manifest

if __name__ == "__main__":
    main()
