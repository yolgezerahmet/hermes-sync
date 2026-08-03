#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cumulus Sync Motoru — Birim Testler
====================================
Çalıştır: python3 -m unittest discover tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sync_motor as sm


class TestHash(unittest.TestCase):
    def test_sha256_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = f.name
        try:
            h = sm.sha256_file(path)
            # "hello world" SHA256
            self.assertEqual(
                h,
                "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")
        finally:
            os.unlink(path)

    def test_sha256_missing(self):
        self.assertIsNone(sm.sha256_file("/yok/boyle/dosya"))


class TestGlob(unittest.TestCase):
    def test_matches(self):
        self.assertTrue(sm.matches_glob("test.c", ["*.c"]))
        self.assertTrue(sm.matches_glob("kernel.h", ["*.h", "*.c"]))
        self.assertFalse(sm.matches_glob("test.o", ["*.c"]))


class TestMachineDetect(unittest.TestCase):
    def test_h1(self):
        self.assertEqual(sm.detect_machine("CumulusNET-Hermes-1"), "H1")

    def test_h2(self):
        self.assertEqual(sm.detect_machine("H2-Windows-RTX5070Ti"), "H2")

    def test_unknown_linux(self):
        # Linux'ta bilinmeyen hostname → H1 fallback
        self.assertEqual(sm.detect_machine("bilinmeyen-server"), "H1")


class TestScan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Test dosyaları oluştur
        Path(self.tmp, "a.c").write_text("int a;")
        Path(self.tmp, "b.h").write_text("#define B 1")
        Path(self.tmp, "skip.o").write_text("obj")
        Path(self.tmp, "buyuk.c").write_text("x" * (600 * 1024))  # > 512KB

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_scan_filter(self):
        cfg = {
            "path": self.tmp,
            "include": ["*.c", "*.h"],
            "exclude_dirs": [".git"],
            "max_size_kb": 512,
        }
        inv = sm.scan_directory("test", cfg)
        # a.c ve b.h var, skip.o yok (pattern), buyuk.c yok (boyut)
        paths = set(inv.keys())
        self.assertIn("test/a.c", paths)
        self.assertIn("test/b.h", paths)
        self.assertNotIn("test/skip.o", paths)
        self.assertNotIn("test/buyuk.c", paths)


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = {
            "state": {
                "manifest_local": os.path.join(self.tmp, "manifest.json"),
                "logfile": os.path.join(self.tmp, "log.txt"),
            },
            "machine": "H1",
        }

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_roundtrip(self):
        mf = {"version": "1.0.0", "files": {"a.c": {"sha": "abc"}},
              "machine": "H1"}
        sm.save_manifest(self.cfg, mf)
        loaded = sm.load_manifest(self.cfg)
        self.assertEqual(loaded["files"]["a.c"]["sha"], "abc")
        self.assertEqual(loaded["machine"], "H1")

    def test_missing_returns_default(self):
        mf = sm.load_manifest(self.cfg)
        self.assertIn("files", mf)
        self.assertEqual(mf["machine"], "H1")


class TestConflicts(unittest.TestCase):
    def test_no_conflicts(self):
        self.assertEqual(sm.list_conflicts({
            "dirs": {"x": {"path": "/tmp/nonexistent"}}
        }), [])


class TestConfig(unittest.TestCase):
    def test_default_config(self):
        self.assertIn("github", sm.DEFAULT_CONFIG)
        self.assertIn("gdrive", sm.DEFAULT_CONFIG)
        self.assertIn("dirs", sm.DEFAULT_CONFIG)

    def test_detect_in_default(self):
        # DEFAULT_CONFIG machines ile tutarlı
        cfg = json.loads(json.dumps(sm.DEFAULT_CONFIG))
        self.assertIn("h1_hostnames", cfg["machines"])


if __name__ == "__main__":
    unittest.main()
