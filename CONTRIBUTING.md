# Katkı Rehberi (Contributing)

hermes-sync topluluğuna katkınız için teşekkürler! Her katkı — bug düzeltmesi,
dokümantasyon, test, yeni özellik — değerlidir.

## Geliştirme Döngüsü

```bash
git clone https://github.com/yolgezerahmet/hermes-sync.git
cd hermes-sync
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"          # pytest + fastapi/uvicorn (A2A için)
python3 -m pytest tests/ -q       # tüm testler geçmeli
```

## Test Standardı

- Her yeni özellik için test dosyası (`tests/test_*.py`) zorunludur
- Testler **mock/geçici dizin** kullanır — gerçek `~/.hermes`'e ASLA dokunmaz
- Kimlik testleri `AGENT_IDENTITY_DIR` env'iyle izole dizin kullanır
- `agent_identity.py` kripto testleri: roundtrip + dinleyici + replay + kurcalama
- Test süresi: toplam 10 saniyeyi aşmamalı (hızlı döngü)

```bash
python3 -m pytest tests/ -q --tb=short
# 47+ test, hepsi PASS
```

## Kod Stili

- Python 3.10+ tip ipuçları (`from __future__ import annotations`)
- Docstring: Türkçe (bu projenin dili) — kod yorumları İngilizce/Türkçe serbest
- `os.environ` değişkenleri `_state_db()` gibi fonksiyon içinde okunur
  (test izolasyonu — modül import anında sabitleme tuzağı)
- Gizli veri (token/anahtar) log'a asla basılmaz

## Commit Mesajı

```
<tip>(<kapsam>): <kısa açıklama>

- noktalı detay 1
- noktalı detay 2
```

`<tip>`: feat | fix | perf | docs | test | refactor | security

## PR Süreci

1. Feature branch açın: `git checkout -b feat/<kısa-ad>`
2. Değişiklik + test ekleyin
3. `python3 -m pytest tests/ -q` → tamamı geçmeli
4. PR açın; CI (GitHub Actions) otomatik test çalıştırır
5. İnceleme sonrası merge (squash önerilir)

## Gizlilik

- Public repo'ya `.env`, `config.json`, `sync_manifest.json`, kimlik anahtarları
  ASLA commit'lenmez (`.gitignore` korur)
- CumulusNET'e özel konfigürasyon (IP adresleri, kullanıcı adları) örnek
  dosyalarda bile yer almaz; `config.example.json` jenerik tutulur
