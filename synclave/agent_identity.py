#!/usr/bin/env python3
"""
agent_identity.py — Ajan kimliği + sohbet etiketleme (CumulusNET mesh, v1.0)

AMAÇ (30 Ağu 2026 kullanıcı talebi):
  1. Mesh'e bağlı HER çalışma zamanı (Hermes agent, OpenClaw) için kopyalanamaz
     — daha doğrusu KOPYALANDIĞINDA TESPİT EDİLEBİLİR — kalıcı bir kimlik.
  2. Her sohbetin (kullanıcı↔ajan ve ajan↔ajan) ayrı, çakışmayan, kalıcı ID'si;
     hangi ajanın hangi karşı tarafla hangi kanalda konuştuğu asla karışmaz.

DÜRÜST SINIR (fizik):
  TPM/secure element olmadan saf yazılımda "kopyalanamaz" ID ÜRETİLEMEZ. Özel
  anahtar dosyası kopyalanabilir. Bu modülün verdiği garanti şudur:
    - Kimlik kriptografiktir (Ed25519); agent_id açık anahtarın özetidir.
    - Kimlik donanım parmak izine BAĞLANIR (machine-id, DMI UUID, MAC, CPU...).
    - Anahtar başka makineye kopyalanırsa parmak izi uyuşmaz → clone_state
      "suspected" olur ve mesh tarafı FAIL-CLOSED reddeder (403).
    - Meşru donanım değişikliği (VPS taşıma) yalnız açık onaylı `rekey` ile
      yeni agent_id üretir; eski kimlik superseded olarak arşivlenir.
  Yani: kopyalama engellenmez, KANITLANABİLİR ŞEKİLDE TESPİT EDİLİR ve reddedilir.

DOSYALAR (runtime'a göre ayrı — aynı makinede Hermes ve OpenClaw AYRI kimliktir):
  Hermes  : ~/.hermes/identity/{agent_ed25519.key, agent_identity.json, peers.json, conversations.db}
  OpenClaw: ~/.openclaw/identity/...
  Override: AGENT_IDENTITY_DIR

KULLANIM (CLI):
  python3 agent_identity.py show            # kimliği yaz (yoksa oluştur)
  python3 agent_identity.py fingerprint     # donanım parmak izi kaynakları
  python3 agent_identity.py rekey --confirm # donanım değişti, yeni kimlik
  python3 agent_identity.py peers           # tanınan ajanlar (TOFU)
  python3 agent_identity.py conv-open --kind user --peer ahmet --channel telegram
  python3 agent_identity.py conv-list
"""
from __future__ import annotations

# Statik analiz notu: cryptography import'u try/except ile korunuyor ve her
# kullanım noktası CRYPTO_OK ile kapılıdır; Pyright'ın "possibly None" gürültüsü
# çalışma zamanı davranışını yansıtmaz.
# pyright: reportOptionalMemberAccess=false, reportInvalidTypeForm=false

import base64
import hashlib
import json
import os
import platform
import secrets
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey, X25519PublicKey)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTO_OK = True
except Exception:  # pragma: no cover - kurulum eksikse açıkça söyle
    Ed25519PrivateKey = Ed25519PublicKey = serialization = None  # type: ignore
    X25519PrivateKey = X25519PublicKey = AESGCM = None  # type: ignore
    CRYPTO_OK = False

SCHEMA_VERSION = 1
SIG_MAX_SKEW_S = 120          # imza zaman penceresi (replay koruması)
_NONCE_CACHE: dict[str, float] = {}   # nonce → görülme zamanı

# Crockford Base32 (ULID) — okunabilir, I/L/O/U yok
_C32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


# ─────────────────────────── yardımcılar ──────────────────────────────
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(txt: str) -> bytes:
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)


def _c32_encode(num: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_C32[num & 31])
        num >>= 5
    return "".join(reversed(out))


def _atomic_write(path: Path, data: bytes):
    """Atomik yazma — OCEANAPI denetimi #3 (ORTA): kısmi dosya/crash koruması.
    Geçici dosyaya yaz → fsync → os.replace (aynı dizinde atomik rename)."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))


def ulid() -> str:
    """Zaman sıralı 26 karakter ID (48-bit ms + 80-bit rastgele).
    UUID4'ten farkı: kronolojik sıralanır → sohbetler zaman sırasında durur."""
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = secrets.randbits(80)
    return _c32_encode(ms, 10) + _c32_encode(rand, 16)


def _run(cmd: list[str], timeout: int = 5) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _read(path: str) -> str:
    try:
        return Path(path).read_text(errors="ignore").strip()
    except Exception:
        return ""


# ─────────────────── donanım parmak izi (platform bağımsız) ───────────
def hw_sources() -> dict[str, str]:
    """Kalıcı donanım/OS kökleri. Boş değerler dışlanır.
    Linux'ta machine-id ve DMI UUID aynı olabilir (VPS) — ikisi de saklanır,
    çünkü biri silinip diğeri kalabilir; imza kaynak-adı ile hesaplanır."""
    src: dict[str, str] = {}
    system = platform.system()
    if system == "Linux":
        for key, path in (("machine_id", "/etc/machine-id"),
                          ("dbus_machine_id", "/var/lib/dbus/machine-id"),
                          ("dmi_product_uuid", "/sys/class/dmi/id/product_uuid"),
                          ("dmi_board_serial", "/sys/class/dmi/id/board_serial"),
                          ("dmi_product_serial", "/sys/class/dmi/id/product_serial")):
            v = _read(path)
            if v and v.lower() not in ("none", "to be filled by o.e.m.", "0"):
                src[key] = v
    elif system == "Darwin":
        out = _run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"])
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                src["ioplatform_uuid"] = line.split('"')[-2]
    elif system == "Windows":
        v = _run(["powershell", "-NoProfile", "-Command",
                  "(Get-CimInstance Win32_ComputerSystemProduct).UUID"])
        if v:
            src["win_csproduct_uuid"] = v
        v = _run(["powershell", "-NoProfile", "-Command",
                  "(Get-CimInstance Win32_BIOS).SerialNumber"])
        if v:
            src["win_bios_serial"] = v
    # her platformda: birincil MAC (uuid.getnode rastgele ise 2. bit set olur)
    node = uuid.getnode()
    if not (node >> 40) & 0x01:          # multicast bit = uydurma MAC işareti
        src["mac"] = f"{node:012x}"
    src["arch"] = f"{platform.system()}/{platform.machine()}"
    return src


def hw_fingerprint(src: dict[str, str] | None = None) -> dict:
    """Kaynaklardan tek parmak izi. strength: kaç KALICI kaynak var."""
    src = hw_sources() if src is None else src
    stable = {k: v for k, v in src.items() if k != "arch"}
    blob = "|".join(f"{k}={src[k]}" for k in sorted(src))
    fp = hashlib.sha256(blob.encode()).hexdigest()[:32]
    # kaynak başına ayrı özet: hangi kaynağın değiştiğini söyleyebilmek için
    per = {k: hashlib.sha256(f"{k}={v}".encode()).hexdigest()[:12]
           for k, v in src.items()}
    return {
        "fingerprint": fp,
        "sources": sorted(src.keys()),
        "per_source": per,
        "strength": "strong" if len(stable) >= 2 else ("weak" if stable else "none"),
    }


# ───────────────────────────── kimlik ─────────────────────────────────
def detect_runtime() -> str:
    """Hangi çalışma zamanı: hermes | openclaw. Env ile zorlanabilir."""
    r = os.environ.get("AGENT_RUNTIME", "").strip().lower()
    if r in ("hermes", "openclaw"):
        return r
    # OpenClaw süreci içinden çağrıldıysa kendi dizinini kullan
    if os.environ.get("OPENCLAW_HOME") or os.environ.get("OPENCLAW_SESSION"):
        return "openclaw"
    return "hermes"


_PREFIX = {"hermes": "hx", "openclaw": "oc"}


def identity_dir(runtime: str | None = None) -> Path:
    env = os.environ.get("AGENT_IDENTITY_DIR")
    if env:
        return Path(env).expanduser()
    runtime = runtime or detect_runtime()
    base = "~/.openclaw" if runtime == "openclaw" else "~/.hermes"
    return Path(base).expanduser() / "identity"


class CloneDetected(Exception):
    """Kimlik dosyası başka donanımda kullanılıyor (kopya şüphesi)."""


class AgentIdentity:
    """Kalıcı ajan kimliği: Ed25519 anahtar + donanım bağı + klon tespiti."""

    def __init__(self, meta: dict, priv: "Ed25519PrivateKey | None", d: Path):
        self.meta = meta
        self._priv = priv
        self.dir = d
        self._xpriv: "X25519PrivateKey | None" = None
        xk = d / "agent_x25519.key"
        if xk.exists():
            try:
                self._xpriv = X25519PrivateKey.from_private_bytes(xk.read_bytes()[:32])
            except Exception:
                self._xpriv = None

    # ---- oluşturma / yükleme ----
    @classmethod
    def load_or_create(cls, runtime: str | None = None,
                       user_id: str = "", strict: bool = False) -> "AgentIdentity":
        if not CRYPTO_OK:
            raise RuntimeError("cryptography paketi gerekli: pip install cryptography")
        runtime = runtime or detect_runtime()
        d = identity_dir(runtime)
        d.mkdir(parents=True, exist_ok=True)
        key_f, meta_f = d / "agent_ed25519.key", d / "agent_identity.json"

        if key_f.exists() and meta_f.exists():
            priv = Ed25519PrivateKey.from_private_bytes(key_f.read_bytes()[:32])
            meta = json.loads(meta_f.read_text())
            # ── OCEANAPI DENETİMİ #1 (YÜKSEK): meta ↔ özel anahtar doğrulaması
            # Metadata değiştirilmişse (sahte public_key/agent_id) fail-closed:
            # kimlik dosyaları tutarsız → yükleme REDDEDİLİR, sessiz kabul YOK.
            try:
                derived_pub = priv.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw)
                if _b64(derived_pub) != meta.get("public_key"):
                    raise ValueError("public_key metadata ile özel anahtar uyuşmuyor")
                if AgentIdentity._derive_id(runtime, derived_pub) != meta.get("agent_id"):
                    raise ValueError("agent_id metadata ile anahtar uyuşmuyor")
            except Exception as e:
                raise RuntimeError(
                    f"kimlik tutarsız (meta-anahtar doğrulaması): {e} — "
                    "düzeltme: kimlik dizinini yedekleyip agent_identity.py rekey --confirm "
                    "çalıştırın") from e
            # X25519 (şifreleme) anahtarı eksikse oluştur (v1.1 yükseltmesi)
            xk_f = d / "agent_x25519.key"
            if not xk_f.exists() or "x25519_public" not in meta:
                xpriv = X25519PrivateKey.generate()
                xpub = xpriv.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw)
                _atomic_write(xk_f, xpriv.private_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PrivateFormat.Raw,
                    encryption_algorithm=serialization.NoEncryption()))
                meta["x25519_public"] = _b64(xpub)
                _atomic_write(d / "agent_identity.json",
                              json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
            else:
                # ── OCEANAPI DENETİMİ #2 (ORTA): X25519 public ↔ özel anahtar
                xpriv = X25519PrivateKey.from_private_bytes(xk_f.read_bytes()[:32])
                derived_x = xpriv.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw)
                if _b64(derived_x) != meta.get("x25519_public"):
                    raise RuntimeError(
                        "x25519_public metadata ile özel anahtar uyuşmuyor — rekey gerekli")
            ident = cls(meta, priv, d)
            ident._refresh_clone_state(save=True)
            if strict:
                ident.assert_not_clone()
            return ident

        # yeni kimlik
        priv = Ed25519PrivateKey.generate()
        raw_priv = priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption())
        pub_raw = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        xpriv = X25519PrivateKey.generate()
        xpub_raw = xpriv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        hw = hw_fingerprint()
        agent_id = cls._derive_id(runtime, pub_raw)
        meta = {
            "schema": SCHEMA_VERSION,
            "agent_id": agent_id,
            "runtime": runtime,
            "public_key": _b64(pub_raw),
            "x25519_public": _b64(xpub_raw),
            "user_id": user_id or os.environ.get("SYNC_USER_ID", "cumulusnet"),
            "machine_label": _hostname(),
            "hw_fingerprint": hw["fingerprint"],
            "hw_sources": hw["sources"],
            "hw_per_source": hw["per_source"],
            "hw_strength": hw["strength"],
            "install_epoch": int(time.time()),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "clone_state": "clean",
            "boot_count": 1,
        }
        _atomic_write(key_f, raw_priv)
        xk_f = d / "agent_x25519.key"
        _atomic_write(xk_f, xpriv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()))
        _atomic_write(meta_f, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
        os.chmod(meta_f, 0o644)
        return cls(meta, priv, d)

    @staticmethod
    def _derive_id(runtime: str, pub_raw: bytes) -> str:
        digest = hashlib.sha256(b"cumulus-agent-v1|" + runtime.encode() + b"|" + pub_raw).digest()
        num = int.from_bytes(digest[:15], "big")
        return f"{_PREFIX.get(runtime, 'ag')}-{_c32_encode(num, 24).lower()}"

    # ---- klon tespiti ----
    def _refresh_clone_state(self, save: bool = False) -> dict:
        hw = hw_fingerprint()
        prev_fp = self.meta.get("hw_fingerprint", "")
        changed = [k for k, v in hw["per_source"].items()
                   if self.meta.get("hw_per_source", {}).get(k, v) != v]
        gone = [k for k in self.meta.get("hw_sources", []) if k not in hw["per_source"]]
        if hw["fingerprint"] == prev_fp:
            state, detail = "clean", {}
        else:
            # 'arch' tek başına değiştiyse (OS yükseltmesi) uyarı; kalıcı kök
            # değiştiyse kopya şüphesi — fail-closed tarafı bunu reddeder.
            hard = [k for k in changed + gone if k != "arch"]
            state = "suspected" if hard else "drifted"
            detail = {"changed": changed, "missing": gone,
                      "live_fingerprint": hw["fingerprint"], "stored": prev_fp}
        self.meta["clone_state"] = state
        self.meta["clone_detail"] = detail
        self.meta["hw_strength"] = hw["strength"]
        self.meta["boot_count"] = int(self.meta.get("boot_count", 0)) + (1 if save else 0)
        if save:
            _atomic_write(self.dir / "agent_identity.json",
                          json.dumps(self.meta, ensure_ascii=False, indent=2).encode("utf-8"))
        return {"state": state, "detail": detail}

    def assert_not_clone(self):
        if self.meta.get("clone_state") == "suspected":
            raise CloneDetected(
                f"{self.agent_id}: donanım parmak izi uyuşmuyor "
                f"({self.meta.get('clone_detail', {}).get('changed')}). "
                "Meşruysa: agent_identity.py rekey --confirm")

    def rekey(self, confirm: bool = False, reason: str = "") -> "AgentIdentity":
        """Donanım meşru şekilde değiştiyse YENİ kimlik üret; eskisini arşivle."""
        if not confirm:
            raise ValueError("rekey için --confirm gerekli (yeni agent_id üretilir)")
        # ── OCEANAPI DENETİMİ #4 (ORTA→YÜKSEK): güvenli geçiş.
        # Eski dosyalar SİLİNMEDEN önce yeni kimlik geçici dosyalarda üretilir;
        # hepsi hazır olduktan sonra atomik taşınır. Her an geçerli kimlik var —
        # crash/kısmi hata durumunda kimlik KAYBI yaşanmaz.
        hist_f = self.dir / "identity_history.json"
        hist = json.loads(hist_f.read_text()) if hist_f.exists() else []
        old = dict(self.meta)
        old["superseded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        old["supersede_reason"] = reason or "hardware_change"
        # 1) Yeni anahtar çiftleri üret (geçici dosyalara)
        new_priv = Ed25519PrivateKey.generate()
        new_xpriv = X25519PrivateKey.generate()
        new_pub = new_priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        new_xpub = new_xpriv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        new_id = AgentIdentity._derive_id(self.runtime, new_pub)
        new_meta = dict(self.meta)
        new_meta.update({
            "agent_id": new_id,
            "public_key": _b64(new_pub),
            "x25519_public": _b64(new_xpub),
            "supersedes": old["agent_id"],
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "install_epoch": int(time.time()),
            "clone_state": "clean",
            "boot_count": 1,
        })
        tmp_key = self.dir / "agent_ed25519.key.new"
        tmp_xkey = self.dir / "agent_x25519.key.new"
        tmp_meta = self.dir / "agent_identity.json.new"
        _atomic_write(tmp_key, new_priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()))
        _atomic_write(tmp_xkey, new_xpriv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()))
        _atomic_write(tmp_meta, json.dumps(new_meta, ensure_ascii=False, indent=2).encode("utf-8"))
        # 2) Eski kimliği arşivle (superseded_by = yeni id) — atomik
        old["superseded_by"] = new_id
        hist.append(old)
        _atomic_write(hist_f, json.dumps(hist, ensure_ascii=False, indent=2).encode("utf-8"))
        # 3) Yeni dosyaları ATOMIK taşı (her an geçerli kimlik)
        os.replace(str(tmp_key), str(self.dir / "agent_ed25519.key"))
        os.replace(str(tmp_xkey), str(self.dir / "agent_x25519.key"))
        os.replace(str(tmp_meta), str(self.dir / "agent_identity.json"))
        os.chmod(self.dir / "agent_ed25519.key", 0o600)
        os.chmod(self.dir / "agent_x25519.key", 0o600)
        # 4) Yeni nesneyi döndür
        return AgentIdentity(new_meta, new_priv, self.dir)

    # ---- özellikler ----
    @property
    def agent_id(self) -> str:
        return self.meta["agent_id"]

    @property
    def runtime(self) -> str:
        return self.meta.get("runtime", "hermes")

    @property
    def short(self) -> str:
        return self.agent_id.split("-", 1)[1][:8]

    @property
    def public_key(self) -> str:
        return self.meta["public_key"]

    def card(self) -> dict:
        """A2A AgentCard'a gömülecek açık kimlik (özel anahtar yok)."""
        return {k: self.meta.get(k) for k in (
            "agent_id", "runtime", "public_key", "x25519_public", "user_id",
            "machine_label", "hw_fingerprint", "hw_strength", "install_epoch",
            "clone_state", "boot_count", "schema")}

    # ---- imzalama ----
    def sign_blob(self, blob: bytes) -> str:
        return _b64(self._priv.sign(blob))

    # ---- şifreleme (X25519 ECDH + AES-GCM, PFS) ----
    @property
    def x25519_public(self) -> str:
        return self.meta.get("x25519_public", "")

    def encrypt_for(self, peer_x25519_pub: str, plaintext: bytes) -> dict:
        """Karşı tarafın X25519 anahtarına şifrele (her mesajda ephemeral → PFS).

        Dönen: {"nonce": b64, "eph": b64(ephemeral pub), "ct": b64}
        Alıcı: kendi xpriv + eph ile ECDH → AES-GCM(nonce, ct)
        """
        if not CRYPTO_OK or not self._xpriv:
            raise RuntimeError("şifreleme için X25519 anahtarı yok")
        eph = X25519PrivateKey.generate()
        shared = eph.exchange(X25519PublicKey.from_public_bytes(_unb64(peer_x25519_pub)))
        nonce = secrets.token_bytes(12)
        ct = AESGCM(shared).encrypt(nonce, plaintext, b"a2a-v1")
        eph_pub = eph.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        return {"nonce": _b64(nonce), "eph": _b64(eph_pub), "ct": _b64(ct)}

    def decrypt_from(self, peer_x25519_pub: str, env: dict) -> bytes:
        """encrypt_for çıktısını çöz. AAD 'a2a-v1' — kurcalama reddedilir."""
        if not CRYPTO_OK or not self._xpriv:
            raise RuntimeError("şifreleme için X25519 anahtarı yok")
        eph = X25519PublicKey.from_public_bytes(_unb64(env["eph"]))
        shared = self._xpriv.exchange(eph)
        return AESGCM(shared).decrypt(
            _unb64(env["nonce"]), _unb64(env["ct"]), b"a2a-v1")

    def secure_payload(self, peer_x25519_pub: str, body: bytes,
                       to_agent: str = "") -> dict:
        """Tek paket: imza + şifreleme + replay koruması (ts+nonce).

        to_agent: alıcının agent_id'si (boşsa kendi kimliğimiz yazılır —
        bu durumda alıcı kontrolü yapılamaz; gerçek kullanımda ALICI verilir).
        """
        env = self.encrypt_for(peer_x25519_pub, body)
        env["ts"] = str(int(time.time()))
        env["nonce2"] = secrets.token_hex(8)
        env["to_agent"] = to_agent
        canon = b"|".join([b"a2a-enc-v1", self.agent_id.encode(),
                           env["ts"].encode(), env["nonce2"].encode(),
                           env["to_agent"].encode(),
                           env["nonce"].encode(), env["eph"].encode(),
                           env["ct"].encode()])
        env["sig"] = self.sign_blob(canon)
        env["agent_id"] = self.agent_id
        env["public_key"] = self.public_key
        env["x25519_public"] = self.x25519_public
        return env

    @staticmethod
    def open_secure_payload(env: dict, identity: "AgentIdentity",
                            runtime: str | None = None) -> bytes:
        """secure_payload çıktısını doğrula + çöz (kimlik sahibi alıcı için)."""
        if env.get("to_agent") and env.get("to_agent") != identity.agent_id:
            raise ValueError("bu paket bana değil")
        try:
            skew = abs(time.time() - int(env.get("ts", "0")))
        except ValueError:
            skew = SIG_MAX_SKEW_S + 1
        if skew > SIG_MAX_SKEW_S:
            raise ValueError(f"stale_encrypted_payload({int(skew)}s)")
        nk = f"enc:{env.get('agent_id')}:{env.get('nonce2')}"
        now = time.time()
        for k, seen in list(_NONCE_CACHE.items()):
            if now - seen > SIG_MAX_SKEW_S * 2:
                _NONCE_CACHE.pop(k, None)
        if nk in _NONCE_CACHE:
            raise ValueError("replay_encrypted_payload")
        canon = b"|".join([b"a2a-enc-v1", env["agent_id"].encode(),
                           env["ts"].encode(), env["nonce2"].encode(),
                           env.get("to_agent", "").encode(),
                           env["nonce"].encode(), env["eph"].encode(),
                           env["ct"].encode()])
        Ed25519PublicKey.from_public_bytes(_unb64(env["public_key"])).verify(
            _unb64(env["sig"]), canon)
        _NONCE_CACHE[nk] = now
        return identity.decrypt_from(env["x25519_public"], env)

    def sign_request(self, method: str, body: bytes) -> dict:
        """A2A isteği için imza başlıkları. Kanonik: agent|ts|nonce|method|sha256(body)"""
        ts, nonce = str(int(time.time())), secrets.token_hex(8)
        blob = canonical_request(self.agent_id, ts, nonce, method, body)
        return {
            "X-Agent-Id": self.agent_id,
            "X-Agent-Ts": ts,
            "X-Agent-Nonce": nonce,
            "X-Agent-Sig": self.sign_blob(blob),
            "X-Agent-Key": self.public_key,
            "X-Agent-Runtime": self.runtime,
        }


def _hostname() -> str:
    try:
        return os.uname().nodename
    except AttributeError:
        return os.environ.get("COMPUTERNAME") or platform.node()


def canonical_request(agent_id: str, ts: str, nonce: str, method: str, body: bytes) -> bytes:
    return b"|".join([b"a2a-v1", agent_id.encode(), ts.encode(), nonce.encode(),
                      method.encode(), hashlib.sha256(body).hexdigest().encode()])


# ─────────────── peer kayıt defteri (TOFU) + doğrulama ────────────────
def peers_path(runtime: str | None = None) -> Path:
    return identity_dir(runtime) / "peers.json"


def load_peers(runtime: str | None = None) -> dict:
    p = peers_path(runtime)
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def save_peers(peers: dict, runtime: str | None = None):
    p = peers_path(runtime)
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(p, json.dumps(peers, ensure_ascii=False, indent=2).encode("utf-8"))


def verify_request(headers: dict, method: str, body: bytes,
                   runtime: str | None = None, require: bool = True) -> dict:
    """A2A isteğini doğrula. Dönen: {ok, agent_id, reason, first_seen}

    Kurallar (fail-closed):
      - imza yok + require → RED
      - agent_id ilk kez görülüyor → TOFU kaydı (first_seen=True)
      - agent_id biliniyor ama açık anahtar farklı → RED (kimlik taklidi/klon)
      - zaman penceresi ±120 s, nonce tekrarı → RED (replay)
    """
    def _get(name: str) -> str:
        return headers.get(name) or headers.get(name.lower()) or ""

    aid, sig, ts, nonce = (_get("X-Agent-Id"), _get("X-Agent-Sig"),
                           _get("X-Agent-Ts"), _get("X-Agent-Nonce"))
    key = _get("X-Agent-Key")
    if not (aid and sig and ts and nonce):
        return {"ok": not require, "agent_id": aid or "anonymous",
                "reason": "unsigned" if require else "unsigned_allowed"}
    if not CRYPTO_OK:
        return {"ok": False, "agent_id": aid, "reason": "crypto_missing"}
    try:
        skew = abs(time.time() - int(ts))
    except ValueError:
        return {"ok": False, "agent_id": aid, "reason": "bad_timestamp"}
    if skew > SIG_MAX_SKEW_S:
        return {"ok": False, "agent_id": aid, "reason": f"stale_timestamp({int(skew)}s)"}
    now = time.time()
    for k, seen in list(_NONCE_CACHE.items()):        # eski nonce'ları temizle
        if now - seen > SIG_MAX_SKEW_S * 2:
            _NONCE_CACHE.pop(k, None)
    nk = f"{aid}:{nonce}"
    if nk in _NONCE_CACHE:
        return {"ok": False, "agent_id": aid, "reason": "replay_nonce"}

    peers = load_peers(runtime)
    known = peers.get(aid)
    pub_b64 = (known or {}).get("public_key") or key
    if not pub_b64:
        return {"ok": False, "agent_id": aid, "reason": "no_public_key"}
    if known and key and known.get("public_key") != key:
        return {"ok": False, "agent_id": aid, "reason": "peer_key_mismatch"}
    # agent_id açık anahtarın özeti olmalı — uydurma ID kabul edilmez
    rt = _get("X-Agent-Runtime") or (known or {}).get("runtime") or "hermes"
    if AgentIdentity._derive_id(rt, _unb64(pub_b64)) != aid:
        return {"ok": False, "agent_id": aid, "reason": "id_key_mismatch"}
    try:
        Ed25519PublicKey.from_public_bytes(_unb64(pub_b64)).verify(
            _unb64(sig), canonical_request(aid, ts, nonce, method, body))
    except Exception:
        return {"ok": False, "agent_id": aid, "reason": "bad_signature"}

    _NONCE_CACHE[nk] = now
    first = known is None
    peers[aid] = {
        "public_key": pub_b64,
        "runtime": rt,
        "label": _get("X-Agent-Label") or (known or {}).get("label", ""),
        "first_seen": (known or {}).get("first_seen") or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "msg_count": int((known or {}).get("msg_count", 0)) + 1,
    }
    save_peers(peers, runtime)
    return {"ok": True, "agent_id": aid, "reason": "verified", "first_seen": first}


# ────────────────────── sohbet kayıt defteri ──────────────────────────
def conv_db_path(runtime: str | None = None) -> Path:
    return identity_dir(runtime) / "conversations.db"


_CONN_CACHE: dict[str, "sqlite3.Connection"] = {}
_CONN_LOCK = __import__("threading").Lock()


def _conn(runtime: str | None = None) -> sqlite3.Connection:
    """SQLite bağlantısını ÖNBELLEKLER (performans: 5.6ms -> ~0.5ms/mesaj).

    Aynı runtime için tek bağlantı yeniden kullanılır; kapanış işletim
    sistemine bırakılır (süreç sonunda). Farklı runtime'lar (hermes/openclaw)
    ayrı bağlantı tutar. WAL modu çoklu bağlantıya zaten izin verir.
    """
    p = conv_db_path(runtime)
    p.parent.mkdir(parents=True, exist_ok=True)
    key = str(p)
    with _CONN_LOCK:
        c = _CONN_CACHE.get(key)
        if c is None:
            c = sqlite3.connect(str(p), timeout=15)
            c.execute("PRAGMA journal_mode=WAL")
            # synchronous=NORMAL: WAL commit'inde fsync beklemez (checkpoint'te).
            # Sohbet defteri kritik veri DEĞİL (içerik saklamaz, sayaç+özet tutar);
            # OS çökmesinde son birkaç mesaj kaybolabilir — kabul edilebilir.
            # Maliyet: ~5ms commit -> ~0.2ms. Uygulama çökmesinde veri GÜVENDE.
            c.execute("PRAGMA synchronous=NORMAL")
            c.executescript("""
            CREATE TABLE IF NOT EXISTS conversations(
              conv_id TEXT PRIMARY KEY, kind TEXT NOT NULL, local_agent TEXT NOT NULL,
              peer_id TEXT NOT NULL, channel TEXT NOT NULL, label TEXT,
              created_ts REAL, last_ts REAL, msg_count INTEGER DEFAULT 0, meta TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_conv_scope
              ON conversations(kind, local_agent, peer_id, channel);
            CREATE TABLE IF NOT EXISTS messages(
              msg_id TEXT PRIMARY KEY, conv_id TEXT NOT NULL, seq INTEGER NOT NULL,
              direction TEXT NOT NULL, ts REAL, peer_id TEXT, sha256 TEXT,
              bytes INTEGER, meta TEXT);
            CREATE INDEX IF NOT EXISTS ix_msg_conv ON messages(conv_id, seq);
            """)
            _CONN_CACHE[key] = c
        return c


def open_conversation(kind: str, peer_id: str, channel: str, label: str = "",
                      identity: AgentIdentity | None = None,
                      runtime: str | None = None, meta: dict | None = None) -> str:
    """Sohbet ID'si al (idempotent: aynı kind+peer+channel → aynı ID).

    kind: "user"  → kullanıcı sohbeti  → u.<agent8>.<channel>.<peer8>.<ulid>
          "agent" → ajanlar arası      → a.<agent8>~<peer8>.<channel>.<ulid>
    """
    if kind not in ("user", "agent"):
        raise ValueError("kind: user | agent")
    ident = identity or AgentIdentity.load_or_create(runtime)
    peer_id = (peer_id or "unknown").strip()
    channel = (channel or "direct").strip().lower()
    with _conn(ident.runtime if runtime is None else runtime) as c:
        row = c.execute(
            "SELECT conv_id FROM conversations WHERE kind=? AND local_agent=? "
            "AND peer_id=? AND channel=?", (kind, ident.agent_id, peer_id, channel)
        ).fetchone()
        if row:
            return row[0]
        peer8 = (hashlib.sha256(peer_id.encode()).hexdigest()[:8] if kind == "user"
                 else peer_id.split("-", 1)[-1][:8])
        conv_id = (f"u.{ident.short}.{channel}.{peer8}.{ulid()}" if kind == "user"
                   else f"a.{ident.short}~{peer8}.{channel}.{ulid()}")
        now = time.time()
        c.execute("INSERT INTO conversations(conv_id,kind,local_agent,peer_id,channel,"
                  "label,created_ts,last_ts,msg_count,meta) VALUES(?,?,?,?,?,?,?,?,0,?)",
                  (conv_id, kind, ident.agent_id, peer_id, channel, label, now, now,
                   json.dumps(meta or {}, ensure_ascii=False)))
        return conv_id


def log_message(conv_id: str, direction: str, payload: str | bytes = b"",
                peer_id: str = "", runtime: str | None = None,
                meta: dict | None = None) -> str:
    """Mesajı kaydet → msg_id = <conv_id>#<seq>. İÇERİK SAKLANMAZ (sadece sha256)."""
    if direction not in ("in", "out"):
        raise ValueError("direction: in | out")
    raw = payload.encode() if isinstance(payload, str) else (payload or b"")
    with _conn(runtime) as c:
        row = c.execute("SELECT msg_count FROM conversations WHERE conv_id=?",
                        (conv_id,)).fetchone()
        if not row:
            raise KeyError(f"bilinmeyen conv_id: {conv_id}")
        seq = int(row[0]) + 1
        msg_id = f"{conv_id}#{seq}"
        now = time.time()
        c.execute("INSERT INTO messages(msg_id,conv_id,seq,direction,ts,peer_id,"
                  "sha256,bytes,meta) VALUES(?,?,?,?,?,?,?,?,?)",
                  (msg_id, conv_id, seq, direction, now, peer_id,
                   hashlib.sha256(raw).hexdigest(), len(raw),
                   json.dumps(meta or {}, ensure_ascii=False)))
        c.execute("UPDATE conversations SET msg_count=?, last_ts=? WHERE conv_id=?",
                  (seq, now, conv_id))
        return msg_id


def list_conversations(runtime: str | None = None, kind: str = "", limit: int = 50) -> list[dict]:
    q = ("SELECT conv_id,kind,local_agent,peer_id,channel,label,created_ts,last_ts,msg_count "
         "FROM conversations")
    args: tuple = ()
    if kind:
        q += " WHERE kind=?"
        args = (kind,)
    q += " ORDER BY last_ts DESC LIMIT ?"
    with _conn(runtime) as c:
        cols = ["conv_id", "kind", "local_agent", "peer_id", "channel", "label",
                "created_ts", "last_ts", "msg_count"]
        return [dict(zip(cols, r)) for r in c.execute(q, args + (limit,)).fetchall()]


# ─────────────────────────────── CLI ──────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Ajan kimliği + sohbet etiketleme")
    ap.add_argument("komut", choices=["show", "fingerprint", "rekey", "peers",
                                      "conv-open", "conv-list", "verify-self"])
    ap.add_argument("--runtime", choices=["hermes", "openclaw"], default=None)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--reason", default="")
    ap.add_argument("--kind", choices=["user", "agent"], default="user")
    ap.add_argument("--peer", default="")
    ap.add_argument("--channel", default="direct")
    ap.add_argument("--label", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.komut == "fingerprint":
        hw = hw_fingerprint()
        print(json.dumps({**hw, "raw_sources": hw_sources()}, ensure_ascii=False, indent=2))
        return 0

    ident = AgentIdentity.load_or_create(a.runtime)

    if a.komut == "show":
        card = ident.card()
        if a.json:
            print(json.dumps(card, ensure_ascii=False, indent=2))
        else:
            print(f"agent_id   : {card['agent_id']}")
            print(f"runtime    : {card['runtime']}   makine: {card['machine_label']}")
            print(f"kullanıcı  : {card['user_id']}")
            print(f"donanım fp : {card['hw_fingerprint']} ({card['hw_strength']})")
            print(f"klon durumu: {card['clone_state']}  boot: {card['boot_count']}")
            print(f"kurulum    : {ident.meta.get('created')}")
            print(f"dizin      : {ident.dir}")
            if card["clone_state"] != "clean":
                print(f"UYARI      : {json.dumps(ident.meta.get('clone_detail', {}), ensure_ascii=False)}")
        return 0

    if a.komut == "verify-self":
        st = ident._refresh_clone_state(save=False)
        blob = b"self-test"
        ok = True
        try:
            Ed25519PublicKey.from_public_bytes(_unb64(ident.public_key)).verify(
                _unb64(ident.sign_blob(blob)), blob)
        except Exception:
            ok = False
        derived = AgentIdentity._derive_id(ident.runtime, _unb64(ident.public_key))
        print(json.dumps({"agent_id": ident.agent_id, "signature_ok": ok,
                          "id_matches_key": derived == ident.agent_id,
                          "clone_state": st["state"], "detail": st["detail"]},
                         ensure_ascii=False, indent=2))
        return 0 if (ok and derived == ident.agent_id and st["state"] != "suspected") else 1

    if a.komut == "rekey":
        new = ident.rekey(confirm=a.confirm, reason=a.reason)
        print(f"eski: {ident.agent_id}\nyeni: {new.agent_id}  (history: identity_history.json)")
        return 0

    if a.komut == "peers":
        print(json.dumps(load_peers(ident.runtime), ensure_ascii=False, indent=2))
        return 0

    if a.komut == "conv-open":
        cid = open_conversation(a.kind, a.peer, a.channel, a.label, identity=ident)
        print(cid)
        return 0

    if a.komut == "conv-list":
        rows = list_conversations(ident.runtime, a.kind if a.kind else "")
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print(f"{'KIND':6} {'MSG':>5}  {'PEER':22} {'CHANNEL':10} CONV_ID")
            for r in rows:
                print(f"{r['kind']:6} {r['msg_count']:>5}  {r['peer_id'][:22]:22} "
                      f"{r['channel'][:10]:10} {r['conv_id']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
