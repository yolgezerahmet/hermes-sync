# H2 (Windows) — GÜNCELLEME: Şifreli A2A + Sohbet Köprüsü + GPU Rolü

Tarih: 30 Ağu 2026 · Sürüm: sync_motor v2.3.0 (kimlik+şifreleme+köprü)

## NE DEĞİŞTİ (H1/H3'te AKTİF — H2'de kurulacak)
1. A2A mesajları artık ŞİFRELİ: X25519 ECDH + AES-GCM (PFS) + Ed25519 imza.
   Dinleyen taraf içeriği ÇÖZEMEZ; kurcalama/replay REDDEDİLİR.
2. Sohbet defteri: tüm kullanıcı sohbetleri (telegram/cli/whatsapp) ve
   ajan-ajan sohbetleri conversations.db'de; içerik SAKLANMAZ (sha256).
3. H2 GPU ROLÜ: RTX 5070 Ti ile analiz görevleri (LLM/vision/embedding).

## ADIM 1 — Kod güncelle
```powershell
cd C:\path\to\cumulus-sync-motor
git pull origin main          # 1716b20 (kimlik + şifreleme + köprü)
pip install cryptography      # X25519/AES-GCM için (bir kez)
```

## ADIM 2 — A2A sunucusunu şifreli modda yeniden başlat
```powershell
# mevcut a2a sürecini durdur (Görev Zamanlayıcı / elle)
python agent_mesh_a2a.py --port 8643
# doğrula:
#   http://<H2-IP>:8643/.well-known/agent.json → capabilities.encryptedRequests: true
```

## ADIM 3 — Kimliği doğrula
```powershell
python agent_identity.py show        # hx-... (Windows makinesine özel)
python agent_identity.py verify-self
python sync_motor.py identity show
```

## ADIM 4 — GPU analiz sunucusu (RTX 5070 Ti)
H2'de GPU araçları (Ollama / llama.cpp / vLLM) kuruluysa:
```powershell
# gpu_agent.py bu repoya eklenecek (H1'den gelecek) — port 8644
# H1 komutu: python a2a_cli.py send <H2-IP> "gpu:analiz <görev>"
```
GPU sunucusu H2'de kurulmadan önce H1'den görev gönderilirse H2 inbox'a
not olarak düşer (worker yoksa H2 kullanıcısı işler).

## ADIM 5 — Sohbet köprüsü (H2'de Hermes varsa)
```powershell
python conversation_bridge.py --full   # H2'nin kendi state.db'sini işle
# otomatik: Görev Zamanlayıcı'ya 15 dk'da bir conversation_bridge.py ekle
```

## DOĞRULAMA (H1'den)
```powershell
# H1: python a2a_cli.py send <H2-IP> "selam" --token <A2A_TOKEN>
# yanıtta conversation_id (a. önekli) + served_by (H2 agent_id) döner
```

## GÜVENLİK ÖZETİ
- Kimlik: agent_id = pubkey özeti (hx-/oc-), donanım bağı + klon fail-closed
- Bütünlük: Ed25519 imza (gövde+ts+nonce)
- Gizlilik: X25519 ECDH + AES-GCM (her mesajda ephemeral → PFS)
- Replay: ts (±120s) + nonce tekrarı reddi
- Ölçek: her node kendi anahtarına sahip → 3/20 node aynı model (mac/win/linux)
- Eski sunucular: imzalı ama düz gövde kabul eder (geriye uyum)
