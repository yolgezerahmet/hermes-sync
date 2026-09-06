#!/usr/bin/env python3
"""synclave_profile testleri — Hermes ↔ OpenClaw özel alan eşleme"""
import os, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import synclave.synclave_profile as SP


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="profile_test_"))
        self.he = self.tmp / "hermes"
        self.oc = self.tmp / "openclaw"
        (self.he / "skills").mkdir(parents=True)
        (self.oc / "skills").mkdir(parents=True)
        (self.oc / "workspace" / "memory").mkdir(parents=True)
        # env yönlendir
        self._old = (os.environ.get("HERMES_HOME"), os.environ.get("OPENCLAW_HOME"))
        os.environ["HERMES_HOME"] = str(self.he)
        os.environ["OPENCLAW_HOME"] = str(self.oc)
        SP.HERMES = self.he
        SP.OPENCLAW = self.oc

    def tearDown(self):
        os.environ.pop("HERMES_HOME", None)
        os.environ.pop("OPENCLAW_HOME", None)
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestSOUL(Base):
    def test_hermes_soul_openclaw_a_yansir(self):
        (self.he / "SOUL.md").write_text("# Hermes SOUL\n## Dil\nTürkçe\n", encoding="utf-8")
        r = SP.merge_soul(self.he / "SOUL.md", self.oc / "workspace" / "SOUL.md")
        self.assertEqual(r["status"], "kopyalandi")
        self.assertTrue((self.oc / "workspace" / "SOUL.md").exists())

    def test_iki_taraf_birlesir_ayni_bolum_son_degisen_kazanir(self):
        (self.he / "SOUL.md").write_text("# SOUL\n## Dil\nTürkçe\n## Teknik\nRF\n", encoding="utf-8")
        (self.oc / "workspace" / "SOUL.md").write_text("# SOUL\n## Dil\nİngilizce\n## Yön\nMühendislik\n", encoding="utf-8")
        r = SP.merge_soul(self.he / "SOUL.md", self.oc / "workspace" / "SOUL.md")
        self.assertEqual(r["status"], "birlesik")
        out = (self.he / "SOUL.md").read_text()
        self.assertIn("## Teknik", out)
        self.assertIn("## Yön", out)
        # çakışan bölümlerden biri yedeklenmiş olmalı
        self.assertGreaterEqual(len(r["conflict"]), 1)

    def test_bos_taraf_cakisma_yok(self):
        r = SP.merge_soul(self.he / "SOUL.md", self.oc / "workspace" / "SOUL.md")
        self.assertEqual(r["status"], "bos")


class TestSkills(Base):
    def test_ayni_adli_skill_birlesir(self):
        (self.he / "skills" / "demo").mkdir(parents=True, exist_ok=True)
        (self.oc / "skills" / "demo").mkdir(parents=True, exist_ok=True)
        (self.he / "skills" / "demo" / "SKILL.md").write_text("---\nname: demo\n---\nHermes içerik", encoding="utf-8")
        (self.oc / "skills" / "demo" / "SKILL.md").write_text("---\nname: demo\n---\nOpenClaw içerik", encoding="utf-8")
        # merge_skills mtime'a göre kazananı seçer — test ortamında iki yazma
        # aynı nanosaniyeye denk gelebilir, bu yüzden kazananı (hermes) açıkça
        # daha yeni yaparak deterministik hale getir: openclaw sürümü yedeklenir.
        oc_st = (self.oc / "skills" / "demo" / "SKILL.md").stat().st_mtime + 10
        os.utime(self.he / "skills" / "demo" / "SKILL.md", (oc_st, oc_st))
        r = SP.merge_skills(self.he / "skills", self.oc / "skills")
        self.assertIn("birlesen", r)
        # conflict yedek dosyası oluşmuş olmalı
        conf = list((self.oc / "skills" / "demo").glob("SKILL.md.conflict.*"))
        self.assertEqual(len(conf), 1)
        # kazanan hermes içeriği iki tarafa da yazılmış olmalı
        self.assertIn("Hermes içerik", (self.oc / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8"))

    def test_tek_tarafli_skill_kopyalanir(self):
        (self.he / "skills" / "sadece_h").mkdir(parents=True, exist_ok=True)
        (self.oc / "skills" / "sadece_o").mkdir(parents=True, exist_ok=True)
        (self.he / "skills" / "sadece_h" / "SKILL.md").write_text("sadece hermes", encoding="utf-8")
        (self.oc / "skills" / "sadece_o" / "SKILL.md").write_text("sadece openclaw", encoding="utf-8")
        r = SP.merge_skills(self.he / "skills", self.oc / "skills")
        self.assertEqual(r["hermes_only"], 1)
        self.assertEqual(r["openclaw_only"], 1)
        self.assertEqual(r["kopyalandi"], 2)
        self.assertTrue((self.oc / "skills" / "sadece_h" / "SKILL.md").exists())
        self.assertTrue((self.he / "skills" / "sadece_o" / "SKILL.md").exists())


class TestMemory(Base):
    def test_bellek_koprusu(self):
        import time as _t
        bugun = _t.strftime("%Y-%m-%d")
        (self.oc / "workspace" / "memory" / f"{bugun}.md").write_text("bugünkü not", encoding="utf-8")
        r = SP.merge_memory(self.he, self.oc)
        self.assertIn("bugün", r)
        self.assertTrue((self.he / "memory" / f"openclaw_{bugun}.md").exists())


class TestMap(Base):
    def test_harita_basilir(self):
        out = SP.show_map()
        self.assertIn("HERMES", out)
        self.assertIn("OpenClaw", out)
        self.assertIn("identity", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
