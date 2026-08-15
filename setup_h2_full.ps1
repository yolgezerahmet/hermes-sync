# =============================================================================
# setup_h2_full.ps1 — H2 (Windows) BAŞTAN SONA OTOMATİK KURULUM
# =============================================================================
# NODE AGENT + SYNC MOTOR + GDRIVE + TASK SCHEDULER (tek komutla)
# -----------------------------------------------------------------------------
# NE YAPAR (sırayla):
#   1. Python 3.11+ kontrol (yoksa indirir)
#   2. rclone kontrol (yoksa indirir)
#   3. GDrive remote kontrol (yoksa rehberli bağlar)
#   4. sync_motor + node_agent + smart_sync + koordinatör indirir
#      (kaynak: GitHub birincil, H1 9090 yedek)
#   5. config.json'u H2 yollarıyla oluşturur
#   6. Task Scheduler görevi kurar (her 90 dk: node_agent.py once)
#   7. İLK KOŞUYU hemen çalıştırır (doğrulama)
#   8. Eşitlik raporu basar (sync_coordinator)
# -----------------------------------------------------------------------------
# KULLANIM (PowerShell — yönetici GEREKMEZ):
#   powershell -ExecutionPolicy Bypass -File setup_h2_full.ps1
# -----------------------------------------------------------------------------
# NOTLAR:
#   - H2 geri bildirimi: kullanıcı klasörü sabit DEĞİL — $env:USERPROFILE kullan
#   - UTF-8 BOM ile kaydet (Türkçe karakter bozulmasın): dosya yukarıdaki gibi
#   - Task Scheduler görevi adı: CumulusNodeAgent
# =============================================================================

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ── Yapılandırma ────────────────────────────────────────────────────────────
$SyncDir      = Join-Path $env:USERPROFILE "cumulus-sync-motor"
$HermesDir    = Join-Path $env:USERPROFILE ".hermes"
$StateDir     = Join-Path $HermesDir "state"
$TaskName     = "CumulusNodeAgent"
$TaskInterval = 90                      # dakika
$GDriveRemote = "gdrive"                # rclone remote adı
$GitHubBase   = "https://raw.githubusercontent.com/yolgezerahmet/cumulus-sync-motor/main"
$H1Base       = "http://100.92.2.47:9090"   # yedek kaynak (H1 upload)
$Files        = @("sync_motor.py","smart_sync.py","node_agent.py",
                  "sync_coordinator.py","sync_web_ui.py","config.example.json")

function Log($msg, $color = "Gray") {
    Write-Host ("{0} {1}" -f (Get-Date -Format "HH:mm:ss"), $msg) -ForegroundColor $color
}

Write-Host ""
Write-Host "══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  H2 BAŞTAN SONA KURULUM — NODE AGENT + SYNC MOTOR + GDRIVE" -ForegroundColor Cyan
Write-Host ("  Makine: " + $env:COMPUTERNAME + "  Kullanıcı: " + $env:USERNAME) -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── 1. PYTHON ───────────────────────────────────────────────────────────────
Log "ADIM 1/8 — Python kontrolü" -Color Yellow
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Log "  python bulunamadı — indiriliyor (python.org)" -Color Yellow
    $url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $exe = "$env:TEMP\python-install.exe"
    Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
    Start-Process -FilePath $exe -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1" -Wait
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        # PATH yenilenmediyse standart konumdan dene
        $py = Get-Command "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe" -ErrorAction SilentlyContinue
    }
}
if (-not $py) {
    Log "  ❌ python hâlâ bulunamadı — https://python.org/downloads adresinden kur ve script'i yeniden çalıştır" -Color Red
    exit 1
}
$pyVer = & $py.Source --version 2>&1
Log ("  ✅ Python: " + $pyVer) -Color Green

# ── 2. RCLONE ───────────────────────────────────────────────────────────────
Log "ADIM 2/8 — rclone kontrolü" -Color Yellow
$rc = Get-Command rclone -ErrorAction SilentlyContinue
if (-not $rc) {
    Log "  rclone bulunamadı — indiriliyor" -Color Yellow
    $url = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"
    $zip = "$env:TEMP\rclone.zip"
    $ex = "$env:TEMP\rclone-ex"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $ex -Force
    $exe = Get-ChildItem $ex -Recurse -Filter "rclone.exe" | Select-Object -First 1
    $inst = Join-Path $env:USERPROFILE "rclone"
    New-Item -ItemType Directory -Force -Path $inst | Out-Null
    Copy-Item $exe.FullName -Destination $inst -Force
    # PATH'e ekle (oturum + kalıcı)
    $env:PATH = "$inst;" + $env:PATH
    [Environment]::SetEnvironmentVariable("PATH", "$inst;" + [Environment]::GetEnvironmentVariable("PATH","User"), "User")
    $rc = Get-Command rclone -ErrorAction SilentlyContinue
    if (-not $rc) { $rc = Get-Command (Join-Path $inst "rclone.exe") -ErrorAction SilentlyContinue }
}
if (-not $rc) {
    Log "  ❌ rclone kurulamadı — manuel: https://rclone.org/downloads" -Color Red
    exit 1
}
Log ("  ✅ rclone: " + (& $rc.Source version 2>&1 | Select-Object -First 1)) -Color Green

# ── 3. GDRIVE REMOTE ────────────────────────────────────────────────────────
Log "ADIM 3/8 — GDrive remote kontrolü" -Color Yellow
$gdriveOk = (& rclone listremotes 2>$null | Select-String "^$GDriveRemote:" )
if (-not $gdriveOk) {
    Log "  ❌ '$GDriveRemote' remote'u yok — bağlanması gerekiyor" -Color Red
    Log "  AŞAĞIDAKİ KOMUTU ÇALIŞTIR (tarayıcıda Google hesabına giriş yap):" -Color White
    Log "      rclone config" -Color Cyan
    Log "  → n (new remote) → ad: $GDriveRemote → Google Drive →" -Color Cyan
    Log "  → client_id: boş bırak → client_secret: boş bırak → scope: drive" -Color Cyan
    Log "  → root_folder_id: boş → service_account: n → auto config: y → tarayıcı token" -Color Cyan
    Log "  → y (yes this is OK) → q (quit)" -Color Cyan
    Log "  Bağlandıktan sonra script'i YENİDEN çalıştır." -Color Yellow
    exit 1
}
Log ("  ✅ GDrive remote hazır: " + $gdriveOk.ToString().Trim()) -Color Green

# ── 4. DOSYALARI İNDİR ──────────────────────────────────────────────────────
Log "ADIM 4/8 — sync_motor + node_agent indiriliyor" -Color Yellow
New-Item -ItemType Directory -Force -Path $SyncDir | Out-Null
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
Set-Location $SyncDir

foreach ($f in $Files) {
    $dest = Join-Path $SyncDir $f
    $ok = $false
    # Birincil: GitHub
    try {
        Invoke-WebRequest -Uri "$GitHubBase/$f" -OutFile $dest -UseBasicParsing -TimeoutSec 60
        $ok = (Get-Item $dest).Length -gt 500
    } catch { $ok = $false }
    # Yedek: H1 9090
    if (-not $ok) {
        try {
            Invoke-WebRequest -Uri "$H1Base/$f" -OutFile $dest -UseBasicParsing -TimeoutSec 30
            $ok = (Get-Item $dest).Length -gt 500
        } catch { $ok = $false }
    }
    if ($ok) { Log ("  ✅ " + $f) -Color Green }
    else     { Log ("  ⚠ " + $f + " indirilemedi — kaynak erişilemez") -Color Yellow }
}

# ── 5. CONFIG.JSON ──────────────────────────────────────────────────────────
Log "ADIM 5/8 — config.json hazırlanıyor" -Color Yellow
$cfgPath = Join-Path $SyncDir "config.json"
if (-not (Test-Path $cfgPath)) {
    $cfg = @{
        machine = $env:COMPUTERNAME
        state   = @{ manifest_local = (Join-Path $SyncDir ".sync-manifest.json"); logfile = (Join-Path $SyncDir "sync.log") }
        dirs    = @{
            kernel  = @{ path = (Join-Path $env:USERPROFILE "cumulusos\kernel"); pattern = "*.{c,h}"; max_kb = 1024 }
            pcb     = @{ path = (Join-Path $env:USERPROFILE "pcb"); pattern = "*"; max_kb = 20480 }
            patent  = @{ path = (Join-Path $env:USERPROFILE "patent_docs"); pattern = "*"; max_kb = 10240 }
            scripts = @{ path = (Join-Path $HermesDir "scripts"); pattern = "*"; max_kb = 1024 }
            hermes  = @{ path = (Join-Path $HermesDir "config.yaml"); pattern = "*"; max_kb = 1024 }
        }
    }
    $cfg | ConvertTo-Json -Depth 5 | Out-File -FilePath $cfgPath -Encoding utf8
    Log "  ✅ config.json oluşturuldu (H2 yolları)" -Color Green
} else {
    Log "  ℹ config.json zaten var — korunuyor" -Color Gray
}

# ── 6. TASK SCHEDULER ───────────────────────────────────────────────────────
Log "ADIM 6/8 — Task Scheduler görevi ($TaskName, her ${TaskInterval} dk)" -Color Yellow
$pyPath = $py.Source
$action   = New-ScheduledTaskAction -Execute $pyPath -Argument "`"$SyncDir\node_agent.py`" once" -WorkingDirectory $SyncDir
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $TaskInterval)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Log "  ✅ Görev kayıtlı: $TaskName (her $TaskInterval dk)" -Color Green
} catch {
    Log ("  ⚠ Task Scheduler kaydı başarısız: " + $_.Exception.Message) -Color Yellow
}

# ── 7. İLK KOŞU ─────────────────────────────────────────────────────────────
Log "ADIM 7/8 — ilk koşu (node_agent.py once)" -Color Yellow
Push-Location $SyncDir
try {
    & $pyPath node_agent.py once
    Log ("  ✅ ilk koşu rc=" + $LASTEXITCODE) -Color Green
} catch {
    Log ("  ⚠ ilk koşu hatası: " + $_.Exception.Message) -Color Yellow
}
Pop-Location

# ── 8. EŞİTLİK RAPORU ───────────────────────────────────────────────────────
Log "ADIM 8/8 — eşitlik raporu" -Color Yellow
Push-Location $SyncDir
try {
    & $pyPath sync_coordinator.py status
} catch {
    Log ("  ⚠ rapor alınamadı: " + $_.Exception.Message) -Color Yellow
}
Pop-Location

Write-Host ""
Write-Host "══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  KURULUM TAMAMLANDI" -ForegroundColor Green
Write-Host "══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Görev      : $TaskName (her $TaskInterval dk, Task Scheduler)" -ForegroundColor White
Write-Host "  Dizin      : $SyncDir" -ForegroundColor White
Write-Host "  Durum      : gdrive:hermes-sync/hahmet/$($env:COMPUTERNAME.ToLower())/status.json" -ForegroundColor White
Write-Host ""
Write-Host "  Elle çalıştırmak istersen:" -ForegroundColor Yellow
Write-Host "      cd $SyncDir" -ForegroundColor Cyan
Write-Host "      python node_agent.py once        # eşitle + yedek + rapor" -ForegroundColor Cyan
Write-Host "      python node_agent.py doctor      # sağlık kontrolü" -ForegroundColor Cyan
Write-Host "      python sync_coordinator.py status# tüm makineler" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
