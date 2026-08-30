#!/usr/bin/env python3
"""Retry/backoff birim testleri — rclone hata dayanıklılığı (v2.1.1).

Kapsam:
- sync_common_knowledge._run_rclone: okuma komutunda geçici hata → 1 retry
  → başarı; yazma komutuna retry YOK; timeout varsayılanı 180s.
- sync_motor.run_cmd: retries>0 sadece idempotent OKUMA komutlarında;
  yazma komutlarına ASLA retry; hata logu 'sync hata:' formatı.
"""
import json
import os
import sys
import types
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hermes_sync.sync_common_knowledge as ck
import hermes_sync.sync_motor as sm


class _FakeResult:
    def __init__(self, rc, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _make_fake_run(script, calls):
    """script: [(rc, out, err), ...] — her çağrıda sırayla döner.

    Sonuç dizisi biterse son eleman tekrar kullanılır.
    """

    def fake_run(cmd_args, capture_output=True, text=True, errors="replace",
                 timeout=60, **kw):
        calls.append(list(cmd_args))
        rc, out, err = script[min(len(calls) - 1, len(script) - 1)]
        return _FakeResult(rc, out, err)

    return fake_run


@pytest.fixture
def no_sleep(monkeypatch):
    """Retry beklemesini sıfırla (test hızı)."""
    monkeypatch.setattr(time, "sleep", lambda s: None)


# ─── sync_common_knowledge._run_rclone ──────────────────────────

def test_run_rclone_read_retry_success(monkeypatch, no_sleep):
    calls = []
    fake = _make_fake_run([(1, "", "connection reset"), (0, '{"ok":1}', "")], calls)
    monkeypatch.setattr(ck, "subprocess", types.SimpleNamespace(run=fake))
    rc, out, err = ck._run_rclone(["cat", "gdrive:hermes-sync/hahmet/shared/state.json"])
    assert rc == 0
    assert json.loads(out) == {"ok": 1}
    assert len(calls) == 2  # hata → retry → başarı


def test_run_rclone_read_retry_then_fail(monkeypatch, no_sleep):
    calls = []
    fake = _make_fake_run([(1, "", "HTTP 503 Service Unavailable"),
                           (1, "", "HTTP 503 Service Unavailable")], calls)
    monkeypatch.setattr(ck, "subprocess", types.SimpleNamespace(run=fake))
    rc, out, err = ck._run_rclone(["lsf", "gdrive:hermes-sync/hahmet/shared/tasks", "--files-only"])
    assert rc != 0
    assert len(calls) == 2  # yalnız 1 retry — üçüncü çağrı YOK
    assert "sync hata:" in err
    assert "rc=1" in err
    assert "retry=1" in err


def test_run_rclone_write_no_retry(monkeypatch, no_sleep):
    calls = []
    fake = _make_fake_run([(1, "", "connection reset")], calls)
    monkeypatch.setattr(ck, "subprocess", types.SimpleNamespace(run=fake))
    rc, out, err = ck._run_rclone(["copyto", "/tmp/x.json",
                                   "gdrive:hermes-sync/hahmet/shared/state.json"])
    assert rc != 0
    assert len(calls) == 1  # yazma komutu → retry YOK
    assert "sync hata:" in err


def test_run_rclone_not_found_no_retry(monkeypatch, no_sleep):
    """'not found' geçici hata DEĞİL — retry yok (fail-closed ayrımı korunur)."""
    calls = []
    fake = _make_fake_run([(1, "", "directory not found")], calls)
    monkeypatch.setattr(ck, "subprocess", types.SimpleNamespace(run=fake))
    rc, out, err = ck._run_rclone(["cat", "gdrive:hermes-sync/hahmet/none/shared/state.json"])
    assert rc != 0
    assert len(calls) == 1
    assert "sync hata:" in err


def test_run_rclone_default_timeout_180():
    import inspect
    sig = inspect.signature(ck._run_rclone)
    assert sig.parameters["timeout"].default == 180


# ─── sync_motor.run_cmd ─────────────────────────────────────────

def test_run_cmd_read_retry_success(monkeypatch, no_sleep):
    calls = []
    fake = _make_fake_run([(-1, "timeout", ""), (0, "saglikli", "")], calls)
    monkeypatch.setattr(sm, "subprocess", types.SimpleNamespace(run=fake))
    out, rc = sm.run_cmd("rclone cat gdrive:x/y", retries=1)
    assert rc == 0
    assert out == "saglikli"
    assert len(calls) == 2


def test_run_cmd_write_never_retries(monkeypatch, no_sleep):
    calls = []
    fake = _make_fake_run([(1, "", "connection reset")], calls)
    monkeypatch.setattr(sm, "subprocess", types.SimpleNamespace(run=fake))
    # retries=1 verilse bile yazma komutu (copy) retry YAPMAZ
    out, rc = sm.run_cmd("rclone copy /tmp/a gdrive:hermes-sync/hahmet", retries=1)
    assert rc == 1
    assert len(calls) == 1


def test_run_cmd_default_no_retry(monkeypatch, no_sleep):
    calls = []
    fake = _make_fake_run([(1, "", "HTTP 503")], calls)
    monkeypatch.setattr(sm, "subprocess", types.SimpleNamespace(run=fake))
    out, rc = sm.run_cmd("rclone cat gdrive:x/y")  # retries varsayılan 0
    assert rc == 1
    assert len(calls) == 1


def test_run_cmd_non_read_cmd_no_retry(monkeypatch, no_sleep):
    """'backup' yazma sayılır — ilk 3 token'da okuma yok → retry YOK."""
    calls = []
    fake = _make_fake_run([(-1, "timeout", "")], calls)
    monkeypatch.setattr(sm, "subprocess", types.SimpleNamespace(run=fake))
    out, rc = sm.run_cmd("rclone backup gdrive:x/y", retries=1)
    assert rc == -1
    assert len(calls) == 1


def test_run_cmd_retry_log_format(monkeypatch, no_sleep, caplog):
    """Log satırı: 'sync hata: <komut> rc=<rc> <süre>s retry=<n>'."""
    import logging
    calls = []
    fake = _make_fake_run([(-1, "timeout", ""), (0, "ok", "")], calls)
    monkeypatch.setattr(sm, "subprocess", types.SimpleNamespace(run=fake))
    with caplog.at_level(logging.WARNING, logger="sync_motor"):
        out, rc = sm.run_cmd("rclone cat gdrive:x/y", retries=1)
    assert rc == 0
    msgs = [r.getMessage() for r in caplog.records]
    retry_msg = [m for m in msgs if "retry=1/1" in m]
    assert retry_msg, f"retry log satırı bulunamadı: {msgs}"
    assert retry_msg[0].startswith("sync hata:")
    assert "rc=-1" in retry_msg[0]
    assert "s" in retry_msg[0]  # süre


def test_is_transient_classification():
    assert sm._is_transient_rc(-1, "")
    assert sm._is_transient_rc(1, "HTTP 503 Service Unavailable")
    assert sm._is_transient_rc(1, "connection reset by peer")
    assert sm._is_transient_rc(1, "i/o timeout")
    assert not sm._is_transient_rc(1, "directory not found")
    assert not sm._is_transient_rc(2, "file does not exist")
    assert ck._is_transient_rclone_error(-1, "")
    assert ck._is_transient_rclone_error(1, "HTTP 500 Internal Server Error")
    assert ck._is_transient_rclone_error(1, "connection refused")
    assert not ck._is_transient_rclone_error(1, "not found")
    assert not ck._is_transient_rclone_error(1, "invalid object name")
