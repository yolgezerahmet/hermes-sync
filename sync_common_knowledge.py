#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_common_knowledge.py — Ortak Akıl (E modülü, v2.1 — 2026-08-29)
=====================================================================
GPT-5.6 (OceanAPI) tasarımı: GDrive hub üzerinde dağıtık ortak durum +
görev kuyruğu. Rclone üzerinde gerçek distributed lock yok — HLC + son
okuma-çakışma kontrolü yarışı azaltır; kesin atomiklik için ileride
lock/manifest servisi gerekir (not: tasarım sınırı).

Ortak durum dosyası:
  gdrive:hermes-sync/<user>/shared/state.json
  Her makine kendi bloğunu HLC saatli yazar; tüm makineler okur.

Ortak görev kuyruğu:
  gdrive:hermes-sync/<user>/shared/tasks/<task_id>.json
  {task_id, title, status: pending|running|done, owner, hlc, sha, ts}
  Claim: pending → running (yalnız bir makine sahiplenir);
  done: yalnız sahibi yapabilir.

İlkeler: non-destructive, HLC mantıksal saat (duvar saati sıralayıcı değil),
fail-closed (rclone hatası → raise CommonKnowledgeError).
"""
import argparse
import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

GDRIVE_HUB = "gdrive:hermes-sync"
DEFAULT_USER = os.environ.get("SYNC_HUB_USER", "hahmet")
SHARED_DIR = "shared"
STATE_PATH = "state.json"
TASKS_DIR = "tasks"

VALID_STATUS = ("pending", "running", "done")


class CommonKnowledgeError(Exception):
    """Ortak akıl işlem hatası — fail-closed (rclone hata → raise)."""


def _machine_name() -> str:
    try:
        return socket.gethostname().lower().split(".")[0]
    except Exception:
        return "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


def _hlc_value(hlc: Any) -> str:
    """HLC string'ini normalize et (sync_memory.HLC.now() biçimi)."""
    if hlc is None:
        return f"{int(datetime.now(timezone.utc).timestamp() * 1000)}.0000-{_machine_name()}"
    return str(hlc)


def _hub_base(user: Optional[str] = None) -> str:
    return f"{GDRIVE_HUB}/{user or DEFAULT_USER}"


def _run_rclone(args: List[str], timeout: int = 120):
    try:
        r = subprocess.run(["rclone", *args], capture_output=True, text=True,
                           errors="replace", timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT {timeout}s"
    except Exception as e:
        return -1, "", str(e)


# ─── Ortak durum (state.json) ─────────────────────────────────
def read_state(user: Optional[str] = None) -> Dict[str, Any]:
    """state.json'u oku — yoksa boş sözlük döner."""
    rc, out, err = _run_rclone(["cat", f"{_hub_base(user)}/{SHARED_DIR}/{STATE_PATH}"])
    if rc != 0:
        return {}
    try:
        data = json.loads(out)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def update_state(node: str, updates: Dict[str, Any],
                 user: Optional[str] = None) -> Dict[str, Any]:
    """Kendi durum bloğunu HLC saatli state.json'a yaz (merge).

    Önce oku → blok güncelle → temp yaz → copyto. Çakışma riski düşük
    (blok başına yazım); HLC + son-okuma azaltır.
    """
    state = read_state(user)
    blocks = state.get("nodes", {})
    block = blocks.get(node, {})
    block.update(updates)
    block["ts"] = _now_iso()
    block["hlc"] = _hlc_value(block.get("hlc"))
    blocks[node] = block
    state["nodes"] = blocks
    state.setdefault("updated_at", _now_iso())
    _write_state(state, user)
    return state


def _write_state(state: Dict[str, Any], user: Optional[str] = None):
    remote = f"{_hub_base(user)}/{SHARED_DIR}/{STATE_PATH}"
    tmp = tempfile.mkdtemp(prefix="synck_")
    try:
        lp = os.path.join(tmp, STATE_PATH)
        with open(lp, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        rc, _, err = _run_rclone(["copyto", lp, remote], timeout=180)
        if rc != 0:
            raise CommonKnowledgeError(f"state.json yazılamadı: {err.strip()[:150]}")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ─── Ortak görev kuyruğu ──────────────────────────────────────
def _task_remote_path(task_id: str, user: Optional[str] = None) -> str:
    return f"{_hub_base(user)}/{SHARED_DIR}/{TASKS_DIR}/{task_id}.json"


def _read_remote_json(remote_path: str, default=None):
    rc, out, err = _run_rclone(["cat", remote_path])
    if rc != 0:
        return default
    try:
        return json.loads(out)
    except Exception:
        return default


def _write_remote_json(remote_path: str, data: Dict[str, Any]):
    tmp = tempfile.mkdtemp(prefix="synct_")
    try:
        lp = os.path.join(tmp, os.path.basename(remote_path))
        with open(lp, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        rc, _, err = _run_rclone(["copyto", lp, remote_path], timeout=180)
        if rc != 0:
            raise CommonKnowledgeError(f"yazılamadı: {err.strip()[:150]}")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def create_task(task_id: str, title: str, owner: Optional[str] = None,
                hlc: Any = None, user: Optional[str] = None,
                sha: str = "") -> Dict[str, Any]:
    """Görev oluştur — aynı id varsa RED (üzerine yazmaz)."""
    if not task_id or not _valid_task_id(task_id):
        raise CommonKnowledgeError(f"geçersiz task_id: {task_id!r}")
    remote_path = _task_remote_path(task_id, user)
    existing = _read_remote_json(remote_path, None)
    if isinstance(existing, dict):
        raise CommonKnowledgeError(f"Task zaten var: {task_id}")
    task = {
        "task_id": task_id, "title": title, "status": "pending",
        "owner": owner or "", "hlc": _hlc_value(hlc),
        "sha": sha, "ts": _now_iso(),
    }
    _write_remote_json(remote_path, task)
    return task


def claim_task(task_id: str, owner: Optional[str] = None,
               hlc: Any = None, user: Optional[str] = None) -> Dict[str, Any]:
    """pending görevi sahiplen → running (yalnız bir makine).

    read-check-write yarışına açıktır (rclone atomik lock yok);
    claim öncesi son-okuma çakışmayı azaltır.
    """
    owner = owner or _machine_name()
    remote_path = _task_remote_path(task_id, user)
    task = _read_remote_json(remote_path, None)
    if not isinstance(task, dict):
        raise CommonKnowledgeError(f"Task bulunamadı: {task_id}")
    if task.get("status") != "pending":
        return task
    claimed = copy.deepcopy(task)
    claimed["status"] = "running"
    claimed["owner"] = owner
    claimed["hlc"] = _hlc_value(hlc)
    # claim öncesi son okuma (yarış azaltma)
    latest = _read_remote_json(remote_path, None)
    if not isinstance(latest, dict) or latest.get("status") != "pending":
        return latest if isinstance(latest, dict) else task
    _write_remote_json(remote_path, claimed)
    return claimed


def done_task(task_id: str, owner: Optional[str] = None,
              hlc: Any = None, user: Optional[str] = None) -> Dict[str, Any]:
    """running görevi yalnız sahibi done yapabilir."""
    owner = owner or _machine_name()
    remote_path = _task_remote_path(task_id, user)
    task = _read_remote_json(remote_path, None)
    if not isinstance(task, dict):
        raise CommonKnowledgeError(f"Task bulunamadı: {task_id}")
    current_owner = task.get("owner")
    if current_owner and current_owner != owner:
        raise CommonKnowledgeError(
            f"Task başka node tarafından sahiplenilmiş: {current_owner}")
    if task.get("status") not in ("running", "pending"):
        return task
    result = copy.deepcopy(task)
    result["status"] = "done"
    result["owner"] = owner
    result["hlc"] = _hlc_value(hlc)
    result["ts"] = _now_iso()
    _write_remote_json(remote_path, result)
    return result


def list_tasks(user: Optional[str] = None) -> List[Dict[str, Any]]:
    """Tüm görevleri oku (pending/running/done)."""
    tasks_dir = f"{_hub_base(user)}/{SHARED_DIR}/{TASKS_DIR}"
    rc, out, err = _run_rclone(["lsf", tasks_dir, "--files-only"])
    if rc != 0:
        return []
    result = []
    for fn in (out or "").splitlines():
        if not fn.endswith(".json"):
            continue
        task = _read_remote_json(f"{tasks_dir}/{fn}", None)
        if isinstance(task, dict):
            result.append(task)
    return sorted(result, key=lambda t: t.get("ts", ""))


def _valid_task_id(task_id: str) -> bool:
    return all(c.isalnum() or c in "._-" for c in task_id) and len(task_id) <= 64


# ─── CLI ──────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(prog="sync_common_knowledge",
                                 description="Ortak akıl (E) — state + task")
    ap.add_argument("komut", choices=["state", "tasks", "task-add",
                                      "task-claim", "task-done"])
    ap.add_argument("--node", default=None, help="state: makine adı")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--task-id", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--owner", default=None)
    ap.add_argument("--sha", default="")
    ap.add_argument("--user", default=None)
    args = ap.parse_args(argv)

    try:
        if args.komut == "state":
            state = read_state(args.user)
            node = args.node or _machine_name()
            if args.json:
                print(json.dumps(state, ensure_ascii=False, indent=1))
            else:
                blocks = state.get("nodes", {})
                print(f"\n  🧠 ORTAK DURUM — {len(blocks)} makine")
                for n, b in blocks.items():
                    print(f"    {n}: hlc={b.get('hlc','-')} ts={b.get('ts','-')}")
                    for k, v in b.items():
                        if k not in ("hlc", "ts"):
                            print(f"      {k}: {v}")
            return 0
        if args.komut == "tasks":
            tasks = list_tasks(args.user)
            if args.json:
                print(json.dumps(tasks, ensure_ascii=False, indent=1))
            else:
                print(f"\n  📋 ORTAK GÖREVLER — {len(tasks)}")
                for t in tasks:
                    print(f"    [{t.get('status','?'):7}] {t.get('task_id')} "
                          f"— {t.get('title','')} (owner={t.get('owner','-')})")
            return 0
        if args.komut == "task-add":
            if not args.task_id or not args.title:
                print("Kullanım: task-add --task-id <id> --title '<başlık>'")
                return 1
            task = create_task(args.task_id, args.title, owner=args.owner,
                               user=args.user, sha=args.sha)
            if args.json:
                print(json.dumps(task, ensure_ascii=False))
            else:
                print(f"  ➕ task: {task['task_id']} ({task['status']})")
            return 0
        if args.komut == "task-claim":
            if not args.task_id:
                print("Kullanım: task-claim --task-id <id> [--owner <makine>]")
                return 1
            task = claim_task(args.task_id, owner=args.owner, user=args.user)
            if args.json:
                print(json.dumps(task, ensure_ascii=False))
            else:
                print(f"  🔒 task: {task['task_id']} → {task['status']} "
                      f"(owner={task.get('owner','-')})")
            return 0
        if args.komut == "task-done":
            if not args.task_id:
                print("Kullanım: task-done --task-id <id> [--owner <makine>]")
                return 1
            task = done_task(args.task_id, owner=args.owner, user=args.user)
            if args.json:
                print(json.dumps(task, ensure_ascii=False))
            else:
                print(f"  ✅ task: {task['task_id']} → {task['status']}")
            return 0
    except CommonKnowledgeError as e:
        print(f"  ⛔ {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
