#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_motor v1.7.0 — P2P Mesh node hazırlama
Gerçek node dizinlerini P2P dizinine sembolik bağlar (H3'ten çekilebilir).
Kullanım: python3 p2p_export.py [node...]  (hepsi: no arg)
"""
import os, sys, json

SYNC_ROOT = os.path.expanduser("~/cumulus-sync-motor/p2p")
CFG = os.path.expanduser("~/cumulus-sync-motor/config.json")

cfg = json.load(open(CFG))
dirs = cfg.get("dirs", {})
os.makedirs(SYNC_ROOT, exist_ok=True)

# Sadece H1'de paylaşılabilir node'lar (küçük/önemli)
PAYLASILABILIR = ["patent", "research", "scripts", "hermes-skills"]

hedefler = sys.argv[1:] or PAYLASILABILIR
out = []
for node in hedefler:
    if node not in dirs:
        out.append(f"✗ {node}: config'de yok")
        continue
    src = dirs[node]["path"]
    dst = os.path.join(SYNC_ROOT, node)
    if not os.path.isdir(src):
        out.append(f"✗ {node}: kaynak yok ({src})")
        continue
    if os.path.islink(dst):
        os.unlink(dst)
    try:
        os.symlink(src, dst)
        out.append(f"✅ {node}: {src} → p2p/{node}")
    except Exception as e:
        out.append(f"✗ {node}: {e}")

print("\n".join(out))
print(f"\nP2P dizini: {SYNC_ROOT}")
print("Uzak makineden: sync_p2p.py p2p-pull <node> <makine>")
