#!/usr/bin/env python3
"""
test_agent_identity.py — Ajan kimliği + sohbet etiketleme testleri (30 Ağu 2026)

Kapsam (her test GERÇEK dosya/DB üzerinde çalışır, mock kimlik yok):
  K1 kimlik üretimi: agent_id açık anahtardan türer, kalıcıdır, 0600 anahtar
  K2 runtime izolasyonu: aynı makinede hermes ≠ openclaw kimliği
  K3 klon tespiti: kimlik dizini başka donanıma kopyalanınca "suspected"
  K4 rekey: onaylı yeni kimlik + eski kimlik arşivi (superseded_by)
  K5 imza: doğru imza geçer; kurcalanan gövde/ID/nonce/eski zaman RED
  K6 peer TOFU: ilk görüş kaydeder, anahtar değişimi RED (taklit)
  K7 sohbet ID: kullanıcı/ajan ayrı; aynı kapsam idempotent; farklı kapsam ayrı
  K8 mesaj sırası: seq monoton, msg_id çakışmaz, içerik saklanmaz (sadece sha256)
  K9 ULID: kronolojik sıralı ve çakışmasız
"""
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "synclave"))
import agent_identity as AI  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ident_test_"))
        os.environ["AGENT_IDENTITY_DIR"] = str(self.tmp / "hermes_id")
        AI._NONCE_CACHE.clear()

    def tearDown(self):
        os.environ.pop("AGENT_IDENTITY_DIR", None)
        os.environ.pop("AGENT_RUNTIME", None)
        shutil.rmtree(self.tmp, ignore_errors=True)


class K1_Uretim(Base):
    def test_agent_id_anahtardan_turer_ve_kalicidir(self):
        i1 = AI.AgentIdentity.load_or_create("hermes")
        self.assertTrue(i1.agent_id.startswith("hx-"), i1.agent_id)
        self.assertEqual(len(i1.agent_id), 3 + 24)
        # ID = f(pubkey): bağımsız türetme aynı sonucu vermeli
        self.assertEqual(
            AI.AgentIdentity._derive_id("hermes", AI._unb64(i1.public_key)),
            i1.agent_id)
        # yeniden yükleme aynı kimlik (kalıcı)
        i2 = AI.AgentIdentity.load_or_create("hermes")
        self.assertEqual(i1.agent_id, i2.agent_id)
        self.assertEqual(i1.public_key, i2.public_key)
        # özel anahtar sadece sahibinde okunabilir
        mode = oct(os.stat(i1.dir / "agent_ed25519.key").st_mode)[-3:]
        self.assertEqual(mode, "600", f"anahtar izni {mode}")
        # donanım bağı kaydedilmiş
        self.assertTrue(i1.meta["hw_fingerprint"])
        self.assertIn(i1.meta["hw_strength"], ("strong", "weak", "none"))

    def test_iki_ayri_kurulum_farkli_id_uretir(self):
        a = AI.AgentIdentity.load_or_create("hermes").agent_id
        os.environ["AGENT_IDENTITY_DIR"] = str(self.tmp / "ikinci")
        b = AI.AgentIdentity.load_or_create("hermes").agent_id
        self.assertNotEqual(a, b, "her kurulum kendi kimliğini üretmeli")


class K2_RuntimeIzolasyon(Base):
    def test_hermes_ve_openclaw_ayri_kimlik(self):
        os.environ["AGENT_IDENTITY_DIR"] = str(self.tmp / "h")
        h = AI.AgentIdentity.load_or_create("hermes")
        os.environ["AGENT_IDENTITY_DIR"] = str(self.tmp / "o")
        o = AI.AgentIdentity.load_or_create("openclaw")
        self.assertTrue(o.agent_id.startswith("oc-"))
        self.assertNotEqual(h.agent_id, o.agent_id)

    def test_ayni_anahtar_farkli_runtime_farkli_id(self):
        """Runtime ID türetmeye girer: aynı anahtarla hermes/openclaw karışmaz."""
        i = AI.AgentIdentity.load_or_create("hermes")
        pub = AI._unb64(i.public_key)
        self.assertNotEqual(AI.AgentIdentity._derive_id("hermes", pub),
                            AI.AgentIdentity._derive_id("openclaw", pub))

    def test_varsayilan_dizinler_runtime_ile_ayrisir(self):
        os.environ.pop("AGENT_IDENTITY_DIR")
        self.assertIn(".hermes", str(AI.identity_dir("hermes")))
        self.assertIn(".openclaw", str(AI.identity_dir("openclaw")))


class K3_KlonTespiti(Base):
    def test_kopyalanan_kimlik_suspected_ve_fail_closed(self):
        i = AI.AgentIdentity.load_or_create("hermes")
        self.assertEqual(i.meta["clone_state"], "clean")
        i.assert_not_clone()  # temizken hata vermez

        # KLON SİMÜLASYONU: kimlik dizinini "başka makineye" kopyala
        klon = self.tmp / "klon_id"
        shutil.copytree(i.dir, klon)
        meta = json.loads((klon / "agent_identity.json").read_text())
        meta["hw_fingerprint"] = "f" * 32              # başka donanım
        meta["hw_per_source"]["machine_id"] = "deadbeef1234"
        (klon / "agent_identity.json").write_text(json.dumps(meta))

        os.environ["AGENT_IDENTITY_DIR"] = str(klon)
        k = AI.AgentIdentity.load_or_create("hermes")
        self.assertEqual(k.agent_id, i.agent_id, "kopya aynı ID'yi taşır")
        self.assertEqual(k.meta["clone_state"], "suspected")
        with self.assertRaises(AI.CloneDetected):
            k.assert_not_clone()
        self.assertIn("machine_id", k.meta["clone_detail"]["changed"])

    def test_sadece_arch_degisimi_drifted_kabul_edilir(self):
        """OS/çekirdek yükseltmesi kimliği yakmamalı: drifted, suspected DEĞİL."""
        i = AI.AgentIdentity.load_or_create("hermes")
        i.meta["hw_per_source"]["arch"] = "Linux/eski_mimari"
        i.meta["hw_fingerprint"] = "0" * 32
        st = i._refresh_clone_state(save=False)
        self.assertEqual(st["state"], "drifted")
        i.assert_not_clone()  # drifted çalışmayı engellemez

    def test_strict_yukleme_klonu_reddeder(self):
        i = AI.AgentIdentity.load_or_create("hermes")
        m = json.loads((i.dir / "agent_identity.json").read_text())
        m["hw_fingerprint"] = "a" * 32
        m["hw_per_source"]["mac"] = "000000000000"
        (i.dir / "agent_identity.json").write_text(json.dumps(m))
        with self.assertRaises(AI.CloneDetected):
            AI.AgentIdentity.load_or_create("hermes", strict=True)


class K4_Rekey(Base):
    def test_onaysiz_rekey_reddedilir(self):
        i = AI.AgentIdentity.load_or_create("hermes")
        with self.assertRaises(ValueError):
            i.rekey(confirm=False)

    def test_onayli_rekey_yeni_kimlik_ve_arsiv(self):
        i = AI.AgentIdentity.load_or_create("hermes")
        eski = i.agent_id
        yeni = i.rekey(confirm=True, reason="vps_tasima")
        self.assertNotEqual(eski, yeni.agent_id)
        self.assertEqual(yeni.meta["supersedes"], eski)
        hist = json.loads((i.dir / "identity_history.json").read_text())
        self.assertEqual(hist[-1]["agent_id"], eski)
        self.assertEqual(hist[-1]["superseded_by"], yeni.agent_id)
        self.assertEqual(hist[-1]["supersede_reason"], "vps_tasima")
        # yeniden yükleme yeni kimliği verir (eski dosya kalmamalı)
        self.assertEqual(AI.AgentIdentity.load_or_create("hermes").agent_id,
                         yeni.agent_id)


class K5_Imza(Base):
    def setUp(self):
        super().setUp()
        self.i = AI.AgentIdentity.load_or_create("hermes")
        self.body = json.dumps({"method": "task/send", "params": {"x": 1}}).encode()

    def _hdr(self):
        return self.i.sign_request("task/send", self.body)

    def test_dogru_imza_gecer_ve_peer_kaydolur(self):
        r = AI.verify_request(self._hdr(), "task/send", self.body)
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["first_seen"])
        peers = AI.load_peers()
        self.assertIn(self.i.agent_id, peers)
        self.assertEqual(peers[self.i.agent_id]["public_key"], self.i.public_key)

    def test_kurcalanan_govde_red(self):
        h = self._hdr()
        r = AI.verify_request(h, "task/send", self.body + b"x")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "bad_signature")

    def test_farkli_metod_red(self):
        r = AI.verify_request(self._hdr(), "task/cancel", self.body)
        self.assertFalse(r["ok"])

    def test_replay_ayni_nonce_red(self):
        h = self._hdr()
        self.assertTrue(AI.verify_request(h, "task/send", self.body)["ok"])
        r2 = AI.verify_request(h, "task/send", self.body)
        self.assertFalse(r2["ok"])
        self.assertEqual(r2["reason"], "replay_nonce")

    def test_eski_zaman_damgasi_red(self):
        h = self._hdr()
        h["X-Agent-Ts"] = str(int(time.time()) - (AI.SIG_MAX_SKEW_S + 60))
        r = AI.verify_request(h, "task/send", self.body)
        self.assertFalse(r["ok"])
        self.assertIn("stale_timestamp", r["reason"])

    def test_uydurma_agent_id_red(self):
        """Anahtarı olan biri BAŞKA bir ID ile konuşamaz (ID = pubkey özeti)."""
        h = self._hdr()
        h["X-Agent-Id"] = "hx-" + "z" * 24
        r = AI.verify_request(h, "task/send", self.body)
        self.assertFalse(r["ok"])
        self.assertIn(r["reason"], ("id_key_mismatch", "bad_signature"))

    def test_imzasiz_istek_require_ile_red_gevsek_modda_gecer(self):
        self.assertFalse(AI.verify_request({}, "task/send", self.body, require=True)["ok"])
        gevsek = AI.verify_request({}, "task/send", self.body, require=False)
        self.assertTrue(gevsek["ok"])
        self.assertEqual(gevsek["reason"], "unsigned_allowed")


class K6_PeerTOFU(Base):
    def test_anahtar_degisimi_taklit_olarak_red(self):
        i = AI.AgentIdentity.load_or_create("hermes")
        body = b"{}"
        self.assertTrue(AI.verify_request(i.sign_request("m", body), "m", body)["ok"])
        # saldırgan: aynı agent_id, kendi anahtarı
        os.environ["AGENT_IDENTITY_DIR"] = str(self.tmp / "saldirgan")
        AI._NONCE_CACHE.clear()
        sahte = AI.AgentIdentity.load_or_create("hermes")
        h = sahte.sign_request("m", body)
        h["X-Agent-Id"] = i.agent_id          # kurbanın ID'sini takın
        os.environ["AGENT_IDENTITY_DIR"] = str(i.dir)   # kurbanın peer defteri
        r = AI.verify_request(h, "m", body)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "peer_key_mismatch")

    def test_peer_msg_count_artar(self):
        i = AI.AgentIdentity.load_or_create("hermes")
        for _ in range(3):
            AI.verify_request(i.sign_request("m", b"{}"), "m", b"{}")
        self.assertEqual(AI.load_peers()[i.agent_id]["msg_count"], 3)


class K7_SohbetKimligi(Base):
    def setUp(self):
        super().setUp()
        self.i = AI.AgentIdentity.load_or_create("hermes")

    def test_kullanici_ve_ajan_sohbeti_ayri_onek(self):
        u = AI.open_conversation("user", "ahmet", "telegram", identity=self.i)
        a = AI.open_conversation("agent", "hx-abcdefgh01234567890123", "a2a",
                                 identity=self.i)
        self.assertTrue(u.startswith("u."), u)
        self.assertTrue(a.startswith("a."), a)
        self.assertIn(self.i.short, u)
        self.assertIn("~", a, "ajan sohbeti iki tarafı içerir")
        self.assertNotEqual(u, a)

    def test_ayni_kapsam_idempotent(self):
        a = AI.open_conversation("user", "ahmet", "telegram", identity=self.i)
        b = AI.open_conversation("user", "ahmet", "telegram", identity=self.i)
        self.assertEqual(a, b, "aynı kullanıcı+kanal aynı sohbet ID'si")

    def test_kanal_ve_peer_ayrimi_karismaz(self):
        t = AI.open_conversation("user", "ahmet", "telegram", identity=self.i)
        c = AI.open_conversation("user", "ahmet", "cli", identity=self.i)
        b = AI.open_conversation("user", "baskasi", "telegram", identity=self.i)
        self.assertEqual(len({t, c, b}), 3, "kanal/kullanıcı ayrımı korunmalı")

    def test_gecersiz_kind_red(self):
        with self.assertRaises(ValueError):
            AI.open_conversation("grup", "x", "y", identity=self.i)

    def test_sohbet_listesi_kalicidir(self):
        AI.open_conversation("user", "ahmet", "telegram", "Ahmet CLI", identity=self.i)
        AI.open_conversation("agent", "hx-peer0001", "a2a", identity=self.i)
        rows = AI.list_conversations(self.i.runtime)
        self.assertEqual(len(rows), 2)
        kinds = {r["kind"] for r in rows}
        self.assertEqual(kinds, {"user", "agent"})
        self.assertTrue(all(r["local_agent"] == self.i.agent_id for r in rows))


class K8_MesajKaydi(Base):
    def setUp(self):
        super().setUp()
        self.i = AI.AgentIdentity.load_or_create("hermes")
        self.cid = AI.open_conversation("user", "ahmet", "cli", identity=self.i)

    def test_seq_monoton_ve_msg_id_tekil(self):
        ids = [AI.log_message(self.cid, "in" if n % 2 == 0 else "out", f"m{n}")
               for n in range(5)]
        self.assertEqual(len(set(ids)), 5)
        self.assertEqual(ids[0], f"{self.cid}#1")
        self.assertEqual(ids[-1], f"{self.cid}#5")
        rows = AI.list_conversations(self.i.runtime)
        self.assertEqual(rows[0]["msg_count"], 5)

    def test_icerik_saklanmaz_sadece_ozet(self):
        import sqlite3
        gizli = "Ahmet'in özel mesajı 12345"
        mid = AI.log_message(self.cid, "in", gizli)
        c = sqlite3.connect(str(AI.conv_db_path(self.i.runtime)))
        row = c.execute("SELECT sha256, bytes FROM messages WHERE msg_id=?",
                        (mid,)).fetchone()
        c.close()
        import hashlib
        self.assertEqual(row[0], hashlib.sha256(gizli.encode()).hexdigest())
        self.assertEqual(row[1], len(gizli.encode()))
        raw = AI.conv_db_path(self.i.runtime).read_bytes()
        self.assertNotIn(b"12345", raw, "mesaj metni DB'ye yazılmamalı")

    def test_bilinmeyen_sohbet_red(self):
        with self.assertRaises(KeyError):
            AI.log_message("u.yok.yok.yok.yok", "in", "x")

    def test_gecersiz_yon_red(self):
        with self.assertRaises(ValueError):
            AI.log_message(self.cid, "yan", "x")


class K9_Ulid(Base):
    def test_kronolojik_ve_tekil(self):
        a = AI.ulid()
        time.sleep(0.002)
        b = AI.ulid()
        self.assertEqual(len(a), 26)
        self.assertLess(a, b, "ULID zamanla artmalı (sözlük sırası = kronoloji)")
        self.assertEqual(len({AI.ulid() for _ in range(2000)}), 2000)

    def test_sadece_crockford_karakterleri(self):
        self.assertTrue(set(AI.ulid()) <= set(AI._C32))


class K10_DonanimParmakIzi(Base):
    def test_gercek_makinede_kaynak_bulunur(self):
        hw = AI.hw_fingerprint()
        self.assertEqual(len(hw["fingerprint"]), 32)
        self.assertIn("arch", hw["sources"])
        self.assertEqual(hw["strength"], "strong" if len(
            [s for s in hw["sources"] if s != "arch"]) >= 2 else hw["strength"])

    def test_deterministik(self):
        src = AI.hw_sources()
        self.assertEqual(AI.hw_fingerprint(src)["fingerprint"],
                         AI.hw_fingerprint(src)["fingerprint"])

    def test_kaynak_degisimi_parmak_izini_degistirir(self):
        src = AI.hw_sources()
        f1 = AI.hw_fingerprint(src)["fingerprint"]
        src2 = dict(src)
        src2["mac"] = "aabbccddeeff"
        self.assertNotEqual(f1, AI.hw_fingerprint(src2)["fingerprint"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
