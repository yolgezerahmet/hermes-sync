import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
import inbox_worker as worker


class TestAgentUpdate(unittest.TestCase):
    def test_build_agent_update_task(self):
        task = worker.build_agent_update_task(
            "http://100.92.2.47/A2A_UPDATE_20260831.tar.gz", "a" * 64)
        self.assertTrue(task.startswith("agent-update:"))
        self.assertIn("url=http://100.92.2.47/A2A_UPDATE_20260831.tar.gz", task)
        self.assertIn("sha256=" + "a" * 64, task)

    def test_parse_agent_update_roundtrip(self):
        url = "http://127.0.0.1:9090/A2A_UPDATE_20260831.tar.gz"
        digest = "b" * 64
        task = worker.build_agent_update_task(url, digest)
        key, args = worker.parse_task(task)
        self.assertEqual(key, "agent-update")
        self.assertEqual(args[0]["url"], url)
        self.assertEqual(args[0]["sha256"], digest)

    def test_parse_agent_update_requires_url_and_sha256(self):
        key, args = worker.parse_task("agent-update:url=http://100.92.2.47/A2A_UPDATE_20260831.tar.gz sha256=" + "a" * 64)
        self.assertEqual(key, "agent-update")
        self.assertEqual(args[0]["url"], "http://100.92.2.47/A2A_UPDATE_20260831.tar.gz")
        self.assertEqual(args[0]["sha256"], "a" * 64)

    def test_parse_agent_update_rejects_unapproved_url(self):
        key, args = worker.parse_task("agent-update:url=http://evil/p.tar.gz sha256=" + "a" * 64)
        self.assertIsNone(key)
        self.assertIsNone(args)

    def test_apply_update_verifies_archive_and_replaces_only_allowlisted_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            for name in worker.UPDATE_FILES:
                (repo / name).write_text("old")
            (repo / "other.txt").write_text("keep")
            archive = root / "update.tar.gz"
            staging = root / "stage"
            source = root / "source"
            source.mkdir()
            for name in worker.UPDATE_FILES:
                (source / name).write_text("new")
            with tarfile.open(archive, "w:gz") as tar:
                for name in worker.UPDATE_FILES:
                    tar.add(source / name, arcname="a2a_update/" + name)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with mock.patch.object(worker, "UPDATE_REPO", str(repo)):
                result = worker.apply_agent_update(str(archive), digest, staging_dir=staging)
            self.assertEqual(result["status"], "done")
            self.assertEqual((repo / "a2a_cli.py").read_text(), "new")
            self.assertEqual((repo / "agent_mesh_a2a.py").read_text(), "new")
            self.assertEqual((repo / "sync_motor.py").read_text(), "new")
            self.assertEqual((repo / "other.txt").read_text(), "keep")

    def test_apply_update_rejects_hash_mismatch_without_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            target = repo / "a2a_cli.py"
            target.write_text("old")
            archive = root / "update.tar.gz"
            with tarfile.open(archive, "w:gz"):
                pass
            with mock.patch.object(worker, "UPDATE_REPO", str(repo)):
                with self.assertRaises(ValueError):
                    worker.apply_agent_update(str(archive), "0" * 64, staging_dir=root / "stage")
            self.assertEqual(target.read_text(), "old")


if __name__ == "__main__":
    unittest.main()