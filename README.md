# Cumulus Sync Motoru

GitHub + Google Drive + Tailscale üzerinden **iki yönlü, veri kaybına karşı
güvenli (non-destructive)** dosya senkronizasyon motoru.

H1 (7/24 VPS) ve H2 (aralıklı açılan Desktop) arasında **versiyon sunucusu**
mimarisiyle çalışır: GitHub her zaman açık merkezdir, GDrive büyük dosyalar
için versiyonlu depodur, Tailscale anlık farkındalık sağlar.

## Özellikler

| Özellik | Açıklama |
|---------|----------|
| 🔄 İki yönlü | `push` + `pull` — H1 ↔ H2 |
| 🛡️ Non-destructive | Asla üzerine yazmaz; çakışmalar `.conflict.TS` ile korunur |
| 📦 Versiyonlu | Her senkron GDrive'da timestamp'li snapshot oluşturur |
| 🧠 Akıllı filtre | Küçük/değerli dosyalar GitHub manifest'ine; büyükler GDrive'a |
| 👁️ Farkındalık | Her iki taraf diğerinin değişikliklerini görür |
| 🤖 Makine tespiti | H1/H2 hostname + OS ile otomatik algılanır |
| 📝 Loglama | Seviyeli log + dosya kaydı + opsiyonel renkli çıktı |
| ✅ Test | Birim testler (`tests/test_sync_motor.py`) |

## Gereksinimler

- Python 3.8+
- [GitHub CLI](https://cli.github.com/) (`gh`) — kimlik doğrulama yapılmış
- [rclone](https://rclone.org/) — Google Drive remote (`gdrive:`)

## Kurulum

```bash
git clone https://github.com/yolgezerahmet/cumulus-sync-motor.git
cd cumulus-sync-motor
cp config.example.json config.json
# config.json'u kendi makinenize göre düzenleyin
```

## Kullanım

```bash
python3 sync_motor.py status       # durum + farkındalık
python3 sync_motor.py push         # yerel → merkez (GitHub + GDrive)
python3 sync_motor.py pull         # merkez → yerel (çakışmasız)
python3 sync_motor.py both         # push + pull (önerilen)
python3 sync_motor.py conflicts    # çakışma dosyalarını listele
python3 sync_motor.py init         # ilk kurulum
python3 sync_motor.py -v status    # debug log
```

## Mimari

```
┌─────────────────────────────────────────────────────┐
│  GITHUB (cumulus-sync) = HER ZAMAN AÇIK MERKEZ     │
│  - sync_manifest.json (SHA256 + ts + makine)       │
│  - küçük dosyalar manifest'e yazılır               │
└─────────────────────────────────────────────────────┘
        ▲                        ▲
   push │                        │ pull (H2 açılınca)
        ▼                        ▼
  ┌──────────┐   Tailscale   ┌──────────┐
  │  H1 VPS  │◄── 9090 ────►│  H2 Win  │
  │  (7/24)  │               │ (aralıklı)│
  └──────────┘               └──────────┘
        │                          │
        ▼                          ▼
  GDRIVE (büyük dosyalar)    GDRIVE (pull)
  versiyonlu/snapshot.TS/
```

## Güvenlik İlkeleri

1. **Asla mevcut dosyanın üzerine yazma** — çakışma durumunda yerel dosya
   `.conflict.<timestamp>` olarak saklanır.
2. **Her değişiklik manifest'e yazılır** — SHA256 + timestamp + kaynak makine.
3. **Silme işareti** — karşı tarafta `.deleted` işareti bırakır, geri alınabilir.
4. **GDrive versiyonlu** — her senkron timestamp'li snapshot; eski sürümler
   asla silinmez.

## Yapılandırma

`config.json` (bkz. `config.example.json`):

```json
{
  "github": {
    "repo": "kullanici/cumulus-sync",
    "manifest_file": "sync_manifest.json"
  },
  "gdrive": {
    "versioned_dir": "gdrive:cumulusos-backups/versiyonlu"
  },
  "dirs": {
    "kernel": {
      "path": "/yol/kernel",
      "include": ["*.c", "*.h", "*.md"],
      "exclude_dirs": [".git", "build"],
      "max_size_kb": 512
    }
  }
}
```

Her dizin için:
- `path` — taranacak dizin
- `include` — glob desenleri (dahil edilecek dosya türleri)
- `exclude_dirs` — atlanacak alt dizinler
- `max_size_kb` — manifest'e girecek maksimum dosya boyutu (büyükler GDrive'a)

## Lisans

MIT — bkz. [LICENSE](LICENSE)

## Katkı

1. Fork edin
2. Feature branch açın
3. Testleri çalıştırın: `python3 -m unittest discover tests`
4. PR gönderin
