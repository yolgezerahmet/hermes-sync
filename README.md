# Hermes Sync (hermes-sync)

Hermes Agent ağları için **çok nokta yedekleme + senkronizasyon + ajan mesh** motoru.
Non-destructive, versiyonlu, sınırsız node. **MIT** lisansı.

> Özel CumulusNET kopyası: `cumulus-sync-motor` (private). Bu repo (public) evrensel
> Hermes/OpenClaw kullanımı içindir.

## v2.1 — 29 Ağu 2026: Ajan Mesh + Restic

```
┌────────────┐   A2A (JSON-RPC, Tailscale)   ┌────────────┐
│  H1 Hermes │ ◄──────────────────────────► │  H3 Hermes │
│  (VPS)     │                               │  (Proxmox) │
└──┬─────┬───┘                               └──┬─────┬───┘
   │     │ Syncthing (P2P dosya)               │     │
   │     └─────────────────────────────────────┘     │
   │              ┌────────────┐                     │
   └─────────────►│   GDrive   │◄────────────────────┘
                  │  restic    │  (ortak yedek repo)
                  │  state.json│  (ortak durum)
                  └────────────┘
   ┌────────────┐
   │  H2 Hermes │  (A2A + restic canlı; Syncthing/worker talimatlı)
   │  (Windows) │
   └────────────┘
```

### Bileşenler

| Bileşen | Dosya | Açıklama |
|---|---|---|
| Senkron motoru | `sync_motor.py` | push/pull/both/backup/versions/rollback + `mesh` komutu (kanal seçici) |
| Node ajanı | `node_agent.py` | otonom eşitleme + yedek + hub raporu + ortak akıl |
| A2A mesh server | `agent_mesh_a2a.py` | Ajanlar arası konuşma (JSON-RPC, port 8643) |
| A2A client | `a2a_cli.py` | send/get/stream — görev gönder, sonuç al, canlı akış dinle |
| Görev işleyici | `inbox_worker.py` | A2A inbox görevlerini çalıştırır (allowlist) |
| Ortak akıl | `sync_common_knowledge.py` | GDrive hub'da dağıtık ortak durum + görev kuyruğu (HLC) |
| Ortak hafıza | `sync_memory.py` | Memory DIF'leri JSONL + audit hash-chain |
| Retention | `sync_retention.py` | Snapshot yaşam döngüsü |
| Akıllı kurulum | `probe/propose/apply` | Kaynak farkındalıklı kurulum önerisi |

### 3 Katmanlı Akıllı Kanal Mimarisi

```
Görev/cevap  → A2A      (Tailscale HTTP, anlık — saniyeler)
Dosya değişimi → Syncthing (P2P, GDrive'suz — fsWatcher)
Arşiv/yedek  → GDrive  (restic incremental + versiyonlu snapshot)
```

### A2A — 3 İletişim Modu

```bash
# SENKRON: anında sonuç
python3 a2a_cli.py send-status 100.103.44.107 --token <TOKEN>

# ASENKRON: görev gönder → task_id → sonra sonucu al (kalıcı task store)
python3 a2a_cli.py send <host> "uptime" --mode async --token <TOKEN>
python3 a2a_cli.py get <host> --task-id <TASK_ID> --token <TOKEN>

# CANLI: SSE akışı (2s'de bir veri)
python3 a2a_cli.py stream <host> "selam" --seconds 10 --token <TOKEN>
```

### Restic Incremental Yedek

```bash
# rclone serve restic gdrive:restic-backup --addr 127.0.0.1:8443
python3 sync_motor.py backup            # CDC dedup + snapshot + restore
python3 sync_motor.py versions          # snapshot listesi
python3 sync_motor.py rollback <node> --version <snapshot> --dry-run
```

Retention: forget keep-daily 7 / weekly 4 / monthly 6 — prune yalnız birincil makinede (04:00).

### Kurulum (yeni node)

```bash
python3 sync_motor.py init              # config üret (gdrive:hermes-sync/<user>/)
python3 sync_motor.py add-node <ad> --path <dizin> [--include '*.md'] [--max-kb 1024]
python3 sync_motor.py both              # push + pull
python3 sync_motor.py mesh status       # tüm node'ların A2A durumu
```

### Gereksinimler

- Python 3.10+, rclone (GDrive remote), restic 0.19+ (yedek), fastapi+uvicorn (A2A server)
- Tailscale veya doğrudan erişim (A2A 8643, Syncthing 22000/8384)

### Güvenlik

- `.env`, `*.key`, `*.pem`, token içeren dosyalar ASLA kapsama alınmaz (secret filtre)
- A2A: Bearer token + Tailscale-only (dışa kapalı)
- Görev işleyici: allowlist komutlar (status/uptime/test:<modul>/shell:ls)
- Non-destructive: çakışma `.conflict.TS` korunur, üzerine yazma yok

## Geçmiş

- v1.6 (12 Ağu): akıllı kurulum (probe/propose/apply)
- v1.3 (3 Ağu): evrensel — kullanıcı/makine kimliği, sınırsız node, share
- v1.0 (3 Ağu): GitHub manifest + GDrive versiyonlu + OpenClaw skill
