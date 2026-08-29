# CHANGELOG — Cumulus Sync Motoru / Hermes Sync

## [2.1.0] — 2026-08-29

### Eklenen — ÖNCELİK SINIFLI YEDEK + DOĞRULAMA (C modülü, v2.1)
- sync_retention.py node-bazlı politika: KRİTİK (kernel/patent/scripts/
  hermes/math) 12 ay + 8 hafta; ORTA (research/pcb/sim/openclaw) 8 hafta;
  BÜYÜK (hermes-skills/plugins/hermes-full) 4 hafta. --node filtresi eklendi
- cmd_backup upload sonrası SHA doğrulama: rclone lsjson --hash → GDrive
  hash'i yerel sha256 ile karşılaştırılır (eşleşmezse ⚠ rapor)
- test_retention_cmd.py: 9 test (öncelik eşleme, limitler, karar, SHA verify)

### Eklenen — ORTAK AKIL (E modülü, v2.1)
- sync_common_knowledge.py: GDrive hub üzerinde dağıtık ortak durum +
  görev kuyruğu (GPT-5.6 tasarımı). HLC mantıksal saat, fail-closed.
  - state.json: gdrive:hermes-sync/<user>/shared/state.json — her makine
    kendi bloğunu HLC saatli yazar, tüm makineler okur (read→merge→write)
  - tasks/<task_id>.json: pending→running (claim, tek sahip)→done (yalnız
    sahibi); aynı id RED, başkası sahiplenemez/done yapamaz
  - CLI: state, tasks, task-add, task-claim, task-done
- sync_coordinator.py: tasks + state komutları (list/add/claim/done + json)
- node_agent.py once: run_state adımı (her koşuda state.json HLC bloğu)
- test_common_knowledge.py: 10 test (state merge, create RED, claim tek
  sahip, done sahibi, fail-closed) — rclone mock'lu

### Eklenen — VERSİYON ETİKETLEME (A modülü)
- `versions <node> --tag <etiket>`: en son versiyonu etiketler
  (tags/<tag>.txt: tam dosya adı + SHA256 + ts; rclone lsjson --hash).
  Aynı tag → RED (üzerine yazmaz); geçersiz etiket (^[a-z0-9][a-z0-9._-]{0,63}$) → RED
- `versions <node> --diff v1.tar.gz,v2.tar.gz`: iki versiyon tar üye listesini
  karşılaştırır (rclone cat | tar tzf stream — içerik indirmez); eklenen/silinen
- `rollback --dry-run`: ön-inceleme — değişecek dosya + çakışma sayısı,
  HİÇBİR ŞEY yazmaz (force modunu da hesaba katar)
- test_versions_cmd.py: 8 test (tag yazma/aynı-tag RED/geçersiz-tag RED,
  diff iki tar, rollback dry-run non-destructive, rollback force)

### Eklenen — ORTAK HAFIZA (D modülü, v2.1)
- `memory` komutu: sync_memory.py v0.1 → v1.0 AKTİF bağlandı.
  Akış: export (memory DIF → JSONL delta, secret allowlist RED) →
  push (rclone copy → gdrive:hermes-sync/<user>/shared/memory/) →
  pull/import (uzak deltaları çek, conflict_policy='preserve' ile uygula;
  tombstone kaldırma, eşit revision+farklı hlc → .conflict korunur) →
  fact_store (memory_store.db facts tablosuna INSERT OR IGNORE, dedup)
- `--memory-dir` parametresi (varsayılan ~/.hermes/memory)
- `--dry-run` desteği (hiçbir şey yazmaz)
- node_agent.py `once` döngüsüne `memory` adımı + `--no-memory` flag'i
  (motor v2.1+ gerektirir; eski sürüm no-op)
- test_memory_cmd.py: 14 test (export/secret RED, push mock, pull/import
  conflict, fact_store dedup, dry-run) — gerçek GDrive'a dokunmaz

### Düzeltilen
- sync_memory import'u sys.path'e _HERE eklenerek cwd'den bağımsız yapıldı
- fact_store dry-run mesajı yanıltıcıydı ("+N kayıt" → "[DRY] N aday")
- cmd_versions döngü sonrası return 0 eksikti (dispatch rc=None)

## [1.6.0] — 2026-08-13

### Eklenen — AKILLI KURULUM (Kaynak Farkındalıklı Öneri)
- `probe` komutu: yerel CPU/RAM/disk/GPU kaynaklarını ölçer (nvidia-smi →
  lspci → vulkaninfo), tools kataloğunu tarar, manifest'e `resources` +
  `tools_state` yazar → push ile karşı node'a gider
- `propose` komutu: karşı node'da kurulu araçları KAYNAK KONTROLLÜ öneri
  listesine çevirir. GPU öncelikli sıralama; NVIDIA GPU'suz makinede CUDA
  zorunlu araçlar engelliye düşer; disk/RAM/CPU eşikleri denetlenir
  (DISK_INSUFFICIENT / RAM_INSUFFICIENT / CPU_INSUFFICIENT / GPU_MISSING)
- `apply --tool <ad> [--yes]` komutu: onay sonrası kurulum. Non-destructive
  garantileri: zaten kuruluysa RED (üzerine asla yazma), kaynak yetersizse
  RED, `--yes` yoksa interaktif onay (reddedilirse HİÇBİR ŞEY çalışmaz)
- Config `tools` kataloğu: check/gpu/min_ram_gb/min_disk_gb/min_cpus/install
  alanları (cuda-toolkit, vllm, ollama, docker, zephyr-sdk, kicad-cli,
  arm-none-eabi-gcc, qemu-system-arm, ns3)
- `push` artık kaynak + araç durumunu manifest'e otomatik ekler (eşitleme
  sırasında akıllılık; kurulum asla otomatik değildir)

### Düzeltilen
- GPU tespiti iki katmanlı: genel GPU (lspci/vulkan) ayrı, NVIDIA/CUDA
  (nvidia-smi) ayrı — virtio/VGA gibi CUDA uyumsuz GPU'lar CUDA araçlarını
  önerilmez yapar (fail-closed)

## [1.5.0] — 2026-08-12

### Eklenen — Hermes Agent Eşitleri
- `hermes-sessions` node: bir ajanın oturum bilgisi (PROJECT_STATE + kapanış
  özeti, `scripts/hermes_session_digest.py`) eşlere paylaşılır — diğer ajan
  çekip öğrenir
- `hermes-profile` node: config + cron + plugin manifest (SECRETS hariç)
- `validate_skills.py`: skill aktarım kapısı — SKILL.md varlığı + frontmatter +
  references bütünlüğü (kicad skill'inde 4 kırık referans yakaladı)

## [1.4.0] — 2026-08-13

### Eklenen
- `doctor` komutu: ortam sağlık kontrolü — bağımlılıklar (rclone/git/gh),
  node dizinleri (çoklu `paths` desteği), GDrive remote, GitHub repo erişimi
  (URL normalizasyonu + gh auth), sonuç ✅/❌
- `--dry-run` (push/both): ne yapılacağını gösterir, manifest/GitHub/GDrive'a
  HİÇBİR ŞEY yazmaz — güvenli önizleme
- Sürüm bildirimi: `version` komutu + başlıkta v1.4.0

### Düzeltilen
- GDrive çekme O(n²) performans sorunu: `tarfile.getmembers()` + rastgele
  `extractfile()` gzip'te her üye için baştan açıyordu (geriye seek yok) →
  sekansiyel iterasyon tek geçişte açar. 420MB/5000 dosyalık arşivde
  saatlerce %100 CPU → saniyeler.
- Çakışma tespitinde boyut ön-kontrolü: hedef boyut farklıysa içerik
  okumadan çakışma; içerik aynıysa yeniden yazma yok.
- rclone GDrive pull: `--drive-acknowledge-abuse` eklendi.
- config.json: GitHub repo adı düzeltildi (`cumulus-sync` → `cumulus-sync-motor`).

## [1.3.2] — 2026-08-03

- OceanAPI (gpt-5.6) denetim bulguları kapatıldı: deleted yanlış pozitif →
  SHA çakışma koruması; `run_cmd` shell=False (enjeksiyon); `gh_ensure_repo`
  JSON RC; hassas dizin reddi; çoklu yol SHA kontrolü; rclone copy shell=True
  tırnak bug'ı; sessiz aynı-içerik.

## [1.3.1] — 2026-08-03

- AKILLI BUILD GATE: kernel değişikliği → önce build doğrula, FAIL ise push
  durur + `build_break` manifest kaydı. Pipe RC bug fix (make|tail RC'sini
  yutuyordu).

## [1.3.0] — 2026-08-03

- EVRENSEL: kullanıcı kimliği + makine kimliği
  (`gdrive:hermes-sync/<user>/<machine>/versiyonlu/<node>/<ts>/`), sınırsız
  node (`add-node`), paylaşım (`share`), non-destructive çakışma
  (`.conflict.TS`), secret filtre (`.env`/`*.key`). 8 hazır node. Public repo:
  hermes-sync (MIT).

## [1.2.0] — 2026-08-03

- OpenClaw entegrasyonu: `openclaw` node + makine tespiti + skill paketi.

## [1.1.0] — 2026-08-03

- Çoklu dizin, GDrive pull non-destructive, güvenlik (secret filtre), build
  doğrulama, `list_conflicts`/`nodes`/`select`.

## [1.0.x] — 2026-08-02

- İlk sürüm: GitHub manifest merkezi + GDrive versiyonlu yedek + H1↔H2 sync.
