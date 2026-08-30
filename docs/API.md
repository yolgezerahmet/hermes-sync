# API — hermes-sync v2.3

A2A mesh (port 8643) — OpenAPI 3.1 şartnamesi otomatik: `http://<host>:8643/docs`

## Kimlik Doğrulama

| Yöntem | Header | Açıklama |
|---|---|---|
| Bearer | `Authorization: Bearer <token>` | Tailscale içi ortak sır (eski uyum) |
| İmza | `X-Agent-Id/Ts/Nonce/Sig/Key` | Ed25519 — bütünlük + kimlik (ts±120s) |
| Şifreli gövde | `X-Agent-Enc: v1` | X25519 ECDH + AES-GCM (PFS) — varsayılan |

## Uç Noktalar

### `GET /.well-known/agent.json` — AgentCard (A2A keşif)
```json
{"protocolVersion": "1.0", "name": "cumulus-hermes-<kısa>",
 "capabilities": {"signedRequests": true, "encryptedRequests": true,
                  "requireSignature": false},
 "identity": {"agent_id": "hx-...", "public_key": "...", "x25519_public": "...",
              "clone_state": "clean"}}
```

### `POST /` — JSON-RPC 2.0

**task/send** (senkron veya asenkron)
```json
{"jsonrpc": "2.0", "id": 1, "method": "task/send",
 "params": {"payload": {"action": "note", "text": "görev"},
            "mode": "sync|async"}}
```
Yanıt (sync): `{"id": "...", "status": "completed",
 "result": {"note": "...", "conversation_id": "a.xxx~yyy.a2a.01M..."}}`

**task/get**
```json
{"jsonrpc": "2.0", "id": 1, "method": "task/get",
 "params": {"id": "<task_id>"}}
```

**task/cancel, message/send** — JSON-RPC standart iskeleti.

### `GET /health`
```json
{"status": "ok", "tasks": 12, "host": "...",
 "agent_id": "hx-...", "clone_state": "clean",
 "require_signature": false}
```

### `GET /identity`
Açık kimlik + peer sayacı + sohbet özeti (açık anahtarlar SIZMAZ).

### `GET /stream?message=...&seconds=10`
SSE canlı akış (event: open/message/done).

## Hata Kodları (JSON-RPC)

| Kod | Anlam | HTTP |
|---|---|---|
| -32700 | parse error | 400 |
| -32001 | unauthorized (Bearer) | 401 |
| -32002 | identity_rejected:<neden> | 403 |
| -32003 | local_identity_clone_suspected | 403 |
| -32005 | rate_limited | 429 |
| -32601 | bilinmeyen metod | 400 |

## CLI

```bash
# H1 → H3 şifreli görev (otomatik X-Agent-Enc)
python3 a2a_cli.py send 100.103.44.107 "görev" --token <A2A_TOKEN>
python3 a2a_cli.py send-status <host> --token <A2A_TOKEN>
python3 a2a_cli.py get <host> --task-id <ID> --token <A2A_TOKEN>
python3 a2a_cli.py stream <host> "selam" --seconds 10 --token <A2A_TOKEN>
python3 a2a_cli.py card <host>            # AgentCard
```

## GPU Agent (port 8644, gpu_agent.py)

- `GET /health` → GPU adı, VRAM, motor (ollama/llama.cpp/vLLM)
- `POST /analyze` `{"task": "..."}` → `{"result": "...", "motor": "...", "ms": N}`
- H1 tarafı: `python3 gpu_task.py status | task "..." | list`

## Sohbet Defteri (conversation_bridge.py)

- `python3 conversation_bridge.py --full` — tüm geçmişi işle
- `python3 conversation_bridge.py` — watermark'tan itibaren artımlı
- Defter: `~/.hermes/identity/conversations.db`
  - `conversations(conv_id, kind, local_agent, peer_id, channel, ...)`
  - `messages(msg_id, conv_id, seq, direction, ts, peer_id, sha256, bytes)`
