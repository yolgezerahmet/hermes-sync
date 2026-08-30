# H2 (Windows) — Ajan Kimliği + Sohbet Etiketleme Kurulum Notu

Tarih: 30 Ağu 2026 · Sürüm: sync_motor v2.2.0 · Kimlik: agent_identity.py

## Ne değişti?
Mesh'e bağlı HER çalışma zamanı (H1/H2/H3/OpenClaw) artık kendi kriptografik
kimliğine sahip. Sohbetler (kullanıcı↔ajan, ajan↔ajan) ayrı ID ile etiketleniyor
ve asla karışmıyor.

## Adım 1 — Kod güncelle
```powershell
cd C:\path\to\cumulus-sync-motor   # H2'deki repo
git pull origin main               # 7688f0c (v2.2.0) gelir
```

## Adım 2 — Bağımlılık (bir kez)
```powershell
pip install cryptography           # Ed25519 imza için
```

## Adım 3 — Kimliği üret/doğrula
```powershell
python agent_identity.py show          # hx-... veya oc-... ID üretir
python agent_identity.py verify-self   # imza + ID-anahtar tutarlılığı
python sync_motor.py identity show
```

## Adım 4 — A2A sunucusunu kimlikli modda yeniden başlat
Windows'ta a2a servisi nasıl başlatılıyorsa (Görev Zamanlayıcı / nohup):
```powershell
# mevcut a2a sürecini durdur, sonra:
python agent_mesh_a2a.py --port 8643
```
Kimlik modülü otomatik yüklenir (AgentCard'ta identity alanı görünür).

## Adım 5 — Doğrula
- `http://<H2-IP>:8643/health` → `agent_id` + `clone_state: clean`
- `http://<H2-IP>:8643/identity` → açık kimlik + peer sayacı
- H1'den: `python a2a_cli.py send <H2-IP> "selam" --token <A2A_TOKEN>`
  → yanıtta `conversation_id` (a. önekli) döner

## Güvenlik gerçekleri
- agent_id = açık anahtar özeti; anahtar başka donanıma kopyalanırsa
  clone_state=suspected → mesh 403 RED (fail-closed)
- Meşru taşıma: `python agent_identity.py rekey --confirm`
- Tüm node'lar güncellendikten sonra `--require-signature` açılacak
- İmzasız istekler defteri kirletmez (from_verified=False)

## Kimlik/sohbet formatları
- ID: `hx-...` (Hermes) / `oc-...` (OpenClaw)
- Kullanıcı sohbeti: `u.<agent8>.<kanal>.<peer8>.<ulid>`
- Ajan sohbeti:    `a.<agent8>~<peer8>.<kanal>.<ulid>`
- Mesaj: `<conv_id>#<seq>` — içerik saklanmaz (sadece sha256)
- Defter: `~/.hermes/identity/conversations.db`
