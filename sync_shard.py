#!/usr/bin/env python3
"""Shard manifest — OceanAPI #1 (28 Ağu 2026)
106K dosyalık TEK manifest yerine node başına ayrı JSON:
  manifest/sync_manifest.kernel.json
  manifest/sync_manifest.pcb.json
  ...
Sadece DEĞİŞEN node'un shard'ı commit edilir → GitHub 1MB limiti + ARG_MAX çözülür.
Ayrıca her shard'a sürüm damgası (ts + revision) → çoklu versiyonlama.
"""
import json, os, hashlib, datetime

MANIFEST_DIR = "manifest"

def shard_manifest(mf, nodes):
    """Tek manifest'i node başına shard'la"""
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    shards = {}
    for node in nodes:
        node_files = {}
        prefix = f"{node}/"
        for path, info in (mf.get("files", {}) or {}).items():
            if path.startswith(prefix):
                node_files[path[len(prefix):]] = info
        if not node_files:
            continue
        shard = {
            "node": node,
            "ts": ts,
            "revision": hashlib.sha256(json.dumps(node_files, sort_keys=True).encode()).hexdigest()[:12],
            "file_count": len(node_files),
            "files": node_files,
        }
        shard_path = os.path.join(MANIFEST_DIR, f"sync_manifest.{node}.json")
        with open(shard_path, "w") as f:
            json.dump(shard, f, indent=1, ensure_ascii=False)
        shards[node] = shard_path
    return shards

def load_shard(node):
    """Node shard'ını oku — manifest yerine"""
    path = os.path.join(MANIFEST_DIR, f"sync_manifest.{node}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)

def main():
    # Test: mevcut manifest'i shard'la
    local = os.path.expanduser("~/.hermes/state/sync_motor_manifest.json")
    if not os.path.exists(local):
        print("Manifest yok — sync_motor çalıştırınca oluşur")
        return
    with open(local) as f:
        mf = json.load(f)
    nodes = ["kernel", "pcb", "patent", "research", "scripts", "hermes",
             "hermes-skills", "openclaw", "hermes-sessions", "hermes-profile",
             "math", "sim"]
    shards = shard_manifest(mf, nodes)
    total = 0
    for node, path in shards.items():
        size = os.path.getsize(path)
        total += size
        print(f"  {node}: {size/1024:.1f} KB")
    print(f"Toplam: {len(shards)} shard, {total/1024/1024:.2f} MB (tek manifest: {os.path.getsize(local)/1024/1024:.2f} MB)")

if __name__ == "__main__":
    main()
