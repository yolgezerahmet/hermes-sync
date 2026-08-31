#!/usr/bin/env python3
"""
gpu_task.py — H2 GPU analiz görevi istemcisi (H1) v1.0

KULLANIM (H1'de, kullanıcının "H2 ekran kartıyla analiz" talebi):
  python3 gpu_task.py "görev metni"                # H2'ye gönder, sonucu bekle
  python3 gpu_task.py --list                       # H1'deki GPU sonuç arşivi
  python3 gpu_task.py --status                     # H2 GPU sunucusu durumu

AKIŞ:
  H1 ──A2A (şifreli)──▶ H2 gpu_agent (port 8644 / inbox) ──▶ GPU (Ollama/vLLM)
  H2 ──sonuç──▶ H1 /root/research/gpu/<ts>.md ──sync──▶ H2 + H3 (3 node kullanır)

Sonuçlar H1'de /root/research/gpu/ altına yazılır; sync_motor research node'u
ile H2/H3'e otomatik yayılır — üç node aynı analizi görebilir.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
RESULT_DIR = Path(os.environ.get("GPU_RESULT_DIR", "~/.hermes/state/gpu_results")).expanduser()
H2_HOST = os.environ.get("GPU_NODE_HOST", "100.76.82.46")
H2_PORT = int(os.environ.get("GPU_NODE_PORT", "8643"))
# H2'de gpu_agent.py çalışıyorsa doğrudan HTTP; yoksa A2A inbox üzerinden
GPU_HTTP_PORT = int(os.environ.get("GPU_HTTP_PORT", "8644"))


def _token() -> str:
    for line in open(os.path.expanduser("~/.hermes/.env")):
        if line.startswith("A2A_TOKEN="):
            return line.strip().split("=", 1)[1]
    return ""


def _run_a2a(args: list[str], timeout: int = 180) -> dict:
    r = subprocess.run([sys.executable, str(HERE / "a2a_cli.py"), *args],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        return {"error": r.stderr.strip() or r.stdout.strip()}
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"raw": r.stdout}


def _http_check() -> dict:
    """H2'de gpu_agent.py (8644) varsa doğrudan durum döner."""
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://{H2_HOST}:{GPU_HTTP_PORT}/health", timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {"reachable": False}


def gpu_status() -> dict:
    http = _http_check()
    if http.get("reachable", True) and http.get("status"):
        return {"kanal": "gpu_agent_http", **http}
    # A2A yol: H2 inbox worker'a "gpu:status" görevi
    r = _run_a2a(["send", H2_HOST, "gpu:status", "--port", str(H2_PORT),
                  "--token", _token()], timeout=60)
    return {"kanal": "a2a_inbox", "gonderildi": True, "yanit": r}


def gpu_task(gorev: str, timeout: int = 600) -> dict:
    """Görevi H2'ye gönder. gpu_agent HTTP'ye ulaşırsa senkron analiz;
    ulaşamazsa A2A inbox'a not düşer (H2 tarafı işler, sonuç ayrıca alınır)."""
    http = _http_check()
    if http.get("status") == "ok":
        import urllib.request
        # H2'de farklı gpu_agent sürümleri olabilir: önce standart body şeması
        # ({"task": ...}), 422 alırsa query şeması (?request=...) dene.
        sonuc = None
        denemeler = [
            ("body", json.dumps({"task": gorev}).encode(),
             {"Content-Type": "application/json"}),
            ("query", b"",
             {"Content-Type": "application/json"}),
        ]
        for etiket, data, hdr in denemeler:
            import urllib.error
            if etiket == "query":
                import urllib.parse
                url = (f"http://{H2_HOST}:{GPU_HTTP_PORT}/analyze?request="
                       + urllib.parse.quote(gorev))
            else:
                url = f"http://{H2_HOST}:{GPU_HTTP_PORT}/analyze"
            req = urllib.request.Request(url, data=data or None,
                                         headers=hdr, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    sonuc = json.loads(r.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code in (422, 400, 404) and etiket == "body":
                    continue  # şema farklı — query'yi dene
                if etiket == "query":
                    return {"error": f"gpu_agent hatası: HTTP {e.code}",
                            "detay": e.read().decode()[:200]}
                continue
            except Exception as e:
                if etiket == "query":
                    return {"error": f"gpu_agent hatası: {e}"}
                continue
        if sonuc is None:
            return {"error": "gpu_agent yanıt vermedi"}
    else:
        # A2A inbox yolu — H2'de worker/Hermes işler
        sonuc = _run_a2a(["send", H2_HOST, f"gpu:analiz {gorev}",
                          "--port", str(H2_PORT), "--token", _token()],
                         timeout=120)
        sonuc["not"] = "H2 gpu_agent kurulana kadar görev inbox'a düşer"

    # Sonucu H1 arşivine yaz (sync research node ile H2/H3'e yayılır)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = RESULT_DIR / f"gpu_{ts}.json"
    fname.write_text(json.dumps({"gorev": gorev, "sonuc": sonuc,
                                 "ts": time.time()}, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    sonuc["_arşiv"] = str(fname)
    return sonuc


def main(argv=None):
    ap = argparse.ArgumentParser(description="H2 GPU analiz istemcisi")
    ap.add_argument("komut", nargs="?", default="status",
                    choices=["status", "task", "list"])
    ap.add_argument("gorev", nargs="?", default="")
    a = ap.parse_args(argv)

    if a.komut == "status":
        print(json.dumps(gpu_status(), ensure_ascii=False, indent=2))
    elif a.komut == "task":
        if not a.gorev:
            print("Kullanım: gpu_task.py task \"<analiz görevi>\"")
            return 1
        print(json.dumps(gpu_task(a.gorev), ensure_ascii=False, indent=2))
    elif a.komut == "list":
        for f in sorted(RESULT_DIR.glob("gpu_*.json"))[-10:]:
            d = json.loads(f.read_text())
            print(f"{f.name}  {d.get('gorev','')[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
