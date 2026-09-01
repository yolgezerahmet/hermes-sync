# Synclave — Encrypted Multi-Node Agent Mesh

Hermes/OpenClaw ağları için **şifreli çok nokta yedekleme + senkronizasyon + ajan mesh** motoru.
Non-destructive, versiyonlu, sınırsız node. **MIT** lisansı.

> Eski ad: `hermes-sync` (v2.3.1) → rebrand: **Synclave** (v1.0.0).
> Özel CumulusNET kopyası: `cumulus-sync-motor` (private). Bu repo (public) evrensel
> Hermes/OpenClaw kullanımı içindir.

## v2.3 — 30 Ağu 2026: Kriptografik Kimlik + Şifreli Mesh + Sohbet Köprüsü

**Yeni yetenekler (bu sürümde):**
- **Kopyalanamaz-kanıtlı ajan kimliği** (`agent_identity.py`): her çalışma
  zamanı (Hermes/OpenClaw) kendi Ed25519 kimliğine sahiptir; agent_id = açık
  anahtar özeti (`hx-` / `oc-`), donanım parmak izine bağlıdır, klon şüphesinde
  mesh 403 ile reddeder (fail-closed). Meşru taşıma için `rekey --confirm`.
- **Uçtan uca şifreli A2A**: X25519 ECDH + AES-GCM (her mesajda ephemeral →
  Perfect Forward Secrecy) + Ed25519 imza + ts/nonce replay koruması.
  Aradaki dinleyici içeriği çözemez; kurcalama/replay reddedilir.
- **Sohbet köprüsü** (`conversation_bridge.py`): Hermes state.db'deki tüm
  kullanıcı sohbetleri (telegram/cli/whatsapp) kalıcı sohbet defterine akar;
  içerik saklanmaz (sadece sha256). Sohbet ID: `u.<agent>.<kanal>.<peer>.<ulid>`
  (kullanıcı) / `a.<agent>~<peer>.<kanal>.<ulid>` (ajan-ajan).
- **GPU analiz kanalı** (`gpu_agent.py` + `gpu_task.py`): GPU'lu node (örn.
  Windows + RTX) analiz görevlerini yerel kartta işler; sonuçlar mesh ile
  yayılır.
- **Rate limiting**: 429 Too Many Requests (IP+agent, 120 req/60s, env ile
  ölçeklenir) — brute-force koruması.
- **Ölçek**: her node kendi anahtarına sahip → 3/20 node aynı model
  (mac/windows/linux); ortak token tek başına yetmez, kimlik anahtar tabanlı.

```bash
# kimlik + şifreli sohbet
python3 agent_identity.py show                 # kimlik göster/üret
python3 agent_identity.py verify-self          # imza + ID doğrula
python3 a2a_cli.py send <host> "görev" --token <A2A_TOKEN>   # otomatik şifreli

# sohbet köprüsü (her 15 dk / cron)
python3 conversation_bridge.py --full          # ilk kurulum (tüm geçmiş)
python3 conversation_bridge.py                 # artımlı (watermark)

# GPU analiz (H2 RTX örnek)
python3 gpu_task.py status                     # H2 GPU durumu
python3 gpu_task.py task "PCB BGA fanout analizi"   # GPU'da işle
```

### Güvenlik özeti (v2.3)
- Kimlik: agent_id = pubkey özeti; donanım bağı + klon fail-closed
- Bütünlük: Ed25519 imza (gövde + ts + nonce)
- Gizlilik: X25519 ECDH + AES-GCM (PFS)
- Replay: ts (±120s) + nonce tekrarı reddi
- Brute-force: rate limit (429)
- Eski sunucularla geriye uyum: imzalı ama düz gövde (otomatik seçim)

<<<<<<< HEAD
### Windows Kurulum (H2 + Windows 10/11)

```powershell
# 1) Python 3.10+ (python.org — PATH'e ekle) + git
python --version

# 2) Repo + bağımlılıklar
git clone https://github.com/yolgezerahmet/synclave.git
cd synclave
cp config.example.json config.json
# config.json'u düzenleyin: user_id, github repo, node dizinleri
pip install rclone                # veya winget install Rclone.Rclone
pip install restic                # veya restic.net binary → PATH'e ekle
pip install uvicorn fastapi       # A2A server için (opsiyonel)

# 3) rclone — GDrive remote (tek seferlik OAuth)
rclone config
#    remote adı: gdrive
#    (client_id paylaşılmışsa "shared client_id" uyarısı — kendi client_id'niz
#     Google Cloud OAuth'da daha hızlı ve 2026 sonrası zorunlu)

# 4) restic — GDrive object store'u mount et (arka plan servisi)
rclone serve restic gdrive:restic-backup --addr 127.0.0.1:8443
#    Windows: `schtasks /create` veya NSSM ile oturum açılışında başlat

# 5) Syncthing — P2P dosya kanalı (opsiyonel ama önerilir)
winget install syncthing.syncthing
#    GUI 127.0.0.1:8384 → H1/H3 cihazları eşleştir (device ID'ler)

# 6) A2A token — H1/H3 ile aynı ortak token'ı ortam değişkenine yaz
setx A2A_TOKEN "test-a2a-mesh-2026"     # kendi ortak değerinizle değiştirin

# 7) İlk senkron
python sync_motor.py init    # config üret
python sync_motor.py both    # push + pull
python sync_motor.py mesh status
```

Windows notları:
- Kilit dosyası `%TEMP%\cumulus_sync.lock` kullanılır (`/tmp` yok) — msvcrt.locking.
- `sync_motor.py` / `sync_common_knowledge.py` path'leri `os.path.join` ile kurar;
  sabit `/` ayracı yoktur.
- A2A istemcisi (`a2a_cli.py`) yalnızca `urllib` kullanır — ek bağımlılık gerekmez.
- A2A server `uvicorn` bulunamazsa net hata mesajı basar ve çıkar (traceback değil).
- Uzaktan kurulum için hazır betikler: `remote_hermes_setup.ps1` (SSH/Tailscale).
- Otomatik çalıştırma: `schtasks /create` ile `pythonw sync_motor.py both` (aşağıda).

## Kullanım

```bash
python3 sync_motor.py status          # durum + farkındalık
python3 sync_motor.py both            # push + pull (önerilen)
python3 sync_motor.py push            # yerel → GitHub + GDrive
python3 sync_motor.py pull            # merkezden çek (çakışmasız)
python3 sync_motor.py select          # interaktif node seçimi
python3 sync_motor.py nodes           # node listesi + versiyonlar
python3 sync_motor.py conflicts       # çakışmaları listele
python3 sync_motor.py doctor          # ortam sağlığı (bağımlılık + bağlantı) — v1.4
python3 sync_motor.py version         # sürüm (1.6.1)
=======
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
| Ajan kimliği | `agent_identity.py` | Ed25519 + X25519 kimlik, klon tespiti, sohbet defteri |
| Şifreli mesh | `agent_mesh_a2a.py` | A2A + X-Agent-Enc şifreli gövde + rate limit |
| Sohbet köprüsü | `conversation_bridge.py` | state.db → sohbet defteri (watermark) |
| GPU analiz | `gpu_agent.py` / `gpu_task.py` | GPU'lu node'da analiz görevi |

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
>>>>>>> public/main

# ASENKRON: görev gönder → task_id → sonra sonucu al (kalıcı task store)
python3 a2a_cli.py send <host> "uptime" --mode async --token <TOKEN>
python3 a2a_cli.py get <host> --task-id <TASK_ID> --token <TOKEN>

<<<<<<< HEAD
# Sınırsız node ekleme:
python3 sync_motor.py add-node proje-x --path ~/projeler/proje-x \
    --include "*.md,*.py" --max-kb 2048

# Node paylaşma (başka kullanıcıya):
python3 sync_motor.py share kernel --to arkadas

# === AKILLI KURULUM — Kaynak Farkındalıklı Öneri (v1.6) ===
# Felsefe: eşitleme SIRASINDA hiçbir kurulum otomatik yapılmaz.
# CPU/GPU/RAM/disk kontrolünden geçen ÖNERİ sunulur, onay sonrası kurulur.

python3 sync_motor.py probe                # yerel kaynaklar + kurulu araçlar
                                           # (manifest'e yazar, push ile gider)
python3 sync_motor.py push                 # kaynak + araç durumunu otomatik taşır
python3 sync_motor.py propose              # karşı node'un kurulu araçları → öneri
                                           # (GPU öncelikli; engel nedeniyle ayrım)
python3 sync_motor.py apply --tool ollama  # interaktif onay ile kur
python3 sync_motor.py apply --tool vllm --yes   # onaysız kur (yine de RED:
                                           # zaten kuruluysa / kaynak yetmezse)
```

## Akıllı Kurulum (v1.6)

Eşitleme sırasında karşı node'da kurulu olan GPU/CPU yoğun araçları
**otomatik kurmaz** — kaynak kontrolünden geçirilmiş **öneri** olarak sunar:

1. `probe` → yerel CPU/RAM/disk/GPU ölçülür, kurulu araçlar katalogdan
   taranır, manifest'e yazılır (push ile karşı node'a gider)
2. `propose` → karşı node'da kurulu, sizde olmayan araçlar değerlendirilir:
   - ✅ **KURULABİLİR** — kaynaklar yeterli (GPU araçlar öncelikli listelenir)
   - ⛔ **KAYNAK ENGELLİ** — nedenle birlikte: `GPU yok` (NVIDIA/CUDA
     gerekliyse), `disk yetmez`, `RAM yetmez`, `CPU yetmez`
3. `apply --tool <ad>` → kurulum komutu gösterilir, **interaktif onay**
   alınır (veya `--yes`); onay yoksa HİÇBİR ŞEY çalışmaz

**Non-destructive garantileri:** zaten kuruluysa RED; kaynak yetersizse RED;
kurulum asla mevcut dosyanın üzerine yazmaz. Araç kataloğu `config.json`
içindeki `tools` bölümünden gelir — her araç için `check` (varlık komutu),
`gpu` (NVIDIA/CUDA zorunlu mu), `min_ram_gb`/`min_disk_gb`/`min_cpus`
(eşikler) ve `install` (onay sonrası çalışacak komut) tanımlanır.

## Node Yapılandırması

`config.json` içinde her node:

```json
{
  "identity": {
    "user_id": "kullanici-adi",      // GDrive alanınız
    "machine_id": "laptop"           // boş = otomatik (hostname)
  },
  "dirs": {
    "hermes": {
      "path": "~/.hermes",           // Hermes agent yapılandırması
      "include": ["*.yaml", "*.md", "*.json"],
      "exclude_dirs": ["cache", "logs", "models", "venv"],
      "max_size_kb": 1024,           // büyükler GDrive'a
      "gdrive": true                 // versiyonlu GDrive yedeği
    },
    "projem": {
      "path": "~/projeler/projem",
      "include": ["*.c", "*.h", "*.md"],
      "exclude_dirs": [".git", "build"],
      "max_size_kb": 512,
      "gdrive": true
    }
  }
}
```

## Güvenlik İlkeleri

1. **Asla mevcut dosyanın üzerine yazma** — çakışma → `.conflict.<timestamp>`
2. **Secret'lar manifest'e GİRMEZ**: `.env`, `*.key`, `*.pem`, `id_rsa`,
   `service-account`, `credentials` otomatik atlanır
3. **Versiyonlu GDrive**: `versiyonlu/<node>/<timestamp>/` — eski sürümler
   asla silinmez, geri dönüş her zaman mümkün
4. **SHA256 manifest**: GitHub'da tüm dosyaların durumu — her makine
   diğerinin değişikliklerini görür

## Paylaşım (kullanıcılar arası)
=======
# CANLI: SSE akışı (2s'de bir veri)
python3 a2a_cli.py stream <host> "selam" --seconds 10 --token <TOKEN>
```

### Restic Incremental Yedek
>>>>>>> public/main

```bash
# rclone serve restic gdrive:restic-backup --addr 127.0.0.1:8443
python3 sync_motor.py backup            # CDC dedup + snapshot + restore
python3 sync_motor.py versions          # snapshot listesi
python3 sync_motor.py rollback <node> --version <snapshot> --dry-run
```

Retention: forget keep-daily 7 / weekly 4 / monthly 6 — prune yalnız birincil makinede (04:00).

### Kurulum (yeni node)

```bash
python3 sync_motor.py init              # config üret (gdrive:synclave/<user>/)
python3 sync_motor.py add-node <ad> --path <dizin> [--include '*.md'] [--max-kb 1024]
python3 sync_motor.py both              # push + pull
python3 sync_motor.py mesh status       # tüm node'ların A2A durumu
```

### Gereksinimler

- Python 3.10+, rclone (GDrive remote), restic 0.19+ (yedek), fastapi+uvicorn (A2A server)
- Tailscale veya doğrudan erişim (A2A 8643, Syncthing 22000/8384)

### Windows Kurulum (H2 + Windows 10/11)

```powershell
# 1) Python 3.10+ (python.org — PATH'e ekle) + git
python --version

# 2) Paket + CLI kur
pip install synclave
pip install rclone                # veya winget install Rclone.Rclone
pip install restic                # veya restic.net binary → PATH'e ekle
pip install uvicorn fastapi       # A2A server için (opsiyonel)

<<<<<<< HEAD
1. Fork edin
2. Feature branch açın
3. Test: `python3 -m unittest discover tests`
4. PR gönderin

## Akıllı Aktarım (v1.6.1)
`python3 smart_sync.py both --hub gdrive:cumulusos-backups/smart --machine <h1|h2>`

## Ajan Kimliği + Sohbet Etiketleme (v2.2 — 30 Ağu 2026)

Mesh'e bağlı her çalışma zamanı (Hermes, OpenClaw) kendi kriptografik kimliğine
sahiptir: `agent_identity.py` (Ed25519 + donanım parmak izi bağı + klon tespiti).

```bash
python3 agent_identity.py show                 # kimlik göster/üret
python3 agent_identity.py verify-self          # imza + ID-anahtar doğrulaması
python3 agent_identity.py fingerprint          # donanım parmak izi kaynakları
python3 sync_motor.py identity show            # sync entegre kimlik

# Sohbet etiketleme (kullanıcı ve ajanlar arası AYRI, karışmaz):
python3 agent_identity.py conv-open --kind user  --peer ahmet --channel telegram
python3 agent_identity.py conv-open --kind agent --peer hx-...  --channel a2a
python3 agent_identity.py conv-list
```

### Kimlik formatları
- `agent_id` = açık anahtar özeti: `hx-...` (Hermes) / `oc-...` (OpenClaw)
- Sohbet: `u.<agent8>.<kanal>.<peer8>.<ulid>` (kullanıcı) |
  `a.<agent8>~<peer8>.<kanal>.<ulid>` (ajanlar arası)
- Mesaj: `<conv_id>#<seq>`; içerik saklanmaz (sadece sha256)

### Güvenlik
- Anahtar başka donanıma kopyalanırsa `clone_state=suspected` → mesh 403
- Meşru taşıma için `rekey --confirm` (eski kimlik arşivlenir)
- A2A istekleri Ed25519 imzalı (replay koruması: ts+nonce, ±120s)
- Peer defteri TOFU: anahtar değişirse taklit RED
- `--require-signature` (tüm node'lar güncellenince) imzasız istekleri REDDEDİR
GDrive hub üzerinden KARŞILIKLI aktif iş/veri transferi (non-destructive .conflict merge). Detay: smart_sync.py docstring.
=======
# 3) rclone — GDrive remote (tek seferlik OAuth)
rclone config
#    remote adı: gdrive
#    (client_id paylaşılmışsa "shared client_id" uyarısı — kendi client_id'niz
#     Google Cloud OAuth'da daha hızlı ve 2026 sonrası zorunlu)

# 4) restic — GDrive object store'u mount et (arka plan servisi)
rclone serve restic gdrive:restic-backup --addr 127.0.0.1:8443
#    Windows: `schtasks /create` veya NSSM ile oturum açılışında başlat

# 5) Syncthing — P2P dosya kanalı (opsiyonel ama önerilir)
winget install syncthing.syncthing
#    GUI 127.0.0.1:8384 → H1/H3 cihazları eşleştir (device ID'ler)

# 6) A2A token — H1/H3 ile aynı ortak token'ı .env/ortam değişkenine yaz
setx A2A_TOKEN "test-a2a-mesh-2026"     # kendi ortak değerinizle değiştirin

# 7) İlk senkron
python -m synclave.sync_motor init    # config üret
python -m synclave.sync_motor both    # push + pull
python -m synclave.sync_motor mesh status
```

Windows notları:
- Kilit dosyası `%TEMP%\cumulus_sync.lock` kullanılır (`/tmp` yok) — msvcrt.locking.
- `sync_motor.py` / `sync_common_knowledge.py` path'leri `os.path.join` ile kurar;
  sabit `/` ayracı yoktur.
- A2A istemcisi (`a2a_cli.py`) yalnızca `urllib` kullanır — ek bağımlılık gerekmez.
- A2A server `uvicorn` bulunamazsa net hata mesajı basar ve çıkar (traceback değil).
- Uzaktan kurulum için hazır betikler: `remote_hermes_setup.ps1` (SSH/Tailscale).

### Güvenlik

- `.env`, `*.key`, `*.pem`, token içeren dosyalar ASLA kapsama alınmaz (secret filtre)
- A2A: Bearer token + Tailscale-only (dışa kapalı)
- Görev işleyici: allowlist komutlar (status/uptime/test:<modul>/shell:ls)
- Non-destructive: çakışma `.conflict.TS` korunur, üzerine yazma yok

## Geçmiş

- v1.6 (12 Ağu): akıllı kurulum (probe/propose/apply)
- v1.3 (3 Ağu): evrensel — kullanıcı/makine kimliği, sınırsız node, share
- v1.0 (3 Ağu): GitHub manifest + GDrive versiyonlu + OpenClaw skill
>>>>>>> public/main
