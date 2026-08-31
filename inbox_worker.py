#!/usr/bin/env python3
"""
inbox_worker.py — A2A inbox görev işleyici (v0.1, 29 Ağu 2026)

H3'te (veya herhangi bir node'da) a2a_inbox/*.json görevlerini işler.
GÜVENLİK: SADECE allowlist komutlar çalıştırılır; desteklenmeyen görev RED.
Görev formatı (H1 a2a_cli send ile gelir):
  - "status"            → makine durumu (hostname/df)
  - "uptime"            → uptime
  - "test:<modul>"      → H3 cumulusos make sanitizer-tests
  - "shell:ls -la"      → allowlist shell (ls/df/uptime/hostname)

Sonuç: aynı JSON'a yazılır (status: done/rejected + result) → H1 task/get ile okur.
"""
import glob
import hashlib
import json
import os
import posixpath
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

INBOX = os.path.expanduser("~/.hermes/a2a_inbox")
CUMULUS_DIR = os.path.expanduser("~/cumulusos")
UPDATE_REPO = os.path.expanduser(os.environ.get("A2A_UPDATE_REPO", "~/cumulus-sync-motor"))
UPDATE_FILES = ("a2a_cli.py", "agent_mesh_a2a.py", "sync_motor.py", "inbox_worker.py")
UPDATE_HOSTS = {"100.92.2.47", "127.0.0.1", "localhost"}

ALLOWLIST = {
    "status": ["hostname"],
    "uptime": ["uptime"],
    "df": ["df", "-h", "/"],
    "ls": ["ls", "-la"],
    "git-status": ["git", "status", "--short"],
    "git-log": ["git", "log", "--oneline", "-5"],
}

def run(cmd, timeout=600):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "")[-2000:]
        if r.stderr:
            out += "\n[ERR] " + r.stderr[-500:]
        return out.strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:
        return f"hata: {e}"

def parse_task(text):
    t = (text or "").strip()
    if t == "status":
        return "status", []
    if t == "uptime":
        return "uptime", []
    if t.startswith("df"):
        return "df", []
    if t.startswith("test:"):
        return "test-suite", [t[5:].strip()]
    if t.startswith("shell:"):
        parts = t[6:].strip().split()
        if parts and parts[0] in ALLOWLIST:
            return parts[0], parts[1:]
    if t.startswith("agent-update:"):
        values = {}
        for item in t[len("agent-update:"):].split():
            if "=" in item:
                key, value = item.split("=", 1)
                values[key] = value
        url = values.get("url", "")
        digest = values.get("sha256", "").lower()
        parsed = urllib.parse.urlparse(url)
        if (parsed.scheme not in ("http", "https") or
                parsed.hostname not in UPDATE_HOSTS or
                not digest or len(digest) != 64 or
                any(c not in "0123456789abcdef" for c in digest)):
            return None, None
        return "agent-update", [{"url": url, "sha256": digest}]
    return None, None


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_update_members(tar):
    members = tar.getmembers()
    expected = {"a2a_update/" + name for name in UPDATE_FILES}
    allowed_files = expected | {"MANIFEST.sha256", "a2a_update/VERSION"}
    normalized_names = {}
    for member in members:
        name = posixpath.normpath(member.name)
        if name.startswith("../") or name.startswith("/"):
            raise ValueError("pakette güvensiz yol var")
        name = name.removeprefix("./")
        normalized_names[member.name] = name
    normalized = {name for member in members if member.isfile()
                  for name in (normalized_names[member.name],)}
    if not expected.issubset(normalized) or not normalized.issubset(allowed_files):
        raise ValueError("paket dosya listesi allowlist ile eşleşmiyor")
    for member in members:
        name = normalized_names[member.name]
        if member.isfile() and name not in allowed_files:
            raise ValueError("pakette güvensiz veya beklenmeyen üye var")
        if member.isfile() and name in expected and member.name != name:
            # ./prefix güvenli bir tar yazım biçimidir; diğer dönüşümler reddedilir.
            if member.name != "./" + name:
                raise ValueError("güncelleme yolu normalize edilemedi")
    return members


def apply_agent_update(archive_path, expected_sha256, staging_dir=None):
    """Manifestli A2A paketini staging'de doğrula, üç dosyayı atomik güncelle."""
    archive = os.path.abspath(archive_path)
    if _sha256(archive) != expected_sha256.lower():
        raise ValueError("paket SHA-256 eşleşmiyor")
    stage = Path(staging_dir or tempfile.mkdtemp(prefix="a2a_update_stage_"))
    created_stage = staging_dir is None
    try:
        stage.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as tar:
            _safe_update_members(tar)
            tar.extractall(stage)
        source_dir = stage / "a2a_update"
        backup_dir = Path(UPDATE_REPO) / (".a2a_backup_" + time.strftime("%Y%m%d_%H%M%S"))
        backup_dir.mkdir(parents=True, exist_ok=False)
        for name in UPDATE_FILES:
            target = Path(UPDATE_REPO) / name
            if not target.is_file():
                raise ValueError(f"hedef dosya yok: {target}")
            shutil.copy2(target, backup_dir / name)
        for name in UPDATE_FILES:
            source = source_dir / name
            target = Path(UPDATE_REPO) / name
            tmp = target.with_name(target.name + ".a2a-new")
            shutil.copy2(source, tmp)
            os.replace(tmp, target)
        return {"status": "done", "repo": UPDATE_REPO,
                "files": list(UPDATE_FILES), "backup": str(backup_dir),
                "sha256": expected_sha256.lower()}
    finally:
        if created_stage:
            shutil.rmtree(stage, ignore_errors=True)


def run_agent_update(url, expected_sha256):
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname not in UPDATE_HOSTS:
        raise ValueError("güncelleme kaynağı allowlist dışında")
    filename = os.path.basename(parsed.path)
    if filename != "A2A_UPDATE_20260831.tar.gz":
        raise ValueError("beklenmeyen güncelleme paketi")
    with tempfile.TemporaryDirectory(prefix="a2a_update_download_") as td:
        archive = os.path.join(td, filename)
        request = urllib.request.Request(url, headers={"User-Agent": "cumulus-a2a-updater"})
        with urllib.request.urlopen(request, timeout=60) as response, open(archive, "wb") as output:
            shutil.copyfileobj(response, output)
        return apply_agent_update(archive, expected_sha256)

def process_inbox():
    os.makedirs(INBOX, exist_ok=True)
    done = 0
    for f in sorted(glob.glob(os.path.join(INBOX, "*.json"))):
        try:
            d = json.loads(open(f, encoding="utf-8").read())
            if d.get("status") != "new":
                continue
            key, args = parse_task(d.get("text", ""))
            if key is None:
                d["status"] = "rejected"
                d["result"] = {"error": "desteklenmeyen görev (allowlist dışı)"}
            elif key == "test-suite":
                modul = args[0] if args else ""
                if not modul:
                    d["status"] = "rejected"
                    d["result"] = {"error": "test:<modul> gerekli"}
                else:
                    # H3 cumulusos'ta ilgili testi çalıştır
                    old = os.getcwd()
                    os.chdir(CUMULUS_DIR)
                    out = run(["make", "sanitizer-tests"])
                    os.chdir(old)
                    d["status"] = "done"
                    d["result"] = {"output": out[-1500:], "modul": modul}
            elif key == "agent-update":
                d["result"] = run_agent_update(args[0]["url"], args[0]["sha256"])
                d["status"] = "done"
            else:
                cmd = list(ALLOWLIST[str(key)])
                if key == "ls" and args:
                    cmd += args
                out = run(cmd)
                d["status"] = "done"
                d["result"] = {"output": out[-1500:]}
            d["processed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            with open(f, "w", encoding="utf-8") as wf:
                json.dump(d, wf, ensure_ascii=False, indent=2)
            print(f"işlendi: {os.path.basename(f)} → {d['status']}")
            done += 1
        except Exception as e:
            # Bozuk/uygunsuz görev new kalırsa her timer'da tekrar denenir.
            # Hata kalıcı olarak rejected yazılır; dosya silinmez.
            try:
                failed = json.loads(open(f, encoding="utf-8").read())
                if failed.get("status") == "new":
                    failed["status"] = "rejected"
                    failed["result"] = {"error": str(e)[:500]}
                    failed["processed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    with open(f, "w", encoding="utf-8") as wf:
                        json.dump(failed, wf, ensure_ascii=False, indent=2)
            except Exception as write_error:
                print(f"hata kaydı yazılamadı {f}: {write_error}")
            print(f"hata {f}: {e}")
            done += 1

    if done == 0:
        print("yeni görev yok")
    return done

if __name__ == "__main__":
    process_inbox()
