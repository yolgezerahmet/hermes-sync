#!/usr/bin/env python3
"""H2 Synclave doğrulama script'i — her bileşeni kontrol eder (Windows uyumlu).

Kullanım: python h2_dogrula.py
Çıktı: PASS/FAIL satırları; hepsi PASS ise H2 yeni sisteme geçmiştir.
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

OK = FAIL = 0

def kontrol(ad, kosul, detay=""):
    global OK, FAIL
    if kosul:
        OK += 1
        print(f"  [PASS] {ad} {detay}")
    else:
        FAIL += 1
        print(f"  [FAIL] {ad} {detay}")

print("=== H2 SYNCLAVE DOĞRULAMA ===\n")

# 1) Kimlik dosyaları
id_dir = Path.home() / ".hermes" / "identity"
kontrol("kimlik dizini var", id_dir.exists())
kontrol("ed25519 anahtar", (id_dir / "agent_ed25519.key").exists())
kontrol("x25519 anahtar", (id_dir / "agent_x25519.key").exists())
kontrol("kimlik metadata", (id_dir / "agent_identity.json").exists())

# 2) Kimlik doğrulama (import + load)
sys.path.insert(0, str(Path(__file__).resolve().parent / "synclave_kod"))
try:
    import agent_identity as AI
    ident = AI.AgentIdentity.load_or_create()
    kontrol("kimlik yükleniyor", True, ident.agent_id)
    kontrol("klon durumu temiz", ident.meta.get("clone_state") == "clean",
            ident.meta.get("clone_state"))
except Exception as e:
    kontrol("kimlik yükleniyor", False, str(e)[:80])
    ident = None

# 3) A2A sunucusu (8643)
try:
    with socket.create_connection(("127.0.0.1", 8643), timeout=3):
        kontrol("A2A sunucusu 8643", True)
except Exception:
    kontrol("A2A sunucusu 8643", False, "çalışmıyor — agent_mesh_a2a.py başlat")

# 4) GPU agent (8644)
try:
    with socket.create_connection(("127.0.0.1", 8644), timeout=3):
        kontrol("GPU agent 8644", True)
except Exception:
    kontrol("GPU agent 8644", False, "kapalı — gpu_agent.py başlat + Ollama")

# 5) Ollama
try:
    import urllib.request
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
        d = json.loads(r.read().decode())
        modeller = [m["name"] for m in d.get("models", [])]
        kontrol("Ollama", True, f"model: {modeller[:3]}")
except Exception:
    kontrol("Ollama", False, "Ollama çalışmıyor — ollama serve")

# 6) Sohbet defteri
c_db = id_dir / "conversations.db"
kontrol("sohbet defteri db", c_db.exists(), f"{c_db.stat().st_size} bytes" if c_db.exists() else "")
if c_db.exists():
    import sqlite3
    try:
        c = sqlite3.connect(str(c_db))
        n = c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        m = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        kontrol("defter içeriği", True, f"{n} sohbet, {m} mesaj")
    except Exception as e:
        kontrol("defter içeriği", False, str(e)[:60])

# 7) Bağımlılıklar
for pkg in ("cryptography", "fastapi", "uvicorn", "requests"):
    try:
        __import__(pkg)
        kontrol(f"bağımlılık {pkg}", True)
    except ImportError:
        kontrol(f"bağımlılık {pkg}", False, f"pip install {pkg}")

print(f"\n=== SONUÇ: {OK} PASS, {FAIL} FAIL ===")
print("H2 YENİ SİSTEME GEÇTİ ✅" if FAIL == 0 else "EKSİKLER VAR — yukarıdaki FAIL satırlarına bak")
sys.exit(0 if FAIL == 0 else 1)
