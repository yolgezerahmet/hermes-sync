# Delegasyon (Subagent) Fix — OceanAPI 3 Hatalı Pitfall Zinciri (28 Ağu 2026)

## SORUN BELİRTİSİ
Delegasyon/subagent çağrıları çalışmıyor veya yanlış modelde (gpt-5-mini fallback).
Ana oturum çalışıyor ama subagent'lar hata veriyor.

## 3 HATALI PİTFALL ZİNCİRİ (sırayla kontrol et)

### 1. HTTP 403 "Your request was blocked" — User-Agent EKSİK
```
NEDEN: OceanAPI Cloudflare, User-Agent header'ı ZORUNLU kılıyor.
       Delegasyon alt ajanı UA göndermiyor → Cloudflare bloklar (403).
FIX: custom_providers (list!) içinde oceanapi bloğuna ekle:
    extra_headers:
      User-Agent: hermes-1
KONUM: /root/.hermes/config.yaml → custom_providers (LİST tipi! dict değil)
```

### 2. HTTP 401 "Invalid or inactive API key" — TIRNAKLI KEY
```
NEDEN: .env'de OCEANAPI_API_KEY="sk-..." (tırnaklı).
       Ana oturum tırnakları strip eder, delegasyon alt ajanı ETMEZ → 401.
FIX: .env'de tırnakları kaldır:
    OCEANAPI_API_KEY=sk-...   (tırnaksız!)
KONTROL: python3 -c "print(open('/root/.hermes/.env').read().count('OCEANAPI_API_KEY=\"'))" → 0 olmalı
```

### 3. HTTP 401 DEVAM — Gateway ESKİ CONFIG
```
NEDEN: Config değişti ama gateway process eski config ile çalışıyor.
       'hermes gateway restart' PID DEĞİŞTİRMEYEBİLİR (drain bekler).
FIX: SERT restart:
    kill -9 <PID>  (ps -p PID ile doğrula)
    systemctl --user reset-failed hermes-gateway
    hermes gateway start
    hermes gateway status | grep PID  → YENİ PID olmalı!
```

## EN SAĞLAM CONFIG (inline key — env bağımlılığı yok)
```yaml
delegation:
  provider: custom:oceanapi
  model: gpt-5-6-sol
  base_url: https://api.oceanapi.dev/v1
  api_key: sk-...          # INLINE (api_key_env KULLANMA — alt ajan bulamıyor)
  api_mode: chat
  max_concurrent_children: 5   # OceanAPI eşzamanlı limit 6
  max_iterations: 100
  max_spawn_depth: 2
  orchestrator_enabled: true
  temperature: 0.0
  # top_p KULLANMA! (OceanAPI 400: "not supported with this model")
  # extra_body: {} BOŞ KALSIN
```

## DOĞRULAMA (canlı test — 28 Ağu 2026 BAŞARILI)
```
✅ 4+4=8 · gpt-5-6-sol · api_calls=2 · 7.68s · exit=completed
✅ execute_code tool erişimi tam
```

## DİĞER OCEANAPI KISITLARI (delegasyonda da geçerli)
```
- top_p: 400 hatası (kullanma)
- temperature: destekleniyor (0.0 OK)
- User-Agent: zorunlu
- Eşzamanlı: 6 (max_concurrent_children: 5 güvenli)
- Uzun çıktı → DeepSeek V4-Pro'ya yönlendir (105s timeout)
```
