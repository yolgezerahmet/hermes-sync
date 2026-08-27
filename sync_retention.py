#!/usr/bin/env python3
"""GDrive versiyonlu yedek RETENTION politikası (OceanAPI #5 — 26 Ağu 2026)
Kural: son 7 gün günlük + 8 hafta haftalık + 12 ay aylık tutulur.
Daha eski snapshot'lar silinir (silme öncesi geri yükleme testi manuel).
"""
import subprocess, re, os, sys
from datetime import datetime, timedelta

GDRIVE_ROOT = "gdrive:cumulusos-backups/versiyonlu"
NOW = datetime.now()

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    return r.stdout

def parse_snapshots():
    """rclone lsd ile YYYYMMDD_HHMMSS dizinlerini listele"""
    out = run(f"rclone lsd {GDRIVE_ROOT} --max-depth 1 2>/dev/null")
    snaps = []
    for line in out.splitlines():
        m = re.search(r"(\d{8})_(\d{6})", line)
        if m:
            ts = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            name = line.split()[-1]
            snaps.append((ts, name))
    return sorted(snaps)

def retention_decision(snaps):
    """Hangi snapshot'lar SİLİNİR? (dry-run raporu)"""
    keep = set()
    # Son 7 gün: tümü
    cutoff_daily = NOW - timedelta(days=7)
    for ts, name in snaps:
        if ts >= cutoff_daily:
            keep.add(name)
    # 8 hafta: haftalık (her haftanın son snapshot'ı)
    cutoff_weekly = NOW - timedelta(weeks=8)
    weekly_buckets = {}
    for ts, name in snaps:
        if cutoff_weekly <= ts < cutoff_daily:
            wk = ts.isocalendar()[:2]  # (yıl, hafta)
            if wk not in weekly_buckets or ts > weekly_buckets[wk][0]:
                weekly_buckets[wk] = (ts, name)
    for ts, name in weekly_buckets.values():
        keep.add(name)
    # 12 ay: aylık (her ayın son snapshot'ı)
    cutoff_monthly = NOW - timedelta(days=365)
    monthly_buckets = {}
    for ts, name in snaps:
        if cutoff_monthly <= ts < cutoff_weekly:
            mk = (ts.year, ts.month)
            if mk not in monthly_buckets or ts > monthly_buckets[mk][0]:
                monthly_buckets[mk] = (ts, name)
    for ts, name in monthly_buckets.values():
        keep.add(name)
    return [name for ts, name in snaps if name not in keep], sorted(keep)

def main():
    dry = "--apply" not in sys.argv
    snaps = parse_snapshots()
    if not snaps:
        print("Snapshot bulunamadı:", GDRIVE_ROOT)
        return
    print(f"Toplam snapshot: {len(snaps)} | En eski: {snaps[0][0]} | En yeni: {snaps[-1][0]}")
    to_delete, keep = retention_decision(snaps)
    print(f"KORUNAN: {len(keep)} | SİLİNECEK: {len(to_delete)}")
    for name in to_delete[:20]:
        if dry:
            print(f"  [dry-run] sil: {name}")
        else:
            print(f"  sil: {name}")
            run(f"rclone purge {GDRIVE_ROOT}/{name} 2>/dev/null")
    if to_delete and dry:
        print(f"\nUYGULAMAK İÇİN: {sys.argv[0]} --apply")
    print(f"\nRetention: son 7g günlük + 8h haftalık + 12ay aylık (OceanAPI #5)")

if __name__ == "__main__":
    main()
