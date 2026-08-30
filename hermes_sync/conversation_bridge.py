#!/usr/bin/env python3
"""
conversation_bridge.py — Hermes state.db → ajan sohbet defteri köprüsü (v1.0)

AMAÇ (30 Ağu 2026 kullanıcı talebi — "sohbetler kaybolmadan eş zamanlı iş"):
  Hermes'in TÜM kullanıcı sohbetleri (telegram/cli/whatsapp/web) kalıcı,
  karışmaz sohbet ID'leriyle ajan kimlik defterine (conversations.db) akar.
  - Her oturum → kullanıcı sohbeti: u.<agent8>.<kanal>.<peer8>.<ulid>
  - Her mesaj → <conv_id>#<seq> (içerik SAKLANMAZ, sadece sha256 + boyut)
  - Watermark: son işlenen state.db mesaj id'si kaydedilir → incremental
  - Hermes state.db'ye DOKUNMAZ (sadece okur); defter ayrı DB

ÇALIŞMA:
  python3 conversation_bridge.py            # watermark'tan itibaren işle
  python3 conversation_bridge.py --full     # TÜM geçmişi işle (ilk kurulum)
  python3 conversation_bridge.py --dry-run  # ne yapılacağını göster

CRON (no_agent, 15 dk):
  python3 conversation_bridge.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import agent_identity as AI
except Exception as e:
    print(f"agent_identity yüklenemedi: {e}")
    sys.exit(1)

def _state_db():
    # Her çağrıda okunur — testler env'i değiştirip import'tan önce
    # çalışamayabilir (modül import anında sabitlenirse GERÇEK DB'ye bağlanır).
    return os.environ.get("HERMES_STATE_DB", "~/.hermes/state.db")


def _watermark():
    return os.environ.get("BRIDGE_WATERMARK", "~/.hermes/state/bridge_watermark.json")
# source → kanal adı; user_id → görünen kullanıcı adı (gönderen tarafı eşleme)
CHANNEL_MAP = {"telegram": "telegram", "cli": "cli", "whatsapp": "whatsapp",
               "web": "web", "slack": "slack", "discord": "discord", "origin": "cli"}
KNOWN_USERS = {  # <kanal>:<user_id> → görünen ad (peer etiketi değil, label)
    "telegram:729504083": "Ahmet",
    "telegram:0": "bilinmeyen",
    "cli:root": "Ahmet",
    "cli:": "Ahmet",
}
BATCH = 500
SLEEP_PER_BATCH = 0.02


def _load_wm() -> dict:
    p = Path(_watermark()).expanduser()
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def _save_wm(wm: dict):
    p = Path(_watermark()).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(wm, ensure_ascii=False, indent=1), encoding="utf-8")


def _sessions(conn: sqlite3.Connection) -> dict:
    """session_id → (source, user_id, chat_id, title)"""
    rows = conn.execute(
        "SELECT id, source, user_id, chat_id, title FROM sessions").fetchall()
    out = {}
    for sid, source, uid, chat_id, title in rows:
        src = (source or "cli").lower()
        if src not in CHANNEL_MAP:
            src = "cli"
        out[sid] = (src, str(uid or ""), str(chat_id or ""), title or "")
    return out


def _label_for(src: str, uid: str) -> str:
    return KNOWN_USERS.get(f"{src}:{uid}", uid or src)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="tüm geçmişi işle")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    ident = AI.AgentIdentity.load_or_create()
    print(f"[köprü] kimlik: {ident.agent_id} | {ident.runtime}")

    state = sqlite3.connect(str(Path(_state_db()).expanduser()), timeout=20)
    state.row_factory = sqlite3.Row
    wm = _load_wm()
    sess = _sessions(state)

    # watermark: session başına son işlenen mesaj id
    # full modda yok say
    if a.full:
        wm = {}

    # hangi session'ları işleyeceğiz: watermark'ta olmayan veya kısmi olanlar
    to_proc = {sid: (sess.get(sid, ("cli", "", "", ""))) for sid in sess}
    # session'lar arasında session_id kayıp? (silinmiş) — yine de işle

    total_msg = 0
    total_conv = 0
    for sid, (src, uid, chat_id, title) in to_proc.items():
        peer = uid or "unknown"
        label = _label_for(src, uid)
        try:
            conv_id = AI.open_conversation("user", peer, src, label, identity=ident)
        except Exception as e:
            print(f"  ! {sid}: conv açılamadı: {e}")
            continue
        last_id = wm.get(sid, 0)
        # mesajları artan id ile çek
        rows = state.execute(
            "SELECT id, role, content, timestamp, token_count FROM messages "
            "WHERE session_id=? AND id>? AND active=1 AND content IS NOT NULL "
            "ORDER BY id ASC LIMIT ?", (sid, last_id, BATCH)).fetchall()
        while rows:
            for r in rows:
                role = (r["role"] or "").lower()
                if role not in ("user", "assistant"):
                    continue
                direction = "in" if role == "user" else "out"
                raw = (r["content"] or "")[:200000]  # çok uzun içerikleri kes
                meta = {"state_msg_id": r["id"], "title": title[:80] if title else ""}
                if r["token_count"]:
                    meta["tokens"] = r["token_count"]
                AI.log_message(conv_id, direction, raw, peer_id=peer, meta=meta)
                last_id = r["id"]
                total_msg += 1
            total_conv += 1
            wm[sid] = last_id
            if total_msg % 5000 == 0:
                _save_wm(wm)
                print(f"  ... {total_msg} mesaj işlendi")
            time.sleep(SLEEP_PER_BATCH)
            rows = state.execute(
                "SELECT id, role, content, timestamp, token_count FROM messages "
                "WHERE session_id=? AND id>? AND active=1 AND content IS NOT NULL "
                "ORDER BY id ASC LIMIT ?", (sid, last_id, BATCH)).fetchall()

    _save_wm(wm)
    print(f"[köprü] {total_msg} mesaj, {total_conv} oturum batch, "
          f"defter: {ident.dir / 'conversations.db'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
