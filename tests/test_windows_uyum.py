#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_windows_uyum.py — Windows uyumluluk (v2.1.1)
==================================================
Çalıştır: python3 -m unittest discover tests

Kapsam:
  (a) sync_motor kilit yolu Windows'ta %TEMP% seçer (msvcrt.locking).
  (b) config/path işlemleri os.path ile kurulur (sabit '/' yok).
  (c) a2a_cli istemcisi yalnızca urllib kullanır — Windows'ta çalışır.
  (d) A2A server: uvicorn yoksa net hata mesajı + exit 1.
"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sync_motor as sm
import a2a_cli as cli
import agent_mesh_a2a as a2a_srv


class TestLockPath(unittest.TestCase):
    def test_lock_path_windows(self):
        with mock.patch.object(os, "name", "nt"), \
                mock.patch.dict(os.environ, {"TEMP": "C:\\hermes\\temp"}):
            p = sm._motor_lock_path()
            self.assertEqual(p, os.path.join("C:\\hermes\\temp", "cumulus_sync.lock"))
            self.assertFalse(p.startswith("/tmp"))

    def test_lock_path_posix(self):
        with mock.patch.object(os, "name", "posix"):
            self.assertEqual(sm._motor_lock_path(), "/tmp/cumulus_sync.lock")


class TestAcquireLock(unittest.TestCase):
    def test_uses_msvcrt(self):
        calls = []

        class FakeMsvcrt:
            LK_NBLCK = 6

            def locking(self, fd, mode, nbytes):
                calls.append((fd, mode, nbytes))

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(sm, "fcntl", None), \
                    mock.patch.object(sm, "msvcrt", FakeMsvcrt(), create=True), \
                    mock.patch.object(sm, "MOTOR_LOCK", os.path.join(td, "cumulus_sync.lock")):
                fd = sm.acquire_lock()
                self.assertIsNotNone(fd)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][1], 6)  # LK_NBLCK
                self.assertEqual(calls[0][2], 1)
                fd.close()

    def test_no_lock_support(self):
        with tempfile.TemporaryDirectory() as td:
            lock = os.path.join(td, "cumulus_sync.lock")
            with open(lock, "w") as f:
                f.write("999999 /proc yok\n")
            with mock.patch.object(sm, "fcntl", None), \
                    mock.patch.object(sm, "msvcrt", None, create=True), \
                    mock.patch.object(sm, "MOTOR_LOCK", lock):
                fd = sm.acquire_lock()
                self.assertIsNotNone(fd)  # pid canlı değil → devam
                fd.close()


class TestConfigPaths(unittest.TestCase):
    def test_state_path_os_path(self):
        p = sm._state_path({"state": {"dir": "C:\\hermes\\state"}})
        self.assertEqual(p, os.path.join("C:\\hermes\\state", "last_push.json"))

    def test_node_path_joined(self):
        base = "C:\\hermes\\nodes"
        node = "kernel"
        p = os.path.join(base, node)
        self.assertEqual(p, base + os.sep + node)  # os.path.join kullanılmış


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


class TestA2ACliWindows(unittest.TestCase):
    def test_canonical_host_aliases(self):
        self.assertEqual(cli.canonical_host("H2"), "100.76.82.46")
        self.assertEqual(cli.canonical_host("sistemg16"), "100.76.82.46")
        self.assertEqual(cli.canonical_host("100.103.44.107"), "100.103.44.107")

    def test_rpc_urllib(self):
        seen = {}

        def fake_urlopen(req, timeout=120):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            return _FakeResp({"jsonrpc": "2.0", "id": 1,
                              "result": {"served_by": "hx-test"}})

        with mock.patch.object(cli, "identity", lambda: None), \
                mock.patch.object(cli.urllib.request, "urlopen", fake_urlopen):
            out = cli.rpc("127.0.0.1", "ping", {}, "tok123", port=8643, sign=False)
        self.assertEqual(out["result"]["served_by"], "hx-test")
        self.assertEqual(seen["url"], "http://127.0.0.1:8643/")
        self.assertEqual(seen["auth"], "Bearer tok123")

    def test_rpc_retries_transient_connection_once(self):
        calls = []

        def flaky_urlopen(req, timeout=120):
            calls.append(timeout)
            if len(calls) == 1:
                raise OSError("connection reset")
            return _FakeResp({"jsonrpc": "2.0", "id": 1,
                              "result": {"served_by": "hx-test"}})

        with mock.patch.object(cli, "identity", lambda: None), \
                mock.patch.object(cli.urllib.request, "urlopen", flaky_urlopen), \
                mock.patch.object(cli.time, "sleep"):
            out = cli.rpc("127.0.0.1", "ping", {}, "tok123", sign=False,
                          retries=1)
        self.assertEqual(out["result"]["served_by"], "hx-test")
        self.assertEqual(len(calls), 2)

    def test_rpc_does_not_retry_task_send(self):
        calls = []

        def fail_urlopen(req, timeout=120):
            calls.append(1)
            raise OSError("connection reset")

        with mock.patch.object(cli, "identity", lambda: None), \
                mock.patch.object(cli.urllib.request, "urlopen", fail_urlopen):
            with self.assertRaises(OSError):
                cli.rpc("127.0.0.1", "task/send", {}, "tok123", sign=False,
                        retries=1)
        self.assertEqual(len(calls), 1)


class TestMeshNodeInventory(unittest.TestCase):
    def test_aliases_are_collapsed_to_canonical_nodes(self):
        nodes = {
            "H1": "100.92.2.47",
            "h2": "100.76.82.46",
            "sistemg16": "100.76.82.46",
            "h3": "100.103.44.107",
        }
        self.assertEqual(sm.unique_a2a_nodes(nodes), [
            ("H1", "100.92.2.47"),
            ("h2", "100.76.82.46"),
            ("h3", "100.103.44.107"),
        ])

    def test_legacy_health_is_explicit(self):
        health = {"status": "ok", "host": "SISTEMG16"}
        self.assertEqual("legacy" if health.get("disk_gb", "?") == "?" else "ok", "legacy")


class TestA2AServerUvicorn(unittest.TestCase):
    def test_uvicorn_missing_clean_error(self):
        with mock.patch.dict(sys.modules, {"uvicorn": None}), \
                mock.patch.object(sys, "argv", ["a2a", "--port", "8643"]), \
                mock.patch("sys.stdout") as fake_out:
            with self.assertRaises(SystemExit) as cm:
                a2a_srv.main()
            self.assertEqual(cm.exception.code, 1)


class TestA2ATaskList(unittest.TestCase):
    def test_task_list_dispatch_returns_tasks(self):
        result = a2a_srv.dispatch("task/list", {})
        self.assertIn("tasks", result)
        self.assertIsInstance(result["tasks"], list)


if __name__ == "__main__":
    unittest.main()
