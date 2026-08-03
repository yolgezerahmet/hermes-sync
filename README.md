# Hermes Sync Motoru

Hermes Agent'ınızı **Google Drive + GitHub üzerinden** yedekleyen ve
**birden fazla makine arasında** gerçek zamanlı senkronize eden evrensel,
veri kaybına karşı güvenli (non-destructive) motor.

- 🔄 **Çok nokta**: Laptop + Masaüstü + Sunucu + OpenClaw — hepsi eşit
- 🛡️ **Non-destructive**: Asla üzerine yazmaz; çakışmalar `.conflict.TS` ile korunur
- 📦 **Versiyonlu**: Her senkron GDrive'da timestamp'li snapshot
- 🧠 **Sınırsız node**: İstediğiniz dizini node olarak ekleyin
- 👥 **Paylaşım**: Node'ları diğer kullanıcılarla paylaşın
- 🔐 **Güvenli**: `.env`, `*.key`, `id_rsa` ASLA yedeklenmez
- 🤖 **Makine tespiti**: Her makine kendi sürüm geçmişine sahip

## Nasıl Çalışır?

```
┌─────────────────────────────────────────────────────┐
│  GITHUB (manifest merkezi — her zaman açık)         │
│  - sync_manifest.json (SHA256 + ts + makine)        │
└─────────────────────────────────────────────────────┘
        ▲                        ▲
   push │                        │ pull (makine açılınca)
        ▼                        ▼
  ┌──────────┐   Tailscale   ┌──────────┐
  │ Makine 1 │◄── 9090 ────►│ Makine 2 │
  └──────────┘               └──────────┘
        │                          │
        ▼                          ▼
  GDRIVE (versiyonlu yedek)  GDRIVE (pull)
  hermes-sync/<user>/<machine>/versiyonlu/<node>/<ts>/
```

## Kurulum

```bash
git clone https://github.com/yolgezerahmet/hermes-sync.git
cd hermes-sync
cp config.example.json config.json
# config.json'u düzenleyin: user_id, github repo, node dizinleri
```

**Gereksinimler:**
- Python 3.8+
- [GitHub CLI](https://cli.github.com/) — `gh auth login` yapılmış
- [rclone](https://rclone.org/) — Google Drive remote (`gdrive:`)

## Kullanım

```bash
python3 sync_motor.py status          # durum + farkındalık
python3 sync_motor.py both            # push + pull (önerilen)
python3 sync_motor.py push            # yerel → GitHub + GDrive
python3 sync_motor.py pull            # merkezden çek (çakışmasız)
python3 sync_motor.py select          # interaktif node seçimi
python3 sync_motor.py nodes           # node listesi + versiyonlar
python3 sync_motor.py conflicts       # çakışmaları listele

# Sınırsız node ekleme:
python3 sync_motor.py add-node proje-x --path ~/projeler/proje-x \
    --include "*.md,*.py" --max-kb 2048

# Node paylaşma (başka kullanıcıya):
python3 sync_motor.py share kernel --to arkadas
```

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

```bash
# Kullanıcı A: node paylaş
python3 sync_motor.py share kernel --to kullanici-b

# Kullanıcı B: paylaşılan node'u çek
# → gdrive:hermes-sync/kullanici-b/shared/kernel/ altına kopyalanır
```

## Otomatik Çalıştırma

```bash
# Linux/Mac (crontab) — her 3 saatte
0 */3 * * * cd ~/hermes-sync && python3 sync_motor.py both >> ~/hermes-sync.log 2>&1

# Windows (Görev Zamanlayıcı)
# pythonw ile her 3 saatte sync_motor.py both
```

## Sorun Giderme

- **"GitHub manifest erişilemedi"** → `gh auth login`
- **"GDrive snapshot başarısız"** → `rclone config` + `rclone lsd gdrive:`
- **"Karşı taraf OFFLINE"** → `tailscale status` + `tailscale up`
- **Build FAIL** → eşitlenen kod derlenmiyor — log'u incele

## Lisans

MIT — bkz. [LICENSE](LICENSE)

## Katkı

1. Fork edin
2. Feature branch açın
3. Test: `python3 -m unittest discover tests`
4. PR gönderin
