# H2 — SYNCLAVE GEÇİŞ PAKETİ (30 Ağu 2026)

## DURUM ÖZETİ (H1'den canlı ölçüm)

| Bileşen | Durum | Açıklama |
|---|---|---|
| A2A sunucu (8643) | ✅ AKTİF | SISTEMG16 çalışıyor |
| Kimlik (Ed25519) | ✅ AKTİF | agent_id: hx-j03zb0vnv3ekgjmjccg447t2 |
| Şifreleme (X25519+AES-GCM) | ✅ AKTİF | encryptedRequests: true |
| İmza + replay koruması | ✅ AKTİF | signedRequests: true |
| H1↔H2 şifreli konuşma | ✅ DOĞRULANDI | conversation_id a.j03zb0vn~rxbhv62t...#1 |
| GPU analiz (8644) | ❌ KAPALI | gpu_agent.py + Ollama gerekli |
| Sohbet köprüsü | ❓ KONTROL ET | conversation_bridge.py çalıştırılmalı |
| Sync motor | ✅ AKTİF | git pull ile güncel |

## YAPILACAKLAR (sırayla, ~15 dk)

### 1) GPU ANALİZ KANALI (RTX 5070 Ti)
```powershell
# 1a) Ollama kur (LLM inference motoru)
winget install Ollama.Ollama
# veya https://ollama.com/download (Windows kurulumu)

# 1b) İlk modeli çek (örn. küçük + hızlı)
ollama pull llama3.2:3b
# veya qwen2.5:7b (daha güçlü, 5070 Ti'da hızlı)

# 1c) GPU bağımlılıkları
pip install fastapi uvicorn requests

# 1d) gpu_agent.py'yi başlat (bu pakette var)
cd C:\path\to\synclave_kod
python gpu_agent.py --port 8644
```

### 2) SOHBET KÖPRÜSÜ (H2'nin kendi sohbetleri deftere)
```powershell
# H2'nin Hermes state.db'sini sohbet defterine işle (ilk sefer --full)
cd C:\path\to\synclave_kod
python conversation_bridge.py --full

# Otomatik (her 15 dk) — Görev Zamanlayıcı'ya ekle:
#   Program: python
#   Argüman: C:\path\to\synclave_kod\conversation_bridge.py
#   Tetikleyici: 15 dk'da bir
```

### 3) DOĞRULAMA (otomatik script)
```powershell
python h2_dogrula.py
# → her satır OK/PASS olmalı, FAIL varsa aşağıdaki sorun giderme
```

### 4) H1'DEN TEST (H2 kurulumu tamamlanınca H1'de çalıştırılır)
```bash
# H1'de:
python3 gpu_task.py status          # H2 GPU durumu (ollama + model + VRAM)
python3 gpu_task.py task "Merhaba H2, GPU'da çalışıyor musun?"
# → H2'de Ollama sonucu H1'e döner, /root/.hermes/state/gpu_results/ arşivlenir
```

## SORUN GİDERME
- **A2A 8643'te agent_id görünmüyor** → eski kod çalışıyor; git pull + restart
- **gpu_agent 8644 başlamıyor** → fastapi/uvicorn eksik: `pip install fastapi uvicorn`
- **Ollama yanıt vermiyor** → servis başladı mı: `ollama serve` (gerekirse)
- **conversation_bridge yavaş** → ilk --full birkaç saniye sürer; sonrası artımlı
- **Şifreli gönderim 403** → H1 ile A2A_TOKEN aynı olmalı (.env'de)
- **Sohbet defteri nerede** → ~/.hermes/identity/conversations.db (H2'de C:\Users\yolge\.hermes\identity\)

## DOSYALAR (bu pakette)
- synclave_kod/agent_identity.py      — kimlik + şifreleme çekirdeği
- synclave_kod/agent_mesh_a2a.py      — A2A sunucusu (8643)
- synclave_kod/a2a_cli.py             — A2A istemcisi (imzalı/şifreli)
- synclave_kod/gpu_agent.py           — GPU analiz sunucusu (8644)
- synclave_kod/gpu_task.py            — GPU görev istemcisi (H1'de kullanılır)
- synclave_kod/conversation_bridge.py — sohbet köprüsü (state.db → defter)
- synclave_kod/sync_motor.py          — sync motor (güncel)
- h2_dogrula.py                       — otomatik doğrulama
- H2_SYNCLAVE_GECIS.md                — bu talimat

## NOT
- H2, H1'deki cumulus-sync-motor (private) kopyasını kullanıyorsa kodlar
  birebir aynıdır; isim farkı (hermes_sync ↔ synclave) sadece PyPI paketinde.
- GPU kanalı kurulduktan sonra H1'den `gpu_task.py status` çalışırsa
  cluster 3 node TAMAM: kimlik + şifreli mesh + GPU offload.
