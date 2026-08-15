# H2 KURULUM TALİMATI — Otonom Eşitleme + Yedekleme (15 Ağu 2026)
# ==============================================================
# H1 (cumulusnet-hermes-1) hazırladı. Dosyalar H2'nin 9090'ında duruyor.
# Adresler: http://100.76.82.46:9090/ (H2 kendi listesi)

# ADIM 1 — Python kurulu mu?
python --version   # yoksa: https://python.org/downloads (3.11+)

# ADIM 2 — rclone kurulu mu?
rclone version     # yoksa install_node_agent.ps1 kurar

# ADIM 3 — Dosyaları indir (H2'de, PowerShell):
$base = "http://100.76.82.46:9090"
$dir = "$env:USERPROFILE\cumulus-sync-motor"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
foreach ($f in @("node_agent.py","sync_motor.py","smart_sync.py","sync_coordinator.py","sync_web_ui.py","install_node_agent.ps1","config.example.json")) {
    Invoke-WebRequest -Uri "$base/$f" -OutFile "$dir\$f" -UseBasicParsing
}

# ADIM 4 — Kurulum scriptini çalıştır (Task Scheduler + ilk koşu):
Set-Location $dir
powershell -ExecutionPolicy Bypass -File .\install_node_agent.ps1

# ADIM 5 — rclone GDrive bağla (gdrive: remote adıyla):
rclone config
#   n → new remote → ad: gdrive → Google Drive → client_id boş → otomatik token

# ADIM 6 — GDrive erişimini doğrula + ilk koşuyu elle tetikle:
rclone lsd gdrive:hermes-sync/hahmet/
python node_agent.py once

# DOĞRULAMA — H1'den tüm makineleri gör:
#   cd /root/cumulus-sync-motor && python3 sync_coordinator.py status
#   → tabloda H2 (sistemg16) satırı SYNC ✅ BAKUP ✅ görünmeli
