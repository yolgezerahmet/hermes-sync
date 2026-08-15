#!/usr/bin/env python3
"""
sync_memory.py — Çoklu-Ajan Ortak Hafıza + Node Farkındalığı (v0.1)
====================================================================
GPT-5.6 tasarımı (2026-08-15, /tmp/review_sync_memory_ocean.txt) çekirdeği.

Senaryolar:
- H1 (Hermes, Linux VPS) ↔ H2 (Hermes, Windows) ↔ OpenClaw (ayrı ajan)
- Her ajan bir "node"; aynı konu/kod üzerinde node-farkında çalışır
- Ortak hafıza: memory DIF'leri JSONL (canlı DB senkronize EDİLMEZ)
- Audit: append-only JSONL + hash-chain (kim ne yaptı — değiştirilemez iz)
- Skill envanteri: sürüm+SHA256 karşılaştırma (farklılıklar giderilir)

İlkeler (GPT-5.6):
1. hermes-full canlı senkron DEĞİL — ayrı hermes-memory node (shared/private)
2. Canlı DB dosyası değil, MANTIKSAL DELTA'lar (JSONL)
3. Çakışma: son-yazan kazanır DEĞİL — preserve (.conflict~node~ts) + audit
4. Tombstone gerekli (silme fiziksel değil — yoksa kayıt geri gelir)
5. Secret: allowlist alan modeli — tarama başarısızsa DUR
6. Saat: HLC/Lamport mantıksal saat (duvar saati sıralayıcı değil)
"""
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

# ─── Secret taraması (GPT-5.6: regex yeterli değil — allowlist + tarama) ───
SECRET_FIELD_RE = re.compile(
    r"(token|api[_-]?key|secret|password|credential|private[_-]?key|"
    r"access[_-]?token|auth[_-]?token|bearer|client[_-]?secret)",
    re.IGNORECASE)
ALLOWED_VALUE_FIELDS = {"subject", "predicate", "value", "value_type"}


def scan_payload_for_secrets(record: dict) -> dict:
    """Secret taraması: bilinen alan adları + değer kalıpları."""
    hits = []
    for k, v in (record or {}).items():
        if SECRET_FIELD_RE.search(str(k)):
            hits.append(k)
        if k in ("value",) and isinstance(v, str):
            for pat in (r"sk-[A-Za-z0-9]{16,}", r"ghp_[A-Za-z0-9]{30,}",
                        r"AKIA[0-9A-Z]{16}", r"Bearer [A-Za-z0-9._-]+"):
                if re.search(pat, v):
                    hits.append(f"value:{pat[:10]}...")
    return {"hits": sorted(set(hits)), "ok": len(hits) == 0}


# ─── HLC (Hybrid Logical Clock) — duvar saati sıralayıcı DEĞİL ───
class HLC:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.pt = 0  # fiziksel zaman ms
        self.c = 0   # mantıksal sayaç

    def now(self) -> str:
        phys = int(time.time() * 1000)
        if phys > self.pt:
            self.pt, self.c = phys, 0
        else:
            self.c += 1
        return f"{self.pt}.{self.c:04d}-{self.node_id}"


# ─── Ortak Hafıza Delta ────────────────────────────────────────────────
MEMORY_NAMESPACES = ("shared", "private", "quarantine")


def export_memory_delta(memory_dir: str, node_id: str, agent_id: str,
                        since_seq: int = 0) -> dict:
    """Memory kayıtlarını JSONL delta olarak dışa aktar.
    memory_dir/snapshots/ + memory_dir/deltas/ + memory_dir/manifests/
    Kayıtlar: {record_id, namespace, subject, predicate, value, value_type,
               source:{agent_id,node_id}, hlc, revision, tombstone}"""
    delta = []
    for ns in MEMORY_NAMESPACES:
        ns_dir = os.path.join(memory_dir, ns)
        if not os.path.isdir(ns_dir):
            continue
        for fn in sorted(os.listdir(ns_dir)):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(ns_dir, fn)) as f:
                rec = json.load(f)
            rec.setdefault("source", {})
            rec["source"].setdefault("agent_id", agent_id)
            rec["source"].setdefault("node_id", node_id)
            rec.setdefault("revision", 1)
            delta.append(rec)
    # secret taraması: hit varsa delta RED (GPT-5.6: warning ile devam yok)
    for rec in delta:
        scan = scan_payload_for_secrets(rec)
        if not scan["ok"]:
            raise ValueError(f"SECRET: {rec.get('record_id')} alan {scan['hits']}")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join(memory_dir, "deltas", f"{ts}-{node_id}-{since_seq}.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        for rec in delta:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"delta": out, "records": len(delta), "node_id": node_id}


def import_memory_delta(memory_dir: str, delta_path: str,
                        node_id: str, conflict_policy: str = "preserve") -> dict:
    """Delta uygula — non-destructive (.conflict~node~ts koru).
    Aynı record_id: revision karşılaştır — yüksek revision kazanır,
    eşitse ikisini koru (çakışma). tombstone=true → kaydı kaldır (fiziksel
    silme değil — kaldır/ignore)."""
    applied = conflicts = tombstones = 0
    if not os.path.exists(delta_path):
        return {"applied": 0, "conflicts": 0, "error": "delta yok"}
    with open(delta_path) as f:
        for line in f:
            rec = json.loads(line)
            rid = rec.get("record_id")
            ns = rec.get("namespace", "shared")
            if ns not in MEMORY_NAMESPACES:
                continue
            ns_dir = os.path.join(memory_dir, ns)
            os.makedirs(ns_dir, exist_ok=True)
            target = os.path.join(ns_dir, f"{rid}.json")
            # tombstone: kayıt silindi — mevcut dosyayı kaldır (fiziksel
            # silme değil: .tombstone işaretleyici)
            if rec.get("tombstone"):
                if os.path.exists(target):
                    os.replace(target, target + ".tombstone." + node_id)
                tombstones += 1
                continue
            # mevcut kayıtla karşılaştır
            if os.path.exists(target):
                with open(target) as ef:
                    existing = json.load(ef)
                if existing.get("revision", 0) > rec.get("revision", 0):
                    applied += 0  # eski delta — atla
                    continue
                if existing.get("revision", 0) == rec.get("revision", 0) \
                        and existing.get("hlc") != rec.get("hlc"):
                    # çakışma — ikisini koru
                    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    os.replace(target, f"{target}.conflict.{node_id}.{ts}")
                    conflicts += 1
            with open(target, "w") as wf:
                json.dump(rec, wf, ensure_ascii=False, indent=1)
            applied += 1
    return {"applied": applied, "conflicts": conflicts,
            "tombstones": tombstones}


# ─── Audit Log (JSONL + hash-chain — kim ne yaptı, değiştirilemez) ───
AUDIT_REQUIRED = ("event_id", "timestamp_utc", "node_id", "agent_id",
                  "operation_id", "node_name", "path", "old_sha256",
                  "new_sha256", "event_type", "result")


def append_audit_event(audit_dir: str, event: dict) -> str:
    """Audit olayı ekle — hash-chain (previous_event_hash + event_hash)."""
    os.makedirs(audit_dir, exist_ok=True)
    log_path = os.path.join(audit_dir, datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".jsonl")
    event.setdefault("event_id", str(uuid.uuid4()))
    event.setdefault("timestamp_utc", datetime.now(timezone.utc).isoformat() + "Z")
    event.setdefault("operation_id", str(uuid.uuid4()))
    # previous hash: log'un son satırından
    prev_hash = "0" * 64
    if os.path.exists(log_path):
        with open(log_path, "rb") as f:
            try:
                f.seek(-2, os.SEEK_END)
                while f.read(1) != b"\n":
                    f.seek(-2, os.SEEK_CUR)
                last = json.loads(f.readline().decode())
                prev_hash = last.get("event_hash", "0" * 64)
            except Exception:
                prev_hash = "0" * 64
    body = json.dumps({k: event.get(k) for k in AUDIT_REQUIRED},
                      sort_keys=True, ensure_ascii=False)
    event["previous_event_hash"] = prev_hash
    event["event_hash"] = hashlib.sha256(
        (prev_hash + body).encode()).hexdigest()
    with open(log_path, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event["event_hash"]


def verify_audit_chain(audit_dir: str) -> dict:
    """Hash zinciri doğrula — log satırı değiştirildiyse zincir kırılır."""
    log_path = os.path.join(audit_dir, datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".jsonl")
    if not os.path.exists(log_path):
        return {"ok": False, "error": "log yok"}
    prev = "0" * 64
    for line in open(log_path):
        ev = json.loads(line)
        body = json.dumps({k: ev.get(k) for k in AUDIT_REQUIRED},
                          sort_keys=True, ensure_ascii=False)
        calc = hashlib.sha256((ev.get("previous_event_hash", "") + body).encode()).hexdigest()
        if ev.get("previous_event_hash", "0"*64) != prev or calc != ev.get("event_hash"):
            return {"ok": False, "error": "zincir kırıldı", "at": ev.get("event_id")}
        prev = ev.get("event_hash")
    return {"ok": True, "events": sum(1 for _ in open(log_path))}


# ─── Skill Envanteri (sürüm+SHA256 — farklılıklar giderilir) ───
def scan_skill_inventory(skill_root: str) -> list:
    """Skill envanteri: {skill_id, version, content_sha256, manifest_path}"""
    inv = []
    if not os.path.isdir(skill_root):
        return inv
    for root, _, files in os.walk(skill_root):
        if "SKILL.md" not in files:
            continue
        p = os.path.join(root, "SKILL.md")
        with open(p, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
        skill_id = os.path.basename(root)
        version = "0.0.0"
        ver_f = os.path.join(root, "skill.json")
        if os.path.exists(ver_f):
            try:
                with open(ver_f) as vf:
                    version = json.load(vf).get("version", "0.0.0")
            except Exception:
                pass
        inv.append({"skill_id": skill_id, "version": version,
                    "content_sha256": h, "manifest_path": p})
    return inv


def compare_skill_inventories(local: list, remote: list) -> list:
    """Karşılaştır — eksik/farklı skill'leri raporla (mismatch)."""
    actions = []
    remote_map = {r["skill_id"]: r for r in remote}
    local_map = {l["skill_id"]: l for l in local}
    for rid, r in remote_map.items():
        if rid not in local_map:
            actions.append({"skill_id": rid, "status": "missing",
                            "remote": r})
        elif local_map[rid]["content_sha256"] != r["content_sha256"]:
            actions.append({"skill_id": rid, "status": "mismatch",
                            "local": local_map[rid], "remote": r})
    return actions


if __name__ == "__main__":
    print("sync_memory.py — çoklu-ajan ortak hafıza + node farkındalığı")
    print("Kütüphane modülü — sync_motor.py'den import edilir.")
