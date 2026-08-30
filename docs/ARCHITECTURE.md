# Mimarî — hermes-sync v2.3

## Genel Bakış

```
                    ┌────────────────────────────────────────────┐
                    │           NODE (Hermes/OpenClaw)          │
                    │  ┌──────────┐   ┌──────────────────────┐  │
                    │  │ sync_motor│   │   agent_mesh_a2a    │  │
                    │  │ (push/pull│   │   (A2A server 8643) │  │
                    │  │  backup)  │   │   + rate limit      │  │
                    │  └────┬─────┘   └──────────┬───────────┘  │
                    │       │                    │              │
                    │  ┌────▼────────────────────▼───────────┐  │
                    │  │        agent_identity (kimlik)      │  │
                    │  │  Ed25519 imza + X25519/AES-GCM şifre│  │
                    │  └────┬────────────────────┬───────────┘  │
                    └───────┼────────────────────┼──────────────┘
                            │                    │
                  ┌─────────▼──────┐   ┌─────────▼──────────┐
                  │  GITHUB       │   │  GDRIVE (restic)   │
                  │  manifest     │   │  versiyonlu yedek  │
                  └───────────────┘   └────────────────────┘
```

## Katmanlar

### 1. Kimlik Katmanı (`agent_identity.py`)
- Her çalışma zamanı: Ed25519 (imza) + X25519 (şifreleme) anahtar çifti
- `agent_id` = `sha256("cumulus-agent-v1|runtime|pubkey")[:15B]` → Crockford B32
- Donanım parmak izi: machine-id, DMI UUID, MAC, arch → klon tespiti (fail-closed)
- Sohbet defteri: `conversations.db` (SQLite/WAL, synchronous=NORMAL)
  - `u.<agent8>.<kanal>.<peer8>.<ulid>` (kullanıcı sohbeti)
  - `a.<agent8>~<peer8>.<kanal>.<ulid>` (ajan-ajan)
  - mesaj: `<conv_id>#<seq>` — içerik SAKLANMAZ (sha256 + boyut)

### 2. İletişim Katmanı (`agent_mesh_a2a.py`, `a2a_cli.py`)
- A2A (Agent2Agent) JSON-RPC 2.0 alt kümesi + AgentCard
- 3 mod: sync (anında), async (task store), stream (SSE)
- Güvenlik zinciri:
  1. Rate limit (IP+agent, 120/60s → 429)
  2. Bearer token (Tailscale içi)
  3. X-Agent-* imza başlıkları (Ed25519, ts+nonce) — şifresiz gövde için
  4. X-Agent-Enc şifreli gövde (X25519 ECDH + AES-GCM, PFS) — varsayılan
  5. TOFU peer defteri (`peers.json`) — anahtar değişimi = taklit RED

### 3. Veri Katmanı (`sync_motor.py`, `conversation_bridge.py`)
- GitHub: manifest merkezi (her zaman açık) + GDrive: versiyonlu snapshot
- Non-destructive: `.conflict.<ts>` korunur
- Sohbet köprüsü: state.db (Hermes) → conversations.db (kimlik defteri)
  watermark + tek geçiş (12.6K session 1.7s) + tek-instance flock

### 4. Hesaplama Katmanı (`gpu_agent.py`, `gpu_task.py`)
- GPU'lu node (örn. Windows + RTX): Ollama/llama.cpp/vLLM otomatik tespit
- `gpu_task.py task "..."` → şifreli A2A → GPU node → sonuç → yayılım

## Ölçeklenebilirlik (3 → 20 node)

| Yön | 3 node | 20 node |
|---|---|---|
| Kimlik | her node kendi anahtarı | aynı — anahtar tabanlı, ortak token değil |
| Rate limit | bellek içi/node | env ile limit ölçeği; Redis opsiyonel |
| Manifest | GitHub (1MB API limiti dikkat) | shard'lanmış manifest önerilir |
| Sohbet defteri | her node kendi DB'si | aynı — merge stratejisi (ID idempotent) |

## Performans Referansı (H1 ölçümü)

- İmza (Ed25519): 0.07 ms
- Şifreleme+çözme (AES-GCM): 0.40 ms
- Sohbet kaydı (SQLite WAL): 0.14 ms
- Sohbet köprüsü: 62K mesaj → 1.7 s (107K msg/s)
- A2A sunucusu ayrı süreç (~56MB RAM) — Hermes gateway'ini etkilemez

## Test

- `tests/test_agent_identity.py` — kimlik, klon, TOFU, replay (33 test)
- `tests/test_encryption.py` — roundtrip, dinleyici, kurcalama, perf (10 test)
- `tests/test_conversation_bridge.py` — köprü, watermark, seq (4 test)
- CI: GitHub Actions `test.yml` — her push'ta pytest
