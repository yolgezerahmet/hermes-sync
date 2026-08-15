# H2 BAŞTAN SONA KURULUM TALİMATNAMESİ — DETAYLI
# ==============================================
# NODE AGENT + SYNC MOTOR + GDRIVE + OTONOM ZAMANLAYICI
# Tarih: 15 Ağu 2026 | Hazırlayan: H1 (cumulusnet-hermes-1)
# Versiyon: node_agent v1.1 (sürüm-bilinçli) · sync_motor v1.6.5
#
# İKİ YÖNTEM VAR:
#   YÖNTEM A (ÖNERİLEN): Tek komutla otomatik kurulum  → setup_h2_full.ps1
#   YÖNTEM B: Elle kurulum (aşağıdaki adımlar)          → tam kontrol
#
# Not: H2'nin Hermes'i zaten çalışıyor (API 8642 OK, v0.20.0). Bu talimatname
# eşitleme+yedekleme yığınını baştan kurar; Hermes kurulumu kapsam dışıdır.
# ============================================================================

# ─────────────────────────────────────────────────────────────────────────
# HIZLI BAŞLANGIÇ (YÖNTEM A) — 5 DAKİKA
# ─────────────────────────────────────────────────────────────────────────
# 1. Aşağıdaki dosyayı H2'de indir (PowerShell):
#      Invoke-WebRequest -Uri "http://100.76.82.46:9090/setup_h2_full.ps1" -OutFile "$env:USERPROFILE\setup_h2_full.ps1"
#    (veya H1'den: http://100.92.2.47:9090/setup_h2_full.ps1)
# 2. Çalıştır:
#      powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\setup_h2_full.ps1"
# 3. Script gerekirse rclone'u kurar, GDrive bağlanmasını ister, dosyaları
#    indirir, config.json hazırlar, Task Scheduler görevini kurar, ilk koşuyu
#    çalıştırır ve eşitlik raporunu basar.
# 4. Bitti. Kurulumu H1'den doğrula:
#      cd /root/cumulus-sync-motor && python3 sync_coordinator.py status
#    → tabloda sistemg16 satırı SYNC ✅ BAKUP ✅ görünmeli.

# ═══════════════════════════════════════════════════════════════════════
# YÖNTEM B — ELLEYLE KURULUM (ADIM ADIM)
# ═══════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────
# ADIM 0 — ÖN KOŞULLAR
# ─────────────────────────────────────────────────────────────────────────
# Şunların hazır olduğundan emin ol:
#   □ Windows 10/11, internet bağlantısı
#   □ Python 3.11+  (https://python.org/downloads — "Add to PATH" işaretle!)
#   □ Tailscale kurulu ve H1'e bağlı (100.76.82.46 ↔ 100.92.2.47)
#   □ Google Drive hesabı (rclone bağlantısı için tarayıcı girişi)
#
# Doğrula (PowerShell):
#   python --version          # 3.11.x olmalı
#   tailscale status          # H1 görünmeli (100.92.2.47)

# ─────────────────────────────────────────────────────────────────────────
# ADIM 1 — rclone KURULUMU
# ─────────────────────────────────────────────────────────────────────────
# 1a. rclone var mı:
#      rclone version
#     Varsa ADIM 2'ye geç.
# 1b. Yoksa indir + kur:
#      $zip = "$env:TEMP\rclone.zip"
#      Invoke-WebRequest -Uri "https://downloads.rclone.org/rclone-current-windows-amd64.zip" -OutFile $zip
#      Expand-Archive $zip "$env:TEMP\rclone-ex" -Force
#      New-Item -ItemType Directory -Force "$env:USERPROFILE\rclone" | Out-Null
#      Copy-Item (Get-ChildItem "$env:TEMP\rclone-ex" -Recurse -Filter rclone.exe | Select -First 1).FullName "$env:USERPROFILE\rclone\" -Force
#      [Environment]::SetEnvironmentVariable("PATH", "$env:USERPROFILE\rclone;" + [Environment]::GetEnvironmentVariable("PATH","User"), "User")
#      $env:PATH = "$env:USERPROFILE\rclone;" + $env:PATH
#      rclone version          # doğrula

# ─────────────────────────────────────────────────────────────────────────
# ADIM 2 — GDRIVE BAĞLANTISI (rclone remote)
# ─────────────────────────────────────────────────────────────────────────
# 2a. Mevcut remoteları listele:
#      rclone listremotes
#     "gdrive:" varsa ADIM 3'e geç.
# 2b. Bağla:
#      rclone config
#     Etkileşimli sihirbazda:
#       n (new remote)
#       name > gdrive
#       Storage > Google Drive (kaydırarak seç)
#       client_id: BOŞ bırak (Enter)
#       client_secret: BOŞ bırak (Enter)
#       scope: 1 (drive — tam erişim)
#       service_account_credentials: BOŞ (Enter)
#       Edit advanced config? > n
#       Use auto config? > y  ← tarayıcı açılır, Google hesabına giriş yap,
#                               "Allow" de
#       Configure this as a Shared Drive (Team Drive)? > n
#       y (evet, kaydet)
#       q (çık)
# 2c. Doğrula:
#      rclone lsd gdrive:           # Google Drive klasörleri listelenmeli
#      rclone lsd gdrive:hermes-sync/hahmet/
#         → "cumulusnet-hermes-1" ve "sistemg16" klasörleri görünmeli
#         (H1 zaten yazmış; H2'ninki sen ilk koşuda oluşur)

# ─────────────────────────────────────────────────────────────────────────
# ADIM 3 — DOSYALARI İNDİR
# ─────────────────────────────────────────────────────────────────────────
$dir = Join-Path $env:USERPROFILE "cumulus-sync-motor"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Set-Location $dir

# Kaynak 1: GitHub (birincil — her zaman açık)
$gh = "https://raw.githubusercontent.com/yolgezerahmet/cumulus-sync-motor/main"
# Kaynak 2: H1 9090 (yedek)
$h1 = "http://100.92.2.47:9090"

$files = @("sync_motor.py","smart_sync.py","node_agent.py",
           "sync_coordinator.py","sync_web_ui.py","config.example.json")
foreach ($f in $files) {
    try {
        Invoke-WebRequest -Uri "$gh/$f" -OutFile "$dir\$f" -UseBasicParsing -TimeoutSec 60
    } catch {
        try { Invoke-WebRequest -Uri "$h1/$f" -OutFile "$dir\$f" -UseBasicParsing -TimeoutSec 30 }
        catch { Write-Host "  ⚠ $f indirilemedi" -ForegroundColor Yellow }
    }
}
# Doğrula: 6 dosya da >500 byte olmalı
Get-ChildItem $dir | Where-Object { $_.Name -like "*.py" } | Select Name, Length

# ─────────────────────────────────────────────────────────────────────────
# ADIM 4 — CONFIG.JSON (H2 YOLLARI)
# ─────────────────────────────────────────────────────────────────────────
# config.json yoksa oluştur (H2'ye özel yollar):
$cfg = @{
    machine = $env:COMPUTERNAME
    state   = @{ manifest_local = "$dir\.sync-manifest.json"; logfile = "$dir\sync.log" }
    dirs    = @{
        kernel  = @{ path = "$env:USERPROFILE\cumulusos\kernel"; pattern = "*.{c,h}"; max_kb = 1024 }
        pcb     = @{ path = "$env:USERPROFILE\pcb"; pattern = "*"; max_kb = 20480 }
        patent  = @{ path = "$env:USERPROFILE\patent_docs"; pattern = "*"; max_kb = 10240 }
        scripts = @{ path = "$env:USERPROFILE\.hermes\scripts"; pattern = "*"; max_kb = 1024 }
        hermes  = @{ path = "$env:USERPROFILE\.hermes\config.yaml"; pattern = "*"; max_kb = 1024 }
    }
}
$cfg | ConvertTo-Json -Depth 5 | Out-File "$dir\config.json" -Encoding utf8
# Not: klasörler H2'de yoksa sync_motor o node'u "kaynak yok" diye atlar;
# bu NORMAL. Yolları kendi düzenine göre güncellemekten çekinme.

# ─────────────────────────────────────────────────────────────────────────
# ADIM 5 — DOKTOR + İLK KOŞU
# ─────────────────────────────────────────────────────────────────────────
Set-Location $dir
python node_agent.py doctor          # 6/6 ✅ olmalı (python/rclone/git/motorlar/config)

python node_agent.py once            # eşitle + yedek + hub raporu
# Beklenen çıktı:
#   NODE AGENT — SISTEMG16 (Windows) ...
#   🔄 EŞİTLE: sync_motor both [--skip-unchanged]  (motor vX.Y.Z)
#   ✅ eşitleme tamam
#   💾 YEDEK: sync_motor backup | no-op (eski motor)
#   ✅ durum → gdrive:hahmet/sistemg16/status.json

# Doğrula (status.json GDrive'da oluştu):
rclone lsf gdrive:hermes-sync/hahmet/sistemg16/

# ─────────────────────────────────────────────────────────────────────────
# ADIM 6 — OTONOM ZAMANLAYICI (Task Scheduler, her 90 dk)
# ─────────────────────────────────────────────────────────────────────────
$py = (Get-Command python).Source
$action   = New-ScheduledTaskAction -Execute $py -Argument "`"$dir\node_agent.py`" once" -WorkingDirectory $dir
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 90)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "CumulusNodeAgent" -Action $action -Trigger $trigger -Settings $settings -Force

# Doğrula:
Get-ScheduledTask -TaskName "CumulusNodeAgent" | Select TaskName, State
# State = Ready olmalı; ilk çalışma 1 dk sonra

# ─────────────────────────────────────────────────────────────────────────
# ADIM 7 — H1'DEN DOĞRULAMA (H1 makinesinde)
# ─────────────────────────────────────────────────────────────────────────
# H1'de (bu talimatnamenin kaynağı):
cd /root/cumulus-sync-motor
python3 sync_coordinator.py status
# Beklenen:
#   cumulusnet-hermes-1 | Linux   | SYNC ✅ | BAKUP ✅ | 0 çakışma
#   sistemg16          | Windows | SYNC ✅ | BAKUP ✅ | 0 çakışma

# Alternatif: web paneli (H1, SSH tüneli ile):
#   ssh -L 8147:localhost:8147 root@129.121.91.123
#   http://localhost:8147  → /api/status → machines alanında sistemg16

# ─────────────────────────────────────────────────────────────────────────
# SORUN GİDERME
# ─────────────────────────────────────────────────────────────────────────
# P1. "rclone: command not found"
#     → PATH'e rclone klasörünü ekle veya PowerShell'i yeniden başlat.
# P2. GDrive bağlanamadı (tarayıcı açılmadı)
#     → rclone config'te "Use auto config? > n" seçip çıkan URL'yi elle aç,
#       token'ı yapıştır.
# P3. İlk koşuda "config.json yok" / "machine: None"
#     → ADIM 4'ü çalıştır (config.json oluştur).
# P4. "sync_motor both --skip-unchanged" hatası
#     → Motor eski sürüm (v1.6.2 öncesi). node_agent sürüm-bilinçli:
#       otomatik olarak plain "both" kullanır. Yoksa sync_motor.py'yi
#       GitHub'dan güncelle: Invoke-WebRequest ... sync_motor.py
# P5. Task Scheduler görevi çalışmıyor
#     → Görevin "History" sekmesini aç (Task Scheduler → görev → History),
#       çalıştırma hatasını gör. En yaygın: python yolu yanlış — ADIM 6'daki
#       $py değerini kontrol et.
# P6. status.json GDrive'da yok
#     → rclone lsf gdrive:hermes-sync/hahmet/ → boşsa ADIM 2'yi tekrarla
#       (remote adı tam "gdrive:" olmalı).

# ─────────────────────────────────────────────────────────────────────────
# HIZLI REFERANS — SIK KOMUTLAR
# ─────────────────────────────────────────────────────────────────────────
#   python node_agent.py once            # eşitle + yedek + rapor (elle)
#   python node_agent.py status --json   # sadece durum
#   python node_agent.py doctor          # sağlık kontrolü
#   python sync_coordinator.py status    # tüm makinelerin durumu
#   rclone lsf gdrive:hermes-sync/hahmet/sistemg16/   # hub doğrulama
