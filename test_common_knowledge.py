#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_common_knowledge.py — E modülü (ortak akıl) testleri (2026-08-29)

Kapsam:
  1. update_state: HLC saatli makine bloğu merge + ts
  2. create_task: yeni görev pending; aynı id RED
  3. claim_task: pending → running (sahip atanır); başkası RED
  4. done_task: yalnız sahibi done yapabilir; başkası RED
  5. list_tasks: durumlar

KISIT: gerçek rclone/GDrive ÇALIŞTIRILMAZ — subprocess.run mock'lanır.
Mock, gdrive:hermes-sync/... yollarını yerel TMP/hub/ altına eşler.
Kullanım: python3 test_common_knowledge.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sync_common_knowledge as ck

TMP = tempfile.mkdtemp(prefix="ck_test_")
PASS = 0
HUB_ROOT = f"{ck.GDRIVE_HUB}/{ck.DEFAULT_USER}"
LOCAL_HUB = os.path.join(TMP, "hub")


def ok(name):
    global PASS
    PASS += 1
    print(f"  ✓ {name}")


def fail(name, detail=""):
    print(f"  ✗ FAIL: {name} {detail}")
    sys.exit(1)


def remote_to_local(remote: str) -> str:
    if not remote.startswith(HUB_ROOT + "/"):
        return None
    rel = remote[len(HUB_ROOT) + 1:]
    return os.path.join(LOCAL_HUB, *rel.split("/"))


class FakeProc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def fake_run(cmd, **kw):
    # cmd = ["rclone", <op>, ...]
    if cmd[0] != "rclone":
        return FakeProc(1, "", f"not rclone: {cmd}")
    op = cmd[1]
    if op == "cat":
        remote = cmd[2]
        lp = remote_to_local(remote)
        if lp and os.path.exists(lp):
            return FakeProc(0, open(lp).read())
        return FakeProc(1, "", "cat: yok")
    if op == "copyto":
        src, remote = cmd[2], cmd[3]
        lp = remote_to_local(remote)
        if lp is None:
            return FakeProc(1, "", f"kopyalanamaz: {remote}")
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        shutil.copy(src, lp)
        return FakeProc(0, "")
    if op == "lsf":
        remote_dir = cmd[2]
        lp = remote_to_local(remote_dir)
        if lp and os.path.isdir(lp):
            return FakeProc(0, "\n".join(sorted(os.listdir(lp))) + "\n")
        return FakeProc(0, "")
    return FakeProc(1, "", f"unknown op: {op}")


orig_run = subprocess.run
subprocess.run = fake_run
try:
    # ─── 1. STATE ──────────────────────────────────────────────
    print("── STATE ──")
    st = ck.update_state("h1", {"last_sync": "ok", "disk_gb": 105})
    nodes = st.get("nodes", {})
    if "h1" not in nodes:
        fail("h1 bloğu yok")
    if nodes["h1"].get("last_sync") != "ok":
        fail("blok içerik yazılmadı")
    if not nodes["h1"].get("hlc"):
        fail("HLC yok")
    ok("update_state: HLC saatli blok yazıldı")

    # merge: ikinci makine ekle, h1 korunur
    st2 = ck.update_state("h3", {"last_backup": "restic-ok"})
    if "h1" not in st2.get("nodes", {}) or "h3" not in st2.get("nodes", {}):
        fail("merge çalışmadı", str(st2.get("nodes", {}).keys()))
    ok("update_state: çoklu makine merge (h1+h3)")

    # ─── 2. CREATE ─────────────────────────────────────────────
    print("── TASK CREATE ──")
    t = ck.create_task("kernel-build", "Kernel build doğrula", sha="abc123")
    if t["status"] != "pending":
        fail("task pending değil", str(t))
    ok("create_task: pending görev oluştu")
    try:
        ck.create_task("kernel-build", "tekrar")
        fail("aynı task RED etmedi")
    except ck.CommonKnowledgeError:
        ok("create_task: aynı id → RED (üzerine yazmaz)")

    # ─── 3. CLAIM ──────────────────────────────────────────────
    print("── TASK CLAIM ──")
    claimed = ck.claim_task("kernel-build", owner="h1")
    if claimed["status"] != "running" or claimed["owner"] != "h1":
        fail("claim başarısız", str(claimed))
    ok("claim_task: pending → running (owner=h1)")

    # başkası claim edemez (running artık)
    claimed2 = ck.claim_task("kernel-build", owner="h3")
    if claimed2.get("owner") != "h1":
        fail("ikinci claim sahibi değiştirdi", str(claimed2))
    ok("claim_task: running görevi başkası alamaz (owner h1 kalır)")

    # ─── 4. DONE ───────────────────────────────────────────────
    print("── TASK DONE ──")
    try:
        ck.done_task("kernel-build", owner="h3")
        fail("başkası done yapabildi")
    except ck.CommonKnowledgeError:
        ok("done_task: yalnız sahibi (h1) done yapabilir")
    done = ck.done_task("kernel-build", owner="h1")
    if done["status"] != "done":
        fail("done olmadı", str(done))
    ok("done_task: sahibi done yaptı")

    # ─── 5. LIST ───────────────────────────────────────────────
    print("── TASK LIST ──")
    tasks = ck.list_tasks()
    if len(tasks) != 1 or tasks[0]["status"] != "done":
        fail("list_tasks yanlış", str(tasks))
    ok("list_tasks: 1 görev (done)")

    # ─── 6. FAIL-CLOSED ────────────────────────────────────────
    print("── FAIL-CLOSED ──")
    try:
        ck.done_task("var-olmayan", owner="h1")
        fail("olmayan task hata vermedi")
    except ck.CommonKnowledgeError:
        ok("fail-closed: olmayan task → CommonKnowledgeError")

finally:
    subprocess.run = orig_run

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n✅ TÜM TESTLER GEÇTİ — {PASS} PASS")
sys.exit(0)
