# Hermes Agent Eşitleme Tasarımı — v1.5 (12 Ağu 2026)
**Amaç:** hermes-sync'i GERÇEK Hermes ajanları arası eşitlemeye taşı: eş-oturum
bilgi paylaşımı, skill aktarımı, profil yedekleme. Kadirr dersi: tek sağlayıcıya
bağımlılık kırılgan — aynı şey TEK Hermes kurulumu için de geçerli; 2+ ajan birbirini
yedekler + birbirinin durumunu bilir.

## 1. YENİ NODELAR (config.json, uygulandı)
| Node | İçerik | Kullanım |
|------|--------|----------|
| hermes-sessions | ~/.hermes/agent-share/sessions/*.md (PROJECT_STATE + kapanış özeti) | AJAN B diğer AJAN A'nın durumunu çeker/öğrenir |
| hermes-profile | ~/.hermes/agent-share/profile (config + cron + plugin manifest, SECRETS HARİÇ) | ajan yapılandırması peer'e taşınır |

## 2. SCRIPT'LER (scripts/, uygulandı)
- hermes_session_digest.py: oturum özeti üretici → hermes-sessions node'una
- validate_skills.py: skill aktarımı öncesi bütünlük (SKILL.md + frontmatter + references)

## 3. AKIŞ (A → B ajan)
1. AJAN A: `hermes_session_digest.py` → özet yazılır → `sync_motor.py --node hermes-sessions push`
2. AJAN B: `sync_motor.py --node hermes-sessions pull` → özeti okur → "AJAN A şu durumda, kaldığı yer X"
3. SKILL: AJAN A `validate_skills.py` (RED=push yok) → `--node hermes-skills push`; B `pull` → skill'ler taşınır
4. PROFİL: `--node hermes-profile push/pull` → config + cron taşınır (secrets hariç — mevcut gizli filtre korur)

## 4. GÜVENLİK
- .env/*.key/pem/id_rsa manifest'e GİRMEZ (mevcut filtre, v1.3.2)
- hermes-profile config.yaml içerir AMA api_key_env referansları korunur (değerler .env'de kalır)
- Çakışmalar non-destructive (.conflict.TS) — v1.1 mekanizması

## 5. KALAN (sonraki)
- Ajan kimlik manifesti (ajan adı/versiyon/node listesi) → keşif dosyası
- Cron transferi için jobs.json validation
- Şifreli oturum özeti (SE052F değil, host tarafında AES) — opsiyonel
- H2'de bu script'lerin Windows karşılığı (PowerShell) — sync_from_h1.ps1'e ek
