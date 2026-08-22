# ============================================================
# Hermes Uzaktan Kurulum — Windows (H2) PowerShell betiği
# H2'de çalıştırılır: paketi indirir, Hermes + skill + config kurar
# Kullanım: powershell -ExecutionPolicy Bypass -File remote_hermes_setup.ps1
# ============================================================
param(
    [string]$Source = "http://100.92.2.47:9090",  # H1 9090
    [string]$Paket = ""  # boşsa en son paketi bulur
)

Write-Host "=== Hermes Uzaktan Kurulum (Windows) ===" -ForegroundColor Cyan

# 1. Paket listele (H1 9090'dan)
Write-Host "[1/5] H1'den paket aranıyor..."
$files = Invoke-RestMethod "$Source/"
if (-not $Paket) {
    $Paket = ($files -split "`n" | Where-Object { $_ -match "hermes_remote_paket_" } | Select-Object -Last 1).Trim()
}
if (-not $Paket) {
    Write-Host "Paket bulunamadı! H1'de: bash remote_hermes_setup.sh <IP> --windows" -ForegroundColor Red
    exit 1
}
Write-Host "    Paket: $Paket"

# 2. İndir
Write-Host "[2/5] Paket indiriliyor..."
$dest = "$env:TEMP\hermes_remote"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Invoke-WebRequest "$Source/$Paket" -OutFile "$dest\$Paket"
Write-Host "    OK: $dest\$Paket"

# 3. Aç
Write-Host "[3/5] Paket açılıyor..."
Expand-Archive "$dest\$Paket" -DestinationPath $dest -Force
Write-Host "    OK"

# 4. Kurulum
Write-Host "[4/5] Kurulum başlatılıyor..."
$setup = "$dest\remote_pkg\setup_remote.ps1"
if (Test-Path $setup) {
    powershell -ExecutionPolicy Bypass -File $setup
} else {
    # Linux setup betiği varsa — manuel adımları göster
    Write-Host "setup_remote.ps1 yok — Linux betiği gönderildi."
    Write-Host "Şu dosyalar hazır:"
    Get-ChildItem "$dest\remote_pkg" -Recurse | Select-Object -First 10 Name
}

Write-Host "[5/5] Tamam. Sonraki: .env anahtarları + tailscale + sync"
