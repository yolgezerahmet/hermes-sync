#!/usr/bin/env python3
"""Şifreleme katmanı testleri (X25519 + AES-GCM, 30 Ağu 2026)"""
import json, os, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import synclave.agent_identity as AI


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="crypto_test_"))
        os.environ["AGENT_IDENTITY_DIR"] = str(self.tmp / "a")
        self.a = AI.AgentIdentity.load_or_create("hermes")
        os.environ["AGENT_IDENTITY_DIR"] = str(self.tmp / "b")
        self.b = AI.AgentIdentity.load_or_create("hermes")
        os.environ["AGENT_IDENTITY_DIR"] = str(self.tmp / "dinleyici")
        self.ev = AI.AgentIdentity.load_or_create("hermes")
        AI._NONCE_CACHE.clear()

    def tearDown(self):
        os.environ.pop("AGENT_IDENTITY_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)


class K1_Roundtrip(Base):
    def test_a_den_b_ye_sifreli_mesaj(self):
        gizli = "GİZLİ: H2 GPU analiz sonucu 0.97".encode()
        env = self.a.secure_payload(self.b.x25519_public, gizli, to_agent=self.b.agent_id)
        acik = AI.AgentIdentity.open_secure_payload(env, self.b)
        self.assertEqual(acik, gizli)

    def test_dinleyici_cozemez(self):
        """Aradaki dinleyici (ev) şifreyi ÇÖZEMEZ — gizlilik garantisi."""
        env = self.a.secure_payload(self.b.x25519_public, b"cok gizli veri", to_agent=self.b.agent_id)
        with self.assertRaises(Exception):
            AI.AgentIdentity.open_secure_payload(env, self.ev)

    def test_kurcalanan_ct_red(self):
        env = self.a.secure_payload(self.b.x25519_public, b"gizli", to_agent=self.b.agent_id)
        env["ct"] = env["ct"][:-4] + "AAAA"
        with self.assertRaises(Exception):
            AI.AgentIdentity.open_secure_payload(env, self.b)

    def test_kurcalanan_imza_red(self):
        env = self.a.secure_payload(self.b.x25519_public, b"gizli", to_agent=self.b.agent_id)
        env["sig"] = env["sig"][:-4] + "BBBB"
        with self.assertRaises(Exception):
            AI.AgentIdentity.open_secure_payload(env, self.b)

    def test_replay_red(self):
        env = self.a.secure_payload(self.b.x25519_public, b"gizli", to_agent=self.b.agent_id)
        AI.AgentIdentity.open_secure_payload(env, self.b)
        with self.assertRaises(ValueError) as ctx:
            AI.AgentIdentity.open_secure_payload(env, self.b)
        self.assertIn("replay", str(ctx.exception))

    def test_eski_zaman_red(self):
        env = self.a.secure_payload(self.b.x25519_public, b"gizli", to_agent=self.b.agent_id)
        env["ts"] = str(int(__import__("time").time()) - 500)
        with self.assertRaises(ValueError):
            AI.AgentIdentity.open_secure_payload(env, self.b)

    def test_yanlis_alici_red(self):
        env = self.a.secure_payload(self.b.x25519_public, b"gizli", to_agent=self.b.agent_id)
        with self.assertRaises(ValueError):
            AI.AgentIdentity.open_secure_payload(env, self.a)  # kendi paketi


class K2_GovdeGizliligi(Base):
    def test_sifreli_paket_duz_metin_icermez(self):
        gizli = "H2-ANALIZ: BGA fanout cozuldu".encode()
        env = self.a.secure_payload(self.b.x25519_public, gizli, to_agent=self.b.agent_id)
        s = json.dumps(env)
        self.assertNotIn("BGA", s)
        self.assertNotIn("fanout", s)
        self.assertNotIn("cozuldu", s)

    def test_peek_metadata_sizdirmaz(self):
        """Paketin dış görünümü: agent_id + anahtarlar var ama içerik YOK."""
        env = self.a.secure_payload(self.b.x25519_public, b"X" * 1000, to_agent=self.b.agent_id)
        self.assertEqual(env["agent_id"], self.a.agent_id)
        self.assertTrue(env["ct"])
        self.assertTrue(env["nonce"])
        self.assertTrue(env["eph"])
        self.assertTrue(env["sig"])


class K3_Performans(Base):
    def test_sifreleme_suresi(self):
        import time, statistics
        N = 200
        ts = []
        for _ in range(N):
            t0 = time.perf_counter()
            env = self.a.secure_payload(self.b.x25519_public, b"kisa mesaj", to_agent=self.b.agent_id)
            AI.AgentIdentity.open_secure_payload(env, self.b)
            ts.append((time.perf_counter() - t0) * 1000)
        ort = statistics.mean(ts)
        print(f"\n[perf] sifreleme+cozme: ort={ort:.3f}ms  p95={sorted(ts)[int(N*0.95)]:.3f}ms")
        self.assertLess(ort, 5.0, f"şifreleme çok yavaş: {ort}ms")


if __name__ == "__main__":
    unittest.main(verbosity=2)
