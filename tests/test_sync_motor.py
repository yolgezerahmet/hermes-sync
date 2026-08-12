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
from unittest import mock
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
        # Ortam bağımsız: os.name mock'lanır (H2'de Windows'ta da deterministik)
        with mock.patch("sync_motor.os.name", "posix"):
            self.assertEqual(sm.detect_machine("bilinmeyen-server"), "H1")

    def test_unknown_windows(self):
        # Windows'ta bilinmeyen hostname → H2 fallback
        with mock.patch("sync_motor.os.name", "nt"):
            self.assertEqual(sm.detect_machine("bilinmeyen-pc"), "H2")

    def test_openclaw(self):
        self.assertEqual(sm.detect_machine("openclaw"), "OPENCLAW")


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


# ═══════════════════════════════════════════════════════════════
# AKILLI KURULUM (v1.6) — kaynak farkındalığı testleri
# ═══════════════════════════════════════════════════════════════

class TestResourceProbe(unittest.TestCase):
    def test_probe_shape(self):
        with mock.patch("sync_motor.run_cmd", return_value=("", -1)), \
             mock.patch("sync_motor.os.cpu_count", return_value=4):
            r = sm.resource_probe()
        self.assertIsInstance(r["cpus"], int)
        self.assertIsInstance(r["ram_gb"], float)
        self.assertIsInstance(r["disk_gb"], float)
        self.assertIn(r["gpu"], (True, False))
        self.assertGreaterEqual(r["cpus"], 0)

    def test_gpu_detected_via_nvidia(self):
        with mock.patch("sync_motor.run_cmd",
                        side_effect=[("NVIDIA RTX 5070 Ti", 0),
                                     ("", -1), ("", -1)]):
            r = sm.resource_probe()
        self.assertTrue(r["gpu"])
        self.assertIn("RTX", r["gpu_name"])

    def test_gpu_missing(self):
        with mock.patch("sync_motor.run_cmd",
                        side_effect=[("", 1), ("", 1), ("", 1)]):
            r = sm.resource_probe()
        self.assertFalse(r["gpu"])
        self.assertIsNone(r["gpu_name"])


class TestToolInstalled(unittest.TestCase):
    def test_installed(self):
        with mock.patch("sync_motor.shutil.which",
                        return_value="/usr/bin/ollama"):
            self.assertTrue(sm.tool_installed({"check": ["ollama"]}))

    def test_missing(self):
        with mock.patch("sync_motor.shutil.which", return_value=None):
            self.assertFalse(sm.tool_installed({"check": ["ollama"]}))

    def test_any_check_wins(self):
        # HERHANGİ BİRİ kuruluysa 'kurulu' sayılır
        with mock.patch("sync_motor.shutil.which",
                        side_effect=[None, "/usr/local/cuda/bin/nvcc"]):
            self.assertTrue(sm.tool_installed(
                {"check": ["nvcc", "/usr/local/cuda/bin/nvcc"]}))

    def test_no_checks(self):
        self.assertFalse(sm.tool_installed({"check": []}))


class TestScanTools(unittest.TestCase):
    def test_scan(self):
        cfg = {"tools": {
            "ollama": {"check": ["ollama"], "gpu": False,
                       "min_ram_gb": 8, "min_disk_gb": 20},
            "cuda": {"check": ["nvcc"], "gpu": True,
                     "min_ram_gb": 8, "min_disk_gb": 25},
        }}
        with mock.patch("sync_motor.shutil.which",
                        side_effect=["/usr/bin/ollama", None]):
            st = sm.scan_tools(cfg)
        self.assertTrue(st["ollama"]["installed"])
        self.assertFalse(st["cuda"]["installed"])
        self.assertTrue(st["cuda"]["gpu"])

    def test_default_tools_in_config(self):
        # DEFAULT_CONFIG katalog içeriyor (ör. GPU öncelikli araçlar)
        tools = sm.DEFAULT_CONFIG.get("tools", {})
        self.assertIn("cuda-toolkit", tools)
        self.assertTrue(tools["cuda-toolkit"]["gpu"])


class TestProposeInstall(unittest.TestCase):
    TOOL = {"check": ["x"], "gpu": False,
            "min_ram_gb": 8, "min_disk_gb": 20, "min_cpus": 2}
    RES_OK = {"cpus": 4, "ram_gb": 16.0, "disk_gb": 100.0,
              "gpu": True, "nvidia": True, "gpu_name": "RTX"}
    REMOTE = {"x": {"installed": True}}

    def _local(self, installed=False):
        return {"x": {"installed": installed}}

    def test_already(self):
        st, _ = sm.propose_install("x", self.TOOL, self.RES_OK,
                                   self._local(True), self.REMOTE)
        self.assertEqual(st, "ALREADY")

    def test_not_on_source(self):
        st, _ = sm.propose_install("x", self.TOOL, self.RES_OK,
                                   self._local(False),
                                   {"x": {"installed": False}})
        self.assertEqual(st, "NOT_ON_SOURCE")

    def test_installable(self):
        st, _ = sm.propose_install("x", self.TOOL, self.RES_OK,
                                   self._local(False), self.REMOTE)
        self.assertEqual(st, "INSTALLABLE")

    def test_gpu_missing_blocks_gpu_tool(self):
        # Genel GPU olsa bile NVIDIA (CUDA) yoksa GPU zorunlu araç engellenir
        res = dict(self.RES_OK, nvidia=False)
        tool = dict(self.TOOL, gpu=True)
        st, _ = sm.propose_install("x", tool, res,
                                   self._local(False), self.REMOTE)
        self.assertEqual(st, "GPU_MISSING")

    def test_disk_insufficient(self):
        res = dict(self.RES_OK, disk_gb=5.0)
        st, _ = sm.propose_install("x", self.TOOL, res,
                                   self._local(False), self.REMOTE)
        self.assertEqual(st, "DISK_INSUFFICIENT")

    def test_ram_insufficient(self):
        res = dict(self.RES_OK, ram_gb=4.0)
        st, _ = sm.propose_install("x", self.TOOL, res,
                                   self._local(False), self.REMOTE)
        self.assertEqual(st, "RAM_INSUFFICIENT")

    def test_cpu_insufficient(self):
        res = dict(self.RES_OK, cpus=1)
        st, _ = sm.propose_install("x", self.TOOL, res,
                                   self._local(False), self.REMOTE)
        self.assertEqual(st, "CPU_INSUFFICIENT")


class TestCmdProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = {
            "state": {
                "manifest_local": os.path.join(self.tmp, "manifest.json"),
                "logfile": os.path.join(self.tmp, "log.txt"),
            },
            "machine": "H1",
            "tools": {"x": {"check": ["x"], "gpu": False,
                            "min_ram_gb": 1, "min_disk_gb": 1}},
        }

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_probe_writes_manifest(self):
        with mock.patch("sync_motor.resource_probe",
                        return_value={"cpus": 4, "ram_gb": 16.0,
                                      "disk_gb": 100.0, "gpu": False,
                                      "nvidia": False, "gpu_name": None}), \
             mock.patch("sync_motor.shutil.which", return_value=None):
            rc = sm.cmd_probe(self.cfg)
        self.assertEqual(rc, 0)
        mf = sm.load_manifest(self.cfg)
        self.assertIn("resources", mf)
        self.assertIn("tools_state", mf)
        self.assertIn("probe_time", mf)
        self.assertEqual(mf["resources"]["cpus"], 4)


class TestCmdApply(unittest.TestCase):
    RES = {"cpus": 4, "ram_gb": 16.0, "disk_gb": 100.0,
           "gpu": True, "nvidia": True, "gpu_name": "RTX"}

    def _cfg(self, install="echo kur"):
        return {"tools": {"x": {"check": ["x"], "gpu": False,
                                "min_ram_gb": 1, "min_disk_gb": 1,
                                "install": install}}}

    def test_apply_already_installed_red(self):
        # ZATEN KURULU → RED, komut ÇALIŞMAZ (üzerine yazma yasağı)
        with mock.patch("sync_motor.tool_installed", return_value=True), \
             mock.patch("sync_motor.run_cmd") as rc_mock:
            rc = sm.cmd_apply(self._cfg(), "x", yes=True)
        self.assertEqual(rc, 1)
        rc_mock.assert_not_called()

    def test_apply_unknown_tool(self):
        rc = sm.cmd_apply({"tools": {}}, "yok", yes=True)
        self.assertEqual(rc, 1)

    def test_apply_no_install_cmd(self):
        with mock.patch("sync_motor.tool_installed", return_value=False), \
             mock.patch("sync_motor.resource_probe", return_value=self.RES), \
             mock.patch("sync_motor.scan_tools", return_value={}):
            rc = sm.cmd_apply({"tools": {"x": {"check": ["x"],
                                               "gpu": False}}}, "x", yes=True)
        self.assertEqual(rc, 1)

    def test_apply_onay_reddi_non_destructive(self):
        # Interaktif onay 'hayır' → kurulum ÇALIŞMAZ, hiçbir şey değişmez
        with mock.patch("sync_motor.tool_installed", return_value=False), \
             mock.patch("sync_motor.resource_probe", return_value=self.RES), \
             mock.patch("sync_motor.scan_tools", return_value={}), \
             mock.patch("builtins.input", return_value="h"), \
             mock.patch("sync_motor.run_cmd") as rc_mock:
            rc = sm.cmd_apply(self._cfg(), "x", yes=False)
        self.assertEqual(rc, 1)
        rc_mock.assert_not_called()

    def test_apply_yes_runs_install(self):
        with mock.patch("sync_motor.tool_installed", return_value=False), \
             mock.patch("sync_motor.resource_probe", return_value=self.RES), \
             mock.patch("sync_motor.scan_tools", return_value={}), \
             mock.patch("sync_motor.run_cmd",
                        return_value=("kuruldu", 0)) as rc_mock, \
             mock.patch("sync_motor.cmd_probe"):
            rc = sm.cmd_apply(self._cfg(), "x", yes=True)
        self.assertEqual(rc, 0)
        rc_mock.assert_called_once()

    def test_apply_gpu_missing_red(self):
        # GPU zorunlu araç + CUDA uyumlu GPU yok → RED
        cfg = {"tools": {"cuda": {"check": ["nvcc"], "gpu": True,
                                  "min_ram_gb": 8, "min_disk_gb": 25,
                                  "min_cpus": 2, "install": "echo kur"}}}
        res = dict(self.RES, nvidia=False)
        with mock.patch("sync_motor.tool_installed", return_value=False), \
             mock.patch("sync_motor.resource_probe", return_value=res), \
             mock.patch("sync_motor.scan_tools", return_value={}), \
             mock.patch("sync_motor.run_cmd") as rc_mock:
            rc = sm.cmd_apply(cfg, "cuda", yes=True)
        self.assertEqual(rc, 1)
        rc_mock.assert_not_called()


class TestCmdPropose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = {
            "state": {
                "manifest_local": os.path.join(self.tmp, "manifest.json"),
                "logfile": os.path.join(self.tmp, "log.txt"),
            },
            "machine": "H1",
            "tools": {
                "cuda": {"check": ["nvcc"], "gpu": True,
                         "min_ram_gb": 8, "min_disk_gb": 25, "min_cpus": 2,
                         "desc": "CUDA", "install": "echo cuda"},
                "ollama": {"check": ["ollama"], "gpu": False,
                           "min_ram_gb": 8, "min_disk_gb": 20, "min_cpus": 2,
                           "desc": "Ollama", "install": "echo ollama"},
            },
        }

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_propose_no_remote(self):
        rc = sm.cmd_propose(self.cfg)   # manifest'te tools_state yok
        self.assertEqual(rc, 0)

    def test_propose_uses_remote_state(self):
        mf = sm.load_manifest(self.cfg)
        mf["resources"] = {"cpus": 8, "ram_gb": 32.0, "disk_gb": 500.0,
                           "gpu": True, "gpu_name": "RTX 5090"}
        mf["tools_state"] = {"cuda": {"installed": True},
                             "ollama": {"installed": True}}
        sm.save_manifest(self.cfg, mf)
        # Yerel: NVIDIA GPU YOK → cuda engelli; ollama kurulabilir
        with mock.patch("sync_motor.resource_probe",
                        return_value={"cpus": 4, "ram_gb": 16.0,
                                      "disk_gb": 100.0, "gpu": False,
                                      "nvidia": False, "gpu_name": None}), \
             mock.patch("sync_motor.shutil.which", return_value=None):
            rc = sm.cmd_propose(self.cfg)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
