#!/usr/bin/env python3
"""node_resource_probe.py — AKILLI SYNC Kaynak Probu (hermes-sync v1.5)
=====================================================================
Eşitleme/kurulum öncesi HEDEF node'un kaynaklarını ölçer:
  - CPU: çekirdek sayısı + yük ortalaması
  - GPU: nvidia-smi (model, VRAM, kullanım) — varsa
  - DISK: boş alan
  - RAM: toplam/boş
JSON çıktı → sync_motor akıllı karar verir:
  GPU-öncelikli bir paket (ör. LLM modeli, CUDA aracı) hedef node'da
  GPU yoksa KURULMAZ, ÖNERİ olarak sunulur; onay sonrası kurulur.
"""
import json, os, platform, shutil, subprocess, sys

def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""

def cpu_info():
    try:
        cores = os.cpu_count() or 0
    except Exception:
        cores = 0
    load = ""
    try:
        with open("/proc/loadavg") as f:
            load = f.read().split()[0]
    except Exception:
        pass
    return {"cores": cores, "load1": load}

def gpu_info():
    out = sh(["nvidia-smi", "--query-gpu=name,memory.total,utilization.gpu",
              "--format=csv,noheader"])
    if not out:
        return {"present": False}
    parts = [p.strip() for p in out.split(",")]
    return {"present": True, "name": parts[0] if parts else "?",
            "vram_gb": parts[1] if len(parts) > 1 else "?",
            "util_pct": parts[2] if len(parts) > 2 else "?"}

def disk_info():
    try:
        u = shutil.disk_usage("/")
        return {"free_gb": round(u.free / 1e9, 1), "total_gb": round(u.total / 1e9, 1)}
    except Exception:
        return {"free_gb": "?", "total_gb": "?"}

def mem_info():
    try:
        with open("/proc/meminfo") as f:
            d = dict(l.split(":") for l in f if ":" in l)
        tot = int(d.get("MemTotal", "0").strip().split()[0]) // 1024
        free = int(d.get("MemAvailable", "0").strip().split()[0]) // 1024
        return {"total_gb": tot // 1024, "free_gb": free // 1024}
    except Exception:
        return {"total_gb": "?", "free_gb": "?"}

def main():
    r = {
        "machine": platform.node(),
        "os": platform.system(),
        "cpu": cpu_info(),
        "gpu": gpu_info(),
        "disk": disk_info(),
        "mem": mem_info(),
    }
    print(json.dumps(r, indent=2, ensure_ascii=False))
    # akıllı ipucu
    if r["gpu"]["present"]:
        print(f"GPU ÖNCELİKLİ PAKET KURULABİLİR (GPU: {r['gpu']['name']})")
    else:
        print("GPU YOK — GPU-öncelikli paketler ÖNERİ olarak sunulur, kurulmaz (onay şart)")

if __name__ == "__main__":
    sys.exit(main())
