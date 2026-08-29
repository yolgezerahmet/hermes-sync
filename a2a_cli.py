#!/usr/bin/env python3
"""
a2a_cli.py — A2A mesh client (CumulusNET)

Kullanım:
  a2a_cli.py send <host> "<görev metni>" [--token X]     → task_id + durum
  a2a_cli.py send-status <host> [--token X]              → makine durumu iste
  a2a_cli.py get <host> <task_id> [--token X]            → sonuç
  a2a_cli.py card <host> [--token X]                     → AgentCard
  a2a_cli.py ping <host> [--token X]                     → sağlık

Host örnekleri: 100.103.44.107 (H3), 100.92.2.47 (H1), 100.76.82.46 (H2)
"""
import argparse
import json
import sys
import urllib.request

def rpc(host: str, method: str, params: dict, token: str, port: int = 8643):
    url = f"http://{host}:{port}/"
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("komut", choices=["send", "send-status", "get", "card", "ping"])
    ap.add_argument("host")
    ap.add_argument("gorev", nargs="?", default="")
    ap.add_argument("--task-id", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--port", type=int, default=8643)
    args = ap.parse_args()

    try:
        if args.komut == "send":
            r = rpc(args.host, "task/send", {"payload": {"action": "note", "text": args.gorev}}, args.token, args.port)
            print(json.dumps(r, ensure_ascii=False, indent=2))
        elif args.komut == "send-status":
            r = rpc(args.host, "task/send", {"payload": {"action": "status"}}, args.token, args.port)
            print(json.dumps(r, ensure_ascii=False, indent=2))
        elif args.komut == "get":
            r = rpc(args.host, "task/get", {"id": args.task_id}, args.token, args.port)
            print(json.dumps(r, ensure_ascii=False, indent=2))
        elif args.komut == "card":
            req = urllib.request.Request(f"http://{args.host}:{args.port}/.well-known/agent.json")
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(resp.read().decode())
        elif args.komut == "ping":
            req = urllib.request.Request(f"http://{args.host}:{args.port}/health")
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(resp.read().decode())
    except Exception as e:
        print(f"HATA: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
