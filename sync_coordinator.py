#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_coordinator.py — Çoklu Makine Koordinatörü (v1.0)
=======================================================
node_agent'ların GDrive hub'a yazdığı status.json dosyalarını toplar,
eşitlik matrisi üretir ve web panelini besler.

  sync_coordinator.py status            → tüm makinelerin durum tablosu
  sync_coordinator.py status --json     → JSON (panel / agent okur)
  sync_coordinator.py machines          → bilinen makine listesi
  sync_coordinator.py check <makine>    → tek makine eşitlik kontrolü

HUB YAPISI (her makinenin node_agent'ı yazar):
  gdrive:hermes-sync/<user>/<machine>/status.json
  gdrive:hermes-sync/<user>/<machine>/versions/...   (opsiyonel)

Geliştiren: CumulusNET Mühendislik — 2026
"""

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

GDRIVE_HUB = "gdrive:hermes-sync"
DEFAULT_USER = "hahmet"
RUN_STATE = Path(os.path.expanduser("~/.hermes/state/sync_last_run.json"))

def machine_id() -> str:
    try:
        return socket.gethostname().lower().split(".")[0]
    except Exception:
        return "unknown"

def run(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except Exception as e:
        return -1, "", str(e)

def list_machines() -> list:
    """GDrive hub'daki makine dizinlerini listele."""
    rc, out, err = run(["rclone", "lsd", f"{GDRIVE_HUB}/{DEFAULT_USER}", "--max-depth", "1"],
                       timeout=90)
    if rc != 0:
        return []
    machines = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            machines.append(parts[-1])
    return machines

def fetch_status(machine: str) -> dict:
    """Bir makinenin status.json'ını GDrive'dan çek."""
    import tempfile
    tmp = tempfile.mkdtemp(prefix="coord_")
    dst = f"{GDRIVE_HUB}/{DEFAULT_USER}/{machine}/status.json"
    rc, _, err = run(["rclone", "copyto", dst, os.path.join(tmp, "status.json"),
                      "--ignore-checksum", "--no-traverse"], timeout=90)
    if rc != 0:
        return {"machine": machine, "error": err.strip()[:120]}
    try:
        st = json.load(open(os.path.join(tmp, "status.json")))
        return st
    except Exception as e:
        return {"machine": machine, "error": f"parse: {e}"}

def collect() -> dict:
    """Tüm makinelerin durumunu topla → eşitlik matrisi."""
    machines = list_machines()
    rows = []
    for m in machines:
        st = fetch_status(m)
        rows.append(st)
    # yerel makine her zaman ekle (henüz hub'a yazmamış olabilir)
    me = machine_id()
    if me not in [r.get("machine") for r in rows]:
        rows.append({"machine": me, "local": True})
    return {"ts": datetime.now().isoformat(), "machines": rows,
            "count": len(rows)}

def print_table(rows: list):
    print(f"{'MAKİNE':<18} {'OS':<12} {'SYNC':<6} {'BAKUP':<6} {'ÇAKIŞMA':<8} SON_KOŞU")
    print("-" * 80)
    for r in rows:
        if "error" in r and not r.get("ts"):
            print(f"{r.get('machine','?'):<18} {'—':<12} {'HATA':<6} {'—':<6} {r['error'][:40]}")
            continue
        sync = r.get("son_kosu", {}).get("rc") if r.get("son_kosu") else None
        bkp = r.get("backup", {}).get("rc") if r.get("backup") else None
        last = (r.get("son_kosu", {}).get("ts") or r.get("ts") or "?")[:19]
        print(f"{r.get('machine','?'):<18} {r.get('os','?')[:12]:<12} "
              f"{'✅' if sync == 0 else (sync if sync is not None else '?')!s:<6} "
              f"{'✅' if bkp == 0 else (bkp if bkp is not None else '?')!s:<6} "
              f"{r.get('conflict_count', 0)!s:<8} {last}")

def main(argv=None):
    ap = argparse.ArgumentParser(prog="sync_coordinator",
                                 description="Çoklu makine eşitlik koordinatörü")
    ap.add_argument("komut", nargs="?", default="status",
                    choices=["status", "machines", "check"])
    ap.add_argument("makine", nargs="?")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.komut == "machines":
        ms = list_machines()
        print("\n".join(ms) if ms else "(hub boş — node_agent koşuları bekleniyor)")
        return 0

    if args.komut == "check":
        if not args.makine:
            print("kullanım: sync_coordinator.py check <makine>")
            return 1
        st = fetch_status(args.makine)
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0

    # status (varsayılan)
    data = collect()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"═══ EŞİTLİK MATRİSİ — {data['ts'][:19]} ({data['count']} makine) ═══")
        print_table(data["machines"])
        print(f"\nKaynak: {GDRIVE_HUB}/{DEFAULT_USER}/<makine>/status.json")
        print("Not: makine kapalıysa son bilinen durumu gösterilir (status.json kalıcı).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
