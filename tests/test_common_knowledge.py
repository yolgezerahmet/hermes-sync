#!/usr/bin/env python3
"""Ortak akıl (state/task/failover) birim testleri — rclone yerel tmp ile mock'lu."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hermes_sync.sync_common_knowledge as ck


@pytest.fixture
def fake_hub(tmp_path, monkeypatch):
    """GDrive hub'ı yerel tmp dizine çevir (rclone çağrısı yok)."""
    hub = tmp_path / "hub"
    hub.mkdir()

    def fake_run_rclone(args, timeout=120):
        # args: ["cat", remote_path] vb. — yerel hub path'ini tanı
        remote = None
        for a in args:
            if isinstance(a, str) and str(hub) in a:
                remote = a.split(str(hub), 1)[-1].lstrip("/")
        if remote is None:
            return 0, "", ""
        local = hub / remote
        if "cat" in args:
            return (0, local.read_text(), "") if local.exists() else (1, "", "not found")
        if "copyto" in args:
            src = Path(args[args.index("copyto") + 1])
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(src.read_bytes())
            return 0, "", ""
        if "lsf" in args:
            # hub/shared/tasks/ altındaki json'ları listele
            tasks_dir = hub / "shared" / "tasks"
            if tasks_dir.exists():
                return 0, "\n".join(f.name for f in tasks_dir.glob("*.json")), ""
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(ck, "_run_rclone", fake_run_rclone)
    monkeypatch.setattr(ck, "_hub_base", lambda user=None: str(hub))
    return hub


def test_hlc_format():
    h = ck._hlc_value()
    assert "." in h and "-" in h  # 1788...0000-makine


def test_create_and_read_task(fake_hub):
    t = ck.create_task("t-1", "Görev 1")
    assert t["status"] == "pending"
    assert t["attempt"] == 0
    assert t["max_attempts"] == 3
    # tekrar oluşturma → hata
    with pytest.raises(ck.CommonKnowledgeError):
        ck.create_task("t-1", "Tekrar")


def test_claim_pending(fake_hub):
    ck.create_task("t-2", "Görev 2")
    r = ck.claim_task("t-2", owner="node-a")
    assert r["status"] == "running"
    assert r["owner"] == "node-a"
    # running → allow_stale=False iken devralınamaz
    r2 = ck.claim_task("t-2", owner="node-b")
    assert r2["owner"] == "node-a"


def test_done_terminal_korunur(fake_hub):
    ck.create_task("t-3", "Görev 3")
    ck.claim_task("t-3", owner="node-a")
    ck.done_task("t-3", owner="node-a")
    r = ck.claim_task("t-3", owner="node-b", allow_stale=True, force_stale=True)
    assert r["status"] == "done"  # terminal state geri alınamaz


def test_failover_stale(fake_hub, monkeypatch):
    ck.create_task("t-4", "Failover")
    ck.claim_task("t-4", owner="oldu-makine")
    # state.json'da "oldu-makine" yok → sahibi düştü
    monkeypatch.setattr(ck, "read_state",
                        lambda user=None: {"nodes": {"node-a": {}}})
    r = ck.claim_task("t-4", owner="node-a", allow_stale=True)
    assert r["owner"] == "node-a"
    assert r.get("failover") is True
    assert r.get("attempt") == 1


def test_max_attempts_fail(fake_hub, monkeypatch):
    ck.create_task("t-5", "Max attempts")
    ck.claim_task("t-5", owner="d1")
    monkeypatch.setattr(ck, "read_state", lambda user=None: {"nodes": {}})
    monkeypatch.setattr(ck, "_now_iso", lambda: "2099-01-01T00:00:00")
    # 3 deneme → failed
    for _ in range(3):
        r = ck.claim_task("t-5", owner="node-a", allow_stale=True, force_stale=True)
    assert r["status"] == "failed"


def test_list_tasks(fake_hub):
    ck.create_task("t-6", "Görev 6")
    tasks = ck.list_tasks()
    assert any(t["task_id"] == "t-6" for t in tasks)
