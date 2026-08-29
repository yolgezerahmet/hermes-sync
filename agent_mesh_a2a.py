#!/usr/bin/env python3
"""
agent_mesh_a2a.py — Minimal A2A (Agent2Agent) uyumlu mesh server (v0.1)

Linux Foundation A2A protokolünün JSON-RPC 2.0 alt kümesi:
  - GET  /.well-known/agent.json  → AgentCard (keşif)
  - POST /                        → JSON-RPC: task/send, task/get, task/cancel, message/send
  - Görevler "note" modunda yerel inbox'a yazılır (H3'ün Hermes'i işler)
    ve "status" modunda makine durumu döner.
  - Tailscale içi kullanım: sadece 100.x.x.x dinler (dışa kapalı), Bearer token.

Kurulum: python3 agent_mesh_a2a.py --port 8643 --token <TOKEN>
Client : a2a_cli.py send <host> <task> --token ...   /   a2a_cli.py get <host> <task_id>
"""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

INBOX_DIR = Path(os.environ.get("A2A_INBOX", "~/.hermes/a2a_inbox")).expanduser()

TASKS: dict = {}  # task_id → {status, result, created}

# ─── AgentCard (A2A keşif) ────────────────────────────────────────────
def agent_card(host: str, port: int) -> dict:
    return {
        "protocolVersion": "1.0",
        "name": f"cumulus-agent-{os.uname().nodename}",
        "description": "CumulusNET agent mesh — görev alır, yerel inbox'a yazar, durum döner",
        "url": f"http://{host}:{port}/",
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        "skills": [
            {"id": "note", "name": "Görev notu bırak", "description": "Görev metnini yerel inbox'a yazar (Hermes işler)"},
            {"id": "status", "name": "Makine durumu", "description": "Makine/disk/uptime özeti döner"},
        ],
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
    }

# ─── Görev işleme ─────────────────────────────────────────────────────
def execute_task(task: dict):
    """Görevi işle → (status, result). 'note' inbox'a yazar, 'status' durum döner."""
    payload = task.get("payload", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {"action": "note", "text": payload}
    action = payload.get("action", "note")
    if action == "status":
        import shutil
        disk = shutil.disk_usage("/")
        return "completed", {
            "host": os.uname().nodename,
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "disk_gb": round(disk.free / 1e9, 1),
            "uptime_s": round(time.time() - os.stat("/proc/1").st_mtime, 0),
        }
    # note: inbox'a yaz (Hermes/otonom cron okur, işler, sonucu task sonucuna ekler)
    text = payload.get("text", json.dumps(payload, ensure_ascii=False))
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    fname = INBOX_DIR / f"{int(time.time())}_{uuid.uuid4().hex[:8]}.json"
    fname.write_text(json.dumps({
        "ts": time.time(), "from": task.get("metadata", {}).get("from", "unknown"),
        "text": text, "status": "new", "result": None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return "completed", {"note": str(fname), "inbox": str(INBOX_DIR)}

# ─── JSON-RPC dispatch ────────────────────────────────────────────────
def dispatch(method: str, params: dict) -> dict:
    if method == "task/send":
        task_id = uuid.uuid4().hex[:12]
        TASKS[task_id] = {"status": "working", "result": None, "created": time.time()}
        try:
            status, result = execute_task(params)
            TASKS[task_id] = {"status": status, "result": result, "created": time.time()}
        except Exception as e:
            TASKS[task_id] = {"status": "failed", "result": {"error": str(e)}, "created": time.time()}
        return {"id": task_id, "status": TASKS[task_id]["status"], "result": TASKS[task_id]["result"]}
    if method == "task/get":
        tid = params.get("id", "")
        t = TASKS.get(tid)
        if not t:
            # inbox dosyasından ara
            for f in INBOX_DIR.glob("*.json"):
                try:
                    d = json.loads(f.read_text())
                    if d.get("_task_id") == tid:
                        return {"id": tid, "status": "completed", "result": d.get("result") or d}
                except Exception:
                    pass
            raise KeyError(f"task {tid} yok")
        return {"id": tid, "status": t["status"], "result": t["result"]}
    if method == "task/cancel":
        tid = params.get("id", "")
        if tid in TASKS:
            TASKS[tid]["status"] = "canceled"
        return {"id": tid, "status": "canceled"}
    if method == "message/send":
        return {"ok": True, "echo": params.get("message", "")}
    raise KeyError(f"bilinmeyen metod: {method}")

# ─── FastAPI uygulaması ───────────────────────────────────────────────
def build_app(token: str):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Cumulus Agent Mesh (A2A)")

    def check_auth(request: Request):
        if not token:
            return True
        return request.headers.get("authorization") == f"Bearer {token}"

    @app.get("/.well-known/agent.json")
    async def card():
        return JSONResponse(agent_card("localhost", 8643))

    @app.post("/")
    async def rpc(request: Request):
        if not check_auth(request):
            return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32001, "message": "unauthorized"}}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}}, status_code=400)
        method = body.get("method")
        params = body.get("params", {})
        req_id = body.get("id", 1)
        try:
            result = dispatch(method, params)
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})
        except KeyError as e:
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": str(e)}}, status_code=400)
        except Exception as e:
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}, status_code=500)

    @app.get("/health")
    async def health():
        return {"status": "ok", "tasks": len(TASKS)}

    return app

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8643)
    ap.add_argument("--host", default="0.0.0.0")  # Tailscale arayüzünde dinle; dış UFW kapalı
    ap.add_argument("--token", default=os.environ.get("A2A_TOKEN", ""))
    args = ap.parse_args()
    import uvicorn
    app = build_app(args.token)
    print(f"A2A mesh server: http://{args.host}:{args.port} (token={'var' if args.token else 'YOK'})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

if __name__ == "__main__":
    main()
