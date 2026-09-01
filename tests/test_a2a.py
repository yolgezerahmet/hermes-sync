#!/usr/bin/env python3
"""A2A mesh dispatch birim testleri — HTTP yok, dispatch doğrudan."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import synclave.agent_mesh_a2a as a2a


@pytest.fixture
def iso_inbox(tmp_path, monkeypatch):
    """Inbox + task store'u tmp dizine çevir."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(a2a, "INBOX_DIR", inbox)
    monkeypatch.setattr(a2a, "TASK_STORE", tmp_path / "tasks.json")
    a2a.TASKS = a2a._load_tasks()
    return inbox


def test_send_status(iso_inbox):
    r = a2a.dispatch("task/send", {"payload": {"action": "status"}})
    assert r["status"] == "completed"
    assert r["result"]["host"]


def test_send_note(iso_inbox):
    r = a2a.dispatch("task/send", {"payload": {"action": "note", "text": "selam"}})
    assert r["status"] == "completed"
    assert "inbox" in r["result"]


def test_async_mode(iso_inbox):
    r = a2a.dispatch("task/send", {"payload": {"action": "status"}, "mode": "async"})
    assert r["mode"] == "async"
    # arka plan thread'i bitmesini bekle
    import time
    time.sleep(0.5)
    g = a2a.dispatch("task/get", {"id": r["id"]})
    assert g["status"] == "completed"


def test_task_get_inbox_oncesi(iso_inbox):
    """Inbox'ta _task_id varsa TASKS'tan önce döner (işlenmiş sonuç)."""
    r = a2a.dispatch("task/send", {"payload": {"action": "note", "text": "görev"}})
    tid = r["id"]
    # inbox dosyasına işlenmiş sonuç yaz (worker simülasyonu)
    for f in iso_inbox.glob("*.json"):
        d = json.loads(f.read_text())
        if d.get("_task_id") == tid:
            d["status"] = "done"
            d["result"] = {"output": "worker çıktısı"}
            f.write_text(json.dumps(d))
    g = a2a.dispatch("task/get", {"id": tid})
    assert g["result"] == {"output": "worker çıktısı"}


def test_cancel(iso_inbox):
    r = a2a.dispatch("task/send", {"payload": {"action": "note", "text": "x"}, "mode": "async"})
    c = a2a.dispatch("task/cancel", {"id": r["id"]})
    assert c["status"] == "canceled"


def test_task_list(iso_inbox):
    """task/list: görev listesi döner (a2a_cli 'tasks' komutu / private TestA2ATaskList)."""
    r = a2a.dispatch("task/send", {"payload": {"action": "note", "text": "selam"}, "mode": "async"})
    lst = a2a.dispatch("task/list", {})
    assert "tasks" in lst
    assert isinstance(lst["tasks"], list)
    ids = [t["id"] for t in lst["tasks"]]
    assert r["id"] in ids
    # en yeni önce
    created = [t.get("created") or 0 for t in lst["tasks"]]
    assert created == sorted(created, reverse=True)


def test_unknown_method(iso_inbox):
    with pytest.raises(KeyError):
        a2a.dispatch("olmayan/metod", {})
