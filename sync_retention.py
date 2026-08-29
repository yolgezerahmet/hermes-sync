#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_retention.py — GDrive versiyonlu yedek RETENTION politikası (v2.1 C modülü)
Kural (node-bazlı öncelik sınıfı — 29 Ağu 2026):
  KRİTİK (kernel, patent, scripts, hermes): 12 ay (aylık) + 8 hafta (haftalık) + 7 gün (günlük)
  ORTA   (research, pcb, sim, math):        8 hafta (haftalık) + 7 gün (günlük)
  BÜYÜK  (hermes-skills, openclaw, plugins): 4 hafta (haftalık) + 7 gün (günlük)
Silme öncesi geri yükleme testi manuel. --apply ile gerçek silme.
"""
import subprocess, re, os, sys
from datetime import datetime, timedelta

GDRIVE_ROOT = "gdrive:cumulusos-backups/versiyonlu"
NOW = datetime.now()

# Öncelik sınıfları → retention pencereleri (gün)
PRIORITY_RETENTION = {
    "kritik": {"weekly_weeks": 8, "monthly_months": 12},
    "orta":   {"weekly_weeks": 8, "monthly_months": 0},
    "buyuk":  {"weekly_weeks": 4, "monthly_months": 0},
}

# Node adı → öncelik sınıfı (config node adlarıyla eşleşir; bilinmeyen → orta)
NODE_PRIORITY = {
    "kernel": "kritik", "patent": "kritik", "scripts": "kritik",
    "hermes": "kritik", "hermes-profile": "kritik", "math": "kritik",
    "research": "orta", "pcb": "orta", "sim": "orta", "openclaw": "orta",
    "hermes-sessions": "orta",
    "hermes-skills": "buyuk", "plugins": "buyuk", "hermes-full": "buyuk",
}


def priority_for(node: str) -> str:
    return NODE_PRIORITY.get(node, "orta")


def retention_limits(node: str) -> dict:
    """Node için retention pencereleri (gün cinsinden)."""
    prio = priority_for(node)
    conf = PRIORITY_RETENTION[prio]
    return {
        "daily_days": 7,
        "weekly_weeks": conf["weekly_weeks"],
        "monthly_months": conf["monthly_months"],
    }


def parse_snapshots(node: str):
    """rclone lsd ile node altındaki YYYYMMDD_HHMMSS dizinlerini listele."""
    out = run(f"rclone lsd {GDRIVE_ROOT}/{node} --max-depth 1 2>/dev/null")
    snaps = []
    for line in out.splitlines():
        m = re.search(r"(\d{8})_(\d{6})", line)
        if m:
            ts = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            name = line.split()[-1]
            snaps.append((ts, name))
    return sorted(snaps)


def retention_decision(snaps, node: str):
    """Hangi snapshot'lar SİLİNİR? (dry-run raporu) — node-bazlı politika."""
    limits = retention_limits(node)
    keep = set()
    # Son N gün: tümü
    cutoff_daily = NOW - timedelta(days=limits["daily_days"])
    for ts, name in snaps:
        if ts >= cutoff_daily:
            keep.add(name)
    # Haftalık: her haftanın son snapshot'ı
    if limits["weekly_weeks"] > 0:
        cutoff_weekly = NOW - timedelta(weeks=limits["weekly_weeks"])
        weekly_buckets = {}
        for ts, name in snaps:
            if cutoff_weekly <= ts < cutoff_daily:
                wk = ts.isocalendar()[:2]
                if wk not in weekly_buckets or ts > weekly_buckets[wk][0]:
                    weekly_buckets[wk] = (ts, name)
        for ts, name in weekly_buckets.values():
            keep.add(name)
    # Aylık: her ayın son snapshot'ı
    if limits["monthly_months"] > 0:
        cutoff_monthly = NOW - timedelta(days=30 * limits["monthly_months"])
        monthly_buckets = {}
        for ts, name in snaps:
            if cutoff_monthly <= ts < (NOW - timedelta(weeks=limits["weekly_weeks"])):
                mk = (ts.year, ts.month)
                if mk not in monthly_buckets or ts > monthly_buckets[mk][0]:
                    monthly_buckets[mk] = (ts, name)
        for ts, name in monthly_buckets.values():
            keep.add(name)
    return [name for ts, name in snaps if name not in keep], sorted(keep)


def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    return r.stdout


def main():
    dry = "--apply" not in sys.argv
    node = None
    if "--node" in sys.argv:
        node = sys.argv[sys.argv.index("--node") + 1]
    nodes = [node] if node else sorted(NODE_PRIORITY.keys())
    total_del = 0
    for n in nodes:
        snaps = parse_snapshots(n)
        if not snaps:
            continue
        limits = retention_limits(n)
        print(f"\n📦 {n} [{priority_for(n).upper()}] — {len(snaps)} snapshot "
              f"(günlük {limits['daily_days']}g, haftalık {limits['weekly_weeks']}h, "
              f"aylık {limits['monthly_months']}ay)")
        print(f"   En eski: {snaps[0][0]} | En yeni: {snaps[-1][0]}")
        to_delete, keep = retention_decision(snaps, n)
        total_del += len(to_delete)
        print(f"   KORUNAN: {len(keep)} | SİLİNECEK: {len(to_delete)}")
        for name in to_delete[:10]:
            if dry:
                print(f"     [dry-run] sil: {name}")
            else:
                print(f"     sil: {name}")
                run(f"rclone purge {GDRIVE_ROOT}/{n}/{name} 2>/dev/null")
        if len(to_delete) > 10:
            print(f"     … +{len(to_delete) - 10} daha")
    print(f"\nToplam silinecek: {total_del} | Retention node-bazlı (KRİTİK 12ay / ORTA 8h / BÜYÜK 4h)")
    if total_del and dry:
        print(f"UYGULAMAK İÇİN: {sys.argv[0]} --apply [--node <ad>]")


if __name__ == "__main__":
    main()
