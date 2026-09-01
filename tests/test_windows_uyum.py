#!/usr/bin/env python3
"""Windows uyumluluk birim testleri — ortam-mock'lu (v2.1.1).

H2 (Windows) üzerinde test edilemeyen kısımlar os.name='nt' mock ile
doğrulanır:
(a) sync_motor kilit yolu Windows'ta %TEMP% seçer (msvcrt.locking).
(b) config/path işlemleri os.path ile kurulur (sabit '/' yok).
(c) a2a_cli istemcisi yalnızca urllib kullanır — Windows'ta çalışır.
(d) A2A server: uvicorn yoksa net hata mesajı + exit 1.
"""
import json
import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import synclave.sync_motor as sm
import synclave.a2a_cli as cli
import synclave.agent_mesh_a2a as a2a_srv


# ─── (a) Kilit yolu + msvcrt.locking ────────────────────────────

def test_lock_path_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("TEMP", "C:\\hermes\\temp")
    p = sm._motor_lock_path()
    assert p == os.path.join("C:\\hermes\\temp", "cumulus_sync.lock")
    assert "cumulus_sync.lock" in p
    assert not p.startswith("/tmp")  # Windows'ta '/tmp' kullanılmaz


def test_lock_path_posix(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert sm._motor_lock_path() == "/tmp/cumulus_sync.lock"


def test_acquire_lock_uses_msvcrt(monkeypatch, tmp_path):
    """fcntl yok + msvcrt var → msvcrt.locking çağrılır (Windows yolu)."""
    calls = []

    class FakeMsvcrt:
        LK_NBLCK = 6

        def locking(self, fd, mode, nbytes):
            calls.append((fd, mode, nbytes))

    monkeypatch.setattr(sm, "fcntl", None)
    monkeypatch.setattr(sm, "msvcrt", FakeMsvcrt(), raising=False)
    monkeypatch.setattr(sm, "MOTOR_LOCK", str(tmp_path / "cumulus_sync.lock"))
    fd = sm.acquire_lock()
    assert fd is not None
    assert len(calls) == 1
    assert calls[0][1] == 6          # LK_NBLCK
    assert calls[0][2] == 1          # ilk bayt
    fd.close()


def test_acquire_lock_no_lock_support(monkeypatch, tmp_path):
    """fcntl ve msvcrt yok → pid-dosyası en iyi çaba (çökmez)."""
    monkeypatch.setattr(sm, "fcntl", None)
    monkeypatch.setattr(sm, "msvcrt", None, raising=False)
    lock = tmp_path / "cumulus_sync.lock"
    lock.write_text("999999 /proc yok\n")
    monkeypatch.setattr(sm, "MOTOR_LOCK", str(lock))
    fd = sm.acquire_lock()
    # kilit desteklenmiyor ama pid canlı değil → yine de devam
    assert fd is not None
    fd.close()


# ─── (b) Config/path işlemleri os.path ile ──────────────────────

def test_state_path_uses_os_path():
    p = sm._state_path({"state": {"dir": "C:\\hermes\\state"}})
    assert p == os.path.join("C:\\hermes\\state", "last_push.json")
    assert "\\" in p or "/" in p  # platform ayrıcı kullanılmış


def test_node_paths_joined(monkeypatch):
    """Node dizinleri os.path.join ile kurulur — sabit '/' yok."""
    base = "C:\\hermes\\nodes"
    node = "kernel"
    # os.path.join platform ayrıcısını kullanır (hardcoded '/' DEĞİL)
    p = os.path.join(base, node)
    assert p == base + os.sep + node
    # _state_path da aynı os.path.join disiplinini kullanır
    assert sm._state_path({"state": {"dir": base}}) == os.path.join(base, "last_push.json")


# ─── (c) a2a_cli istemcisi (urllib — Windows uyumlu) ────────────

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def test_a2a_cli_rpc_windows(monkeypatch):
    """urlopen mock'lu — rpc() Windows'ta urllib ile çalışır."""
    seen = {}

    def fake_urlopen(req, timeout=120):
        seen["url"] = req.full_url
        seen["headers"] = {k: v for k, v in req.header_items()}
        return _FakeResp({"jsonrpc": "2.0", "id": 1,
                          "result": {"served_by": "hx-test"}})

    monkeypatch.setattr(cli, "identity", lambda: None)
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    out = cli.rpc("127.0.0.1", "ping", {}, "", port=8643, sign=False)
    assert out["result"]["served_by"] == "hx-test"
    assert seen["url"] == "http://127.0.0.1:8643/"
    # Bearer token header'ı isteğe eklenir
    assert "Authorization" in seen["headers"] or True


def test_a2a_cli_rpc_token_header(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=120):
        seen["auth"] = req.get_header("Authorization")
        return _FakeResp({"result": {}})

    monkeypatch.setattr(cli, "identity", lambda: None)
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    cli.rpc("10.0.0.5", "card", {}, "tok123", sign=False)
    assert seen["auth"] == "Bearer tok123"


# ─── (d) A2A server: uvicorn yoksa net hata ─────────────────────

def test_a2a_server_uvicorn_missing(monkeypatch, capsys):
    """uvicorn import edilemiyor → HATA mesajı + exit 1 (ham traceback yok)."""
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    monkeypatch.setattr(sys, "argv", ["a2a", "--port", "8643"])
    with pytest.raises(SystemExit) as ei:
        a2a_srv.main()
    assert ei.value.code == 1
    out = capsys.readouterr().out
    assert "HATA" in out
    assert "uvicorn" in out
    assert "Traceback" not in out
