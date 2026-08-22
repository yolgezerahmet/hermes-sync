#!/bin/bash
# ============================================================
# Hermes Uzaktan Kurulum + Senkron Betiği (H3/H2 için)
# H1'den uzak Hermes sunucusuna: Hermes + skill + config + veri kurar
# Kullanım: ./remote_hermes_setup.sh <HEDEF_IP> [--windows] [--hermes-only]
# ============================================================
set -euo pipefail

HEDEF="${1:-}"
MODE="${2:-}"
if [ -z "$HEDEF" ]; then
    echo "Kullanım: $0 <HEDEF_IP> [--windows] [--hermes-only]"
    echo "Örnek:   $0 100.96.0.1"
    echo "         $0 100.76.82.46 --windows"
    exit 1
fi

echo "=== Hermes Uzaktan Kurulum → $HEDEF $MODE ==="
PAKET="/tmp/hermes_remote_paket_$(date +%Y%m%d_%H%M%S).tar.gz"

# ─── 1. Kurulum paketi oluştur (H1'den) ───
echo "[1/5] Kurulum paketi hazırlanıyor..."
mkdir -p /tmp/remote_pkg/hermes-scripts
cp -r /root/.hermes/scripts/* /tmp/remote_pkg/hermes-scripts/ 2>/dev/null || true
# Config (anahtarsız — .env ayrı güvenli)
cp /root/.hermes/config.yaml /tmp/remote_pkg/config.yaml 2>/dev/null || true
# Sync motoru — symlink hariç (p2p/ dizini symlink içerir)
mkdir -p /tmp/remote_pkg/sync-motor
for f in /root/cumulus-sync-motor/*.py /root/cumulus-sync-motor/*.sh /root/cumulus-sync-motor/*.ps1 /root/cumulus-sync-motor/config.json; do
    [ -f "$f" ] && cp "$f" /tmp/remote_pkg/sync-motor/ 2>/dev/null || true
done
echo "    sync motor kodu kopyalandı ($(ls /tmp/remote_pkg/sync-motor | wc -l) dosya)"
# H3 planı
cp /root/H3_KURULUM_SENKRON_PLANI_20260824.md /tmp/remote_pkg/ 2>/dev/null || true
# Kurulum betiği
cat > /tmp/remote_pkg/setup_remote.sh << 'REMOTE'
#!/bin/bash
# Uzak makinede çalışır: Hermes + sync motor kurulumu
set -euo pipefail
echo "=== Uzak Hermes Kurulumu ==="

# Hermes Agent kur
if ! command -v hermes &>/dev/null; then
    echo "[*] Hermes kuruluyor..."
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
fi
hermes --version || true

# Config kopyala
mkdir -p ~/.hermes
if [ -f /tmp/remote_pkg/config.yaml ]; then
    cp /tmp/remote_pkg/config.yaml ~/.hermes/config.yaml
    echo "[*] config.yaml kopyalandı"
fi

# Script'ler
if [ -d /tmp/remote_pkg/hermes-scripts ]; then
    cp -r /tmp/remote_pkg/hermes-scripts/* ~/.hermes/scripts/ 2>/dev/null || true
    chmod +x ~/.hermes/scripts/*.py 2>/dev/null || true
    echo "[*] script'ler kopyalandı ($(ls /tmp/remote_pkg/hermes-scripts | wc -l) dosya)"
fi

# Sync motor
if [ -d /tmp/remote_pkg/sync-motor ]; then
    mkdir -p ~/cumulus-sync-motor
    cp -r /tmp/remote_pkg/sync-motor/* ~/cumulus-sync-motor/
    echo "[*] sync motor kopyalandı"
fi

echo "=== Kurulum tamam. Sonraki: .env anahtarları + tailscale + GDrive ==="
REMOTE
chmod +x /tmp/remote_pkg/setup_remote.sh

tar -czf "$PAKET" -C /tmp remote_pkg 2>/dev/null
echo "    Paket: $PAKET ($(du -h "$PAKET" | cut -f1))"

# ─── 2. Hedefe ilet ───
echo "[2/5] Paket hedefe iletiliyor..."
if [ "$MODE" == "--windows" ]; then
    # Windows: 9090 upload üzerinden (H2'de 9090 açıksa)
    cp "$PAKET" /tmp/hermes_uploads/
    echo "    → 9090'a kondu: http://$HEDEF:9090/$(basename $PAKET)"
    echo "    (H2'de indirip setup_remote.sh çalıştır — veya PowerShell uzak kurulum)"
else
    # Linux: SSH üzerinden
    scp -o ConnectTimeout=10 "$PAKET" root@"$HEDEF":/tmp/ 2>&1 | tail -2 || {
        echo "    ⚠ SSH başarısız — 9090'a koyuyorum:"
        cp "$PAKET" /tmp/hermes_uploads/
        echo "    → http://$HEDEF:9090/$(basename $PAKET)"
    }
fi

# ─── 3. Uzakta kurulum ───
echo "[3/5] Uzak kurulum başlatılıyor..."
if [ "$MODE" != "--windows" ]; then
    ssh -o ConnectTimeout=10 root@"$HEDEF" "cd /tmp && tar -xzf $(basename $PAKET) && bash /tmp/remote_pkg/setup_remote.sh" 2>&1 | tail -8 || {
        echo "    ⚠ SSH kurulum yapılamadı — paket 9090'da hazır, elle kurulacak"
    }
fi

echo "[4/5] Senkron hazırlığı..."
cat << EOF

=== SONRAKİ ADIMLAR (HEDEF'TE) ===
1. ~/.hermes/.env oluştur (H1'den anahtarlar — güvenli iletim)
2. tailscale up (H3 için)
3. cd ~/cumulus-sync-motor && python3 sync_motor.py both --skip-unchanged
4. python3 node_agent.py once
5. python3 sync_p2p.py p2p-pull patent h1
EOF

echo "[5/5] Tamam — $PAKET hazır."
