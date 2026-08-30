#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_retry.py — rclone hata dayanıklılığı (v2.1.1)
====================================================
Çalıştır: python3 -m unittest discover tests

Kapsam:
  1. _run_rclone: okuma komutunda geçici hata → 1 retry → başarı.
  2. _run_rclone: retry sonrası da hata → tanı önekli dönüş (fail-closed).
  3. _run_rclone: yazma komutuna retry YOK.
  4. run_cmd: retries>0 sadece idempotent okumada; yazmaya ASLA.
  5. Geçici hata sınıflandırması (timeout/5xx/network vs not-found).
"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sync_common_knowledge as ck
import sync_motor as sm


class _FakeResult:
    def __init__(self, rc, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


class TestRunRcloneRetry(unittest.TestCase):
    def _install_fake(self, script, calls):
        def fake_run(cmd_args, capture_output=True, text=True, errors="replace",
                     timeout=60, **kw):
            calls.append(list(cmd_args))
            rc, out, err = script[min(len(calls) - 1, len(script) - 1)]
            return _FakeResult(rc, out, err)
        return fake_run

    @mock.patch("time.sleep")
    def test_read_retry_success(self, _sleep):
        calls = []
        ck.subprocess = types.SimpleNamespace(
            run=self._install_fake([(1, "", "connection reset"), (0, '{"ok":1}', "")], calls))
        try:
            rc, out, err = ck._run_rclone(
                ["cat", "gdrive:hermes-sync/hahmet/shared/state.json"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out), {"ok": 1})
            self.assertEqual(len(calls), 2)  # hata → retry → başarı
        finally:
            import subprocess as _sp
            ck.subprocess = _sp

    @mock.patch("time.sleep")
    def test_read_retry_then_fail(self, _sleep):
        calls = []
        ck.subprocess = types.SimpleNamespace(run=self._install_fake(
            [(1, "", "HTTP 503 Service Unavailable"), (1, "", "HTTP 503")], calls))
        try:
            rc, out, err = ck._run_rclone(["lsf", "gdrive:hermes-sync/hahmet/shared/tasks"])
            self.assertNotEqual(rc, 0)
            self.assertEqual(len(calls), 2)  # yalnız 1 retry
            self.assertIn("sync hata:", err)
            self.assertIn("rc=1", err)
            self.assertIn("retry=1", err)
        finally:
            import subprocess as _sp
            ck.subprocess = _sp

    @mock.patch("time.sleep")
    def test_write_no_retry(self, _sleep):
        calls = []
        ck.subprocess = types.SimpleNamespace(run=self._install_fake(
            [(1, "", "connection reset")], calls))
        try:
            rc, out, err = ck._run_rclone(["copyto", "/tmp/x.json",
                                           "gdrive:hermes-sync/hahmet/shared/state.json"])
            self.assertNotEqual(rc, 0)
            self.assertEqual(len(calls), 1)  # yazma → retry YOK
            self.assertIn("sync hata:", err)
        finally:
            import subprocess as _sp
            ck.subprocess = _sp

    @mock.patch("time.sleep")
    def test_not_found_no_retry(self, _sleep):
        calls = []
        ck.subprocess = types.SimpleNamespace(run=self._install_fake(
            [(1, "", "directory not found")], calls))
        try:
            rc, out, err = ck._run_rclone(["cat", "gdrive:hermes-sync/hahmet/none/x"])
            self.assertNotEqual(rc, 0)
            self.assertEqual(len(calls), 1)
        finally:
            import subprocess as _sp
            ck.subprocess = _sp


class TestRunCmdRetry(unittest.TestCase):
    def _install_fake(self, script, calls):
        def fake_run(cmd_args, capture_output=True, text=True, errors="replace",
                     timeout=60, **kw):
            calls.append(list(cmd_args))
            rc, out, err = script[min(len(calls) - 1, len(script) - 1)]
            return _FakeResult(rc, out, err)
        return fake_run

    @mock.patch("time.sleep")
    def test_read_retry_success(self, _sleep):
        calls = []
        sm.subprocess = types.SimpleNamespace(
            run=self._install_fake([(-1, "timeout", ""), (0, "saglikli", "")], calls))
        try:
            out, rc = sm.run_cmd("rclone cat gdrive:x/y", retries=1)
            self.assertEqual(rc, 0)
            self.assertEqual(out, "saglikli")
            self.assertEqual(len(calls), 2)
        finally:
            import subprocess as _sp
            sm.subprocess = _sp

    @mock.patch("time.sleep")
    def test_write_never_retries(self, _sleep):
        calls = []
        sm.subprocess = types.SimpleNamespace(run=self._install_fake(
            [(1, "", "connection reset")], calls))
        try:
            out, rc = sm.run_cmd("rclone copy /tmp/a gdrive:hermes-sync/hahmet", retries=1)
            self.assertEqual(rc, 1)
            self.assertEqual(len(calls), 1)
        finally:
            import subprocess as _sp
            sm.subprocess = _sp

    @mock.patch("time.sleep")
    def test_default_no_retry(self, _sleep):
        calls = []
        sm.subprocess = types.SimpleNamespace(run=self._install_fake(
            [(1, "", "HTTP 503")], calls))
        try:
            out, rc = sm.run_cmd("rclone cat gdrive:x/y")
            self.assertEqual(rc, 1)
            self.assertEqual(len(calls), 1)
        finally:
            import subprocess as _sp
            sm.subprocess = _sp

    @mock.patch("time.sleep")
    def test_non_read_cmd_no_retry(self, _sleep):
        calls = []
        sm.subprocess = types.SimpleNamespace(run=self._install_fake(
            [(-1, "timeout", "")], calls))
        try:
            out, rc = sm.run_cmd("rclone backup gdrive:x/y", retries=1)
            self.assertEqual(rc, -1)
            self.assertEqual(len(calls), 1)
        finally:
            import subprocess as _sp
            sm.subprocess = _sp


class TestTransientClassification(unittest.TestCase):
    def test_transient(self):
        self.assertTrue(sm._is_transient_rc(-1, ""))
        self.assertTrue(sm._is_transient_rc(1, "HTTP 503 Service Unavailable"))
        self.assertTrue(sm._is_transient_rc(1, "connection reset by peer"))
        self.assertTrue(sm._is_transient_rc(1, "i/o timeout"))
        self.assertTrue(ck._is_transient_rclone_error(-1, ""))
        self.assertTrue(ck._is_transient_rclone_error(1, "HTTP 500 Internal Server Error"))
        self.assertTrue(ck._is_transient_rclone_error(1, "connection refused"))

    def test_not_transient(self):
        self.assertFalse(sm._is_transient_rc(1, "directory not found"))
        self.assertFalse(sm._is_transient_rc(2, "file does not exist"))
        self.assertFalse(ck._is_transient_rclone_error(1, "not found"))
        self.assertFalse(ck._is_transient_rclone_error(1, "invalid object name"))


if __name__ == "__main__":
    unittest.main()
