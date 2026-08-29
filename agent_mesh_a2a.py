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
import socket
import sys
import time
import uuid
from pathlib import Path

INBOX_DIR = Path(os.environ.get("A2A_INBOX", "~/.hermes/a2a_inbox")).expanduser()
TASK_STORE = Path(os.environ.get("A2A_TASK_STORE", "~/.hermes/a2a_tasks.json")).expanduser()

# ─── Kalıcı görev deposu (asenkron: server restart'ında kaybolmaz) ─────
def _load_tasks() -> dict:
    try:
        if TASK_STORE.exists():
            return json.loads(TASK_STORE.read_text())
    except Exception:
        pass
    return {}

def _save_tasks(tasks: dict):
    try:
        TASK_STORE.parent.mkdir(parents=True, exist_ok=True)
        TASK_STORE.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass

TASKS: dict = _load_tasks()


# ─── Platform yardımcıları (29 Ağu 2026 — H2/Windows portu) ───────────
# Orijinal kod 3 Linux'a özgü çağrı kullanıyordu, Windows'ta ÇÖKÜYORDU:
#   os.uname().nodename      → AttributeError (Windows'ta os.uname YOK)
#                              agent_card() ve status action ikisi de patlıyordu
#   os.stat("/proc/1")       → FileNotFoundError (/proc yok) → status 500
#   shutil.disk_usage("/")   → MSYS/Windows'ta kök disk belirsiz
# Linux/macOS davranışı AYNEN korunur; sadece fallback eklenir.
def _hostname() -> str:
    try:
        return os.uname().nodename          # Linux/macOS
    except AttributeError:
        return os.environ.get("COMPUTERNAME") or socket.gethostname()


def _root_path() -> str:
    if os.name == "nt":
        return os.environ.get("SystemDrive", "C:") + os.sep
    return "/"


def _uptime_s():
    """Açılıştan beri geçen saniye. Windows: GetTickCount64 (bağımlılıksız)."""
    try:
        if os.name == "nt":
            import ctypes
            return round(ctypes.windll.kernel32.GetTickCount64() / 1000.0, 0)
        return round(time.time() - os.stat("/proc/1").st_mtime, 0)
    except Exception:
        return None

# ─── AgentCard (A2A keşif) ────────────────────────────────────────────
def agent_card(host: str, port: int) -> dict:
    return {
        "protocolVersion": "1.0",
        "name": f"cumulus-agent-{_hostname()}",
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
        disk = shutil.disk_usage(_root_path())
        return "completed", {
            "host": _hostname(),
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "disk_gb": round(disk.free / 1e9, 1),
            "uptime_s": _uptime_s(),
        }
    # note: inbox'a yaz (Hermes/otonom cron okur, işler, sonucu task sonucuna ekler)
    text = payload.get("text", json.dumps(payload, ensure_ascii=False))
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    fname = INBOX_DIR / f"{int(time.time())}_{uuid.uuid4().hex[:8]}.json"
    fname.write_text(json.dumps({
        "ts": time.time(), "from": task.get("metadata", {}).get("from", "unknown"),
        "text": text, "status": "new", "result": None,
        "_task_id": task.get("_task_id"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return "completed", {"note": str(fname), "inbox": str(INBOX_DIR)}

# ─── JSON-RPC dispatch (senkron / asenkron / sorgu) ───────────────────
def dispatch(method: str, params: dict) -> dict:
    if method == "task/send":
        task_id = uuid.uuid4().hex[:12]
        mode = params.get("mode", "sync")  # sync: anında sonuç | async: task_id + sonradan task/get
        params["_task_id"] = task_id
        TASKS[task_id] = {"status": "working", "result": None, "created": time.time(),
                          "mode": mode}
        _save_tasks(TASKS)
        if mode == "async":
            # arka planda işle (thread); sonuç store'a yazılır, task/get ile alınır
            import threading
            def _run():
                try:
                    status, result = execute_task(params)
                    TASKS[task_id] = {"status": status, "result": result,
                                      "created": time.time(), "mode": "async"}
                except Exception as e:
                    TASKS[task_id] = {"status": "failed", "result": {"error": str(e)},
                                      "created": time.time(), "mode": "async"}
                _save_tasks(TASKS)
            threading.Thread(target=_run, daemon=True).start()
            return {"id": task_id, "status": "working", "result": None, "mode": "async"}
        try:
            status, result = execute_task(params)
            TASKS[task_id] = {"status": status, "result": result, "created": time.time(),
                              "mode": "sync"}
        except Exception as e:
            TASKS[task_id] = {"status": "failed", "result": {"error": str(e)},
                              "created": time.time(), "mode": "sync"}
        _save_tasks(TASKS)
        return {"id": task_id, "status": TASKS[task_id]["status"], "result": TASKS[task_id]["result"]}
    if method == "task/get":
        tid = params.get("id", "")
        # ÖNCE inbox: worker işlenmişse güncel sonuç oradadır (H1 görev sonucu)
        for f in INBOX_DIR.glob("*.json"):
            try:
                d = json.loads(f.read_text())
                if d.get("_task_id") == tid:
                    return {"id": tid, "status": d.get("status", "completed"),
                            "result": d.get("result") or {"note": str(f)}}
            except Exception:
                pass
        t = TASKS.get(tid)
        if not t:
            raise KeyError(f"task {tid} yok")
        return {"id": tid, "status": t["status"], "result": t["result"], "mode": t.get("mode", "sync")}
    if method == "task/cancel":
        tid = params.get("id", "")
        if tid in TASKS:
            TASKS[tid]["status"] = "canceled"
            _save_tasks(TASKS)
        return {"id": tid, "status": "canceled"}
    if method == "message/send":
        return {"ok": True, "echo": params.get("message", ""), "mode": "sync"}
    if method == "message/sendSubscribe":
        # Canlı mesaj akışı (SSE) — dispatch içinde işlenmez; /stream endpoint'ine yönlendir
        return {"ok": True, "stream": f"/stream?message={params.get('message', '')[:50]}"}
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

    @app.get("/stream")
    async def stream(message: str = "", seconds: int = 10):
        """Canlı (SSE) mesaj akışı — 2 saniyede bir durum/mesaj yayınlar.
        Kullanım: GET /stream?message=selam&seconds=10
        (canlı görüşme kanalı; ajan bu akışı dinleyerek eşzamanlı konuşur)
        """
        from fastapi.responses import StreamingResponse

        async def gen():
            import asyncio as _asyncio
            start = time.time()
            yield "event: open\ndata: {\"status\": \"connected\"}\n\n"
            i = 0
            while time.time() - start < seconds:
                yield (f"event: message\ndata: {json.dumps({'t': i, 'echo': message, 'ts': time.strftime('%H:%M:%S')}, ensure_ascii=False)}\n\n")
                i += 1
                await _asyncio.sleep(2)
            yield "event: done\ndata: {}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

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
