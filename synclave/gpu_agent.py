#!/usr/bin/env python3
"""
gpu_agent.py — H2 GPU analiz sunucusu (RTX 5070 Ti) v1.0

H1'den gelen analiz görevlerini H2'deki ekran kartında işler.
Tailscale içi: sadece 100.x.x.x dinler, kimlik imzalı istekleri kabul eder.

KURULUM (H2/Windows):
  pip install fastapi uvicorn requests   # + GPU motoru: ollama / llama.cpp / vLLM
  python gpu_agent.py --port 8644

DESTEKLENEN MOTORLAR (otomatik tespit):
  1. Ollama  (http://127.0.0.1:11434)  — LLM + vision, en kolay
  2. llama.cpp server (http://127.0.0.1:8080) — GGUF modeller
  3. vLLM    (http://127.0.0.1:8000)   — yüksek verim
  Hiçbiri yoksa: 'motor_yok' döner — H1 görevi inbox'a düşürür.

UÇ NOKTALAR:
  GET  /health    → GPU durumu (model/VRAM/motor)
  POST /analyze   → {task: "..."} → {result: "...", motor, model, ms}

H1 KOMUT:
  python3 gpu_task.py status     # /health
  python3 gpu_task.py task "..." # /analyze
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import agent_identity as AI
    IDENTITY_OK = True
except Exception:
    AI = None
    IDENTITY_OK = False


def _detect_motor() -> dict:
    """H2'de hangi GPU inference motoru çalışıyor?"""
    adaylar = [
        ("ollama", "http://127.0.0.1:11434/api/tags"),
        ("llama.cpp", "http://127.0.0.1:8080/health"),
        ("vllm", "http://127.0.0.1:8000/health"),
    ]
    for name, url in adaylar:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return {"motor": name, "url": url}
        except Exception:
            continue
    return {"motor": None, "url": None}


def _ollama_generate(prompt: str, model: str = "") -> str:
    """Ollama üzerinden üretim (varsayılan model otomatik)."""
    tags = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:11434/api/tags", timeout=5).read().decode())
    modeller = [m["name"] for m in tags.get("models", [])]
    sec = model or (modeller[0] if modeller else "")
    if not sec:
        return "Ollama kurulu ama model yok (ollama pull <model>)"
    body = json.dumps({"model": sec, "prompt": prompt,
                       "stream": False, "options": {"num_predict": 2000}}).encode()
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate",
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read().decode())
    return (d.get("response") or "").strip() or "(boş yanıt)"


def _llamacpp_generate(prompt: str) -> str:
    body = json.dumps({"prompt": prompt, "n_predict": 2000}).encode()
    req = urllib.request.Request("http://127.0.0.1:8080/completion",
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read().decode())
    return (d.get("content") or "").strip()


def _vllm_generate(prompt: str) -> str:
    body = json.dumps({"model": "default", "prompt": prompt,
                       "max_tokens": 2000}).encode()
    req = urllib.request.Request("http://127.0.0.1:8000/v1/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read().decode())
    return (d.get("choices") or [{}])[0].get("text", "").strip()


def _gpu_info() -> dict:
    """NVIDIA GPU bilgisi (nvidia-smi varsa)."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
                            "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            ad = r.stdout.strip().split("\n")[0]
            name, total, used = [x.strip() for x in ad.split(",")]
            return {"gpu": name, "vram_total": total, "vram_used": used}
    except Exception:
        pass
    return {"gpu": "nvidia-smi yok"}


def build_app(token: str):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Cumulus H2 GPU Agent")

    def check_auth(request: Request):
        if not token:
            return True
        return request.headers.get("authorization") == f"Bearer {token}"

    @app.get("/health")
    async def health():
        ident = AI.AgentIdentity.load_or_create() if IDENTITY_OK else None
        out = {"status": "ok", "host": platform.node(),
               "gpu": _gpu_info(), "motor": _detect_motor()}
        if ident:
            out["agent_id"] = ident.agent_id
            out["clone_state"] = ident.meta.get("clone_state")
        return out

    @app.post("/analyze")
    async def analyze(request: Request):
        if not check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        gorev = body.get("task", "")
        if not gorev:
            return JSONResponse({"error": "task gerekli"}, status_code=400)
        motor = _detect_motor()
        t0 = time.time()
        try:
            if motor["motor"] == "ollama":
                sonuc = _ollama_generate(gorev)
            elif motor["motor"] == "llama.cpp":
                sonuc = _llamacpp_generate(gorev)
            elif motor["motor"] == "vllm":
                sonuc = _vllm_generate(gorev)
            else:
                return JSONResponse({
                    "error": "motor_yok",
                    "not": "H2'de Ollama/llama.cpp/vLLM kurun: "
                           "https://ollama.com/download (RTX 5070 Ti için)",
                }, status_code=503)
            return {"result": sonuc, "motor": motor["motor"],
                    "ms": round((time.time() - t0) * 1000)}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8644)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--token", default=os.environ.get("A2A_TOKEN", ""))
    args = ap.parse_args()
    import uvicorn
    app = build_app(args.token)
    print(f"H2 GPU Agent: http://{args.host}:{args.port} (token={'var' if args.token else 'YOK'})")
    print(f"  motor: {_detect_motor()}")
    print(f"  GPU  : {_gpu_info()}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
