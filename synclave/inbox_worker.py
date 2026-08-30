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
import json
import os
import subprocess
import time

INBOX = os.path.expanduser("~/.hermes/a2a_inbox")
CUMULUS_DIR = os.path.expanduser("~/cumulusos")

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
    return None, None

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
            print(f"hata {f}: {e}")
    if done == 0:
        print("yeni görev yok")
    return done

if __name__ == "__main__":
    process_inbox()
