# Güvenlik Politikası (Security Policy)

hermes-sync güvenlik açıkları ciddiye alınır. Lütfen sorunları **public
issue olarak açmayın** — özel bildirin.

## Bildirim

- E-posta: ahmethudayioglu@cumulusnet.io
- Konu satırına `[hermes-sync security]` ekleyin
- Yanıt süresi: 48 saat içinde ilk değerlendirme

## Kapsam

Aşağıdaki bileşenlerdeki güvenlik açıkları bildirilebilir:

- `agent_identity.py` — kimlik üretimi, imza, şifreleme (Ed25519/X25519/AES-GCM)
- `agent_mesh_a2a.py` — istek doğrulama, replay koruması, rate limit
- `a2a_cli.py` — imzalı/şifreli gönderim
- `conversation_bridge.py` — state.db okuma, içerik hash'leme
- `sync_motor.py` — secret filtre, kilit, non-destructive yazma
- `inbox_worker.py` — allowlist komut yürütme

## Kapsam dışı

- `.env` / kimlik anahtarlarının kullanıcı tarafından yanlış saklanması
- Tailscale ağ yapılandırması (mesh ağı kullanıcının sorumluluğundadır)
- Üçüncü taraf bağımlılıklar (fastapi, uvicorn, restic, syncthing)

## Güvenli Varsayılanlar

1. **Fail-closed**: kimlik klon şüphesi → mesh 403 (ister imzalı ister token)
2. **Gizlilik**: A2A gövdeleri X25519 ECDH + AES-GCM ile şifrelenir (PFS)
3. **Bütünlük**: Ed25519 imza (gövde + ts + nonce) — kurcalama reddedilir
4. **Replay**: ±120s pencere + nonce tekrarı reddi
5. **Brute-force**: rate limit (429 Too Many Requests)
6. **Secret filtre**: `.env`, `*.key`, `*.pem`, token'lar asla kapsama alınmaz
7. **Non-destructive**: çakışma `.conflict.<ts>` ile korunur, üzerine yazılmaz

## Sorumlu Açıklama (Responsible Disclosure)

- Açığı kanıtlayan minimum repro (kod + ortam) gönderin
- Açık public duyuru yapmadan önce 90 gün makul süre tanıyın
- Kullanıcı verisi içeren örnekler göndermeyin (kendi test verinizi kullanın)
