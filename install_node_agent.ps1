# install_node_agent.ps1 — H2 (Windows) Otonom Eşitleme+Yedekleme Kurulumu
# =========================================================================
# Bu script H2'de çalıştırılır ve şunları yapar:
#   1. rclone var mı kontrol et (yoksa indir + kur)
#   2. sync_motor + node_agent + smart_sync dosyalarını kopyalar
#   3. config.json'u makineye göre hazırlar
#   4. Task Scheduler görevi oluşturur (her 90 dk: node_agent.py once)
#   5. İlk koşuyu hemen çalıştırır (doğrulama)
#
# KULLANIM (PowerShell, yönetici DEĞİL gerekmez):
#   powershell -ExecutionPolicy Bypass -File install_node_agent.ps1
#
# Geliştiren: CumulusNET Mühendislik — 2026

$ErrorActionPreference = "Stop"
# NOT (H2 geri bildirimi, 15 Ağu): kullanıcı klasörü `hahmet` DEĞİL — `yolge`.
# Windows'ta gerçek kullanıcı profilini otomatik almak için $env:USERPROFILE kullanılır.
$SyncDir = Join-Path $env:USERPROFILE "cumulus-sync-motor"
$HermesDir = Join-Path $env:USERPROFILE ".hermes"
$ScriptsDir = Join-Path $SyncDir "scripts"
$TaskName = "CumulusNodeAgent"

Write-Host "=== NODE AGENT KURULUMU (H2) ===" -ForegroundColor Cyan
Write-Host ("Makine: " + $env:COMPUTERNAME + " | Kullanıcı: " + $env:USERNAME)

# 1. rclone kontrol
$rclone = Get-Command rclone -ErrorAction SilentlyContinue
if (-not $rclone) {
    Write-Host "rclone bulunamadı — indiriliyor..." -ForegroundColor Yellow
    $url = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"
    $zip = "$env:TEMP\rclone.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath "$env:TEMP\rclone" -Force
    $rcloneExe = Get-ChildItem "$env:TEMP\rclone" -Recurse -Filter "rclone.exe" | Select-Object -First 1
    $installDir = "$env:LOCALAPPDATA\Microsoft\WindowsApps"
    Copy-Item $rcloneExe.FullName -Destination $installDir -Force
    Write-Host "rclone kuruldu: $installDir\rclone.exe" -ForegroundColor Green
} else {
    Write-Host ("rclone: " + $rclone.Source) -ForegroundColor Green
}

# 2. Dizinler + dosya kopyalama
New-Item -ItemType Directory -Force -Path $SyncDir | Out-Null
New-Item -ItemType Directory -Force -Path $HermesDir | Out-Null
New-Item -ItemType Directory -Force -Path $ScriptsDir | Out-Null

# Kaynak: H1 9090'dan (Tailscale üzerinden) veya mevcut dizinden
$srcDir = $SyncDir  # script'in yanında duruyorsa aynı yer
if (Test-Path "$srcDir\sync_motor.py") {
    Write-Host "sync_motor mevcut: $srcDir"
} else {
    # H1'den çek (Tailscale 9090 veya 100.92.2.47)
    Write-Host "sync_motor H1'den çekiliyor (9090)..." -ForegroundColor Yellow
    $h1 = "http://100.92.2.47:9090"
    foreach ($f in @("sync_motor_v160.py", "sync_from_h1.ps1")) {
        try {
            Invoke-WebRequest -Uri "$h1/$f" -OutFile "$SyncDir\$f" -UseBasicParsing -TimeoutSec 30
        } catch {
            Write-Host "  ⚠ $f çekilemedi: $_" -ForegroundColor Yellow
        }
    }
}

# 3. config.json hazırla (machine adı yoksa)
$cfgPath = "$SyncDir\config.json"
if (-not (Test-Path $cfgPath)) {
    Write-Host "config.json oluşturuluyor..." -ForegroundColor Yellow
    $cfg = @{
        machine = $env:COMPUTERNAME
        state   = @{ manifest_local = "$SyncDir\.sync-manifest.json"; logfile = "$SyncDir\sync.log" }
        dirs    = @{
            kernel = @{ path = "$env:USERPROFILE\cumulusos\kernel"; pattern = "*.{c,h}"; max_kb = 1024 }
            pcb    = @{ path = "$env:USERPROFILE\pcb"; pattern = "*"; max_kb = 20480 }
            patent = @{ path = "$env:USERPROFILE\patent_docs"; pattern = "*"; max_kb = 10240 }
            scripts= @{ path = "$HermesDir\scripts"; pattern = "*"; max_kb = 1024 }
            hermes = @{ path = "$HermesDir\config.yaml"; pattern = "*"; max_kb = 1024 }
        }
    }
    $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $cfgPath -Encoding UTF8
    Write-Host "config.json hazır" -ForegroundColor Green
}

# 4. Task Scheduler görevi (her 90 dk)
Write-Host "Task Scheduler görevi oluşturuluyor: $TaskName" -ForegroundColor Yellow
$py = (Get-Command python -ErrorAction SilentlyContinue) ?? (Get-Command python3 -ErrorAction SilentlyContinue)
if (-not $py) {
    Write-Host "❌ python bulunamadı — https://python.org'dan kurun" -ForegroundColor Red
    exit 1
}
$action = New-ScheduledTaskAction -Execute $py.Source -Argument "$SyncDir\node_agent.py once"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 90)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Görev kayıtlı: $TaskName (her 90 dk)" -ForegroundColor Green

# 5. İlk koşu (doğrulama)
Write-Host "İlk koşu çalıştırılıyor..." -ForegroundColor Yellow
Push-Location $SyncDir
& python node_agent.py once
$rc = $LASTEXITCODE
Pop-Location
Write-Host ("İlk koşu rc=" + $rc) -ForegroundColor Green

Write-Host ""
Write-Host "=== KURULUM TAMAM ===" -ForegroundColor Cyan
Write-Host "Görev: $TaskName (Task Scheduler'da)"
Write-Host "Sonraki adım: rclone config ile GDrive bağla (gdrive: remote adı)"
Write-Host "  rclone config → new remote → ad: gdrive → Google Drive → client_id boş → token"
