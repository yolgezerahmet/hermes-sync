#!/usr/bin/env bash
# =============================================================
# hermes-mesh-kurulum.sh — Hermes Agent P2P peer kurulumu
# Üçgen mesh: her node kendi API anahtarını üretir, diğerlerine peer ekler.
#
# Kullanım:
#   ./hermes-mesh-kurulum.sh add-peer <NODE_ADI> <NODE_URL> <NODE_KEY>
#   ./hermes-mesh-kurulum.sh list
#   ./hermes-mesh-kurulum.sh dm <NODE_ADI> "<mesaj>"
#   ./hermes-mesh-kurulum.sh generate-key
#   ./hermes-mesh-kurulum.sh apiserver-open     # config.yaml host 0.0.0.0
#   ./hermes-mesh-kurulum.sh ufw-tailscale      # 8642 Tailscale-only
#
# Güvenlik ilkesi: her node'un API_SERVER_KEY'i BAĞIMSIZ olmalı.
# Hiçbir node'un anahtarı başka node'un API_SERVER_KEY'i olarak yazılmaz.
# =============================================================
set -euo pipefail

CONFIG="$HOME/.hermes/config.yaml"
CMD="${1:-help}"

case "$CMD" in
  generate-key)
    python3 -c "import secrets; print(secrets.token_hex(16))"
    ;;
  add-peer)
    NODE_NAME="${2:?NODE_ADI gerekli}"
    NODE_URL="${3:?NODE_URL gerekli}"
    NODE_KEY="${4:?NODE_KEY gerekli}"
    hermes peer add "$NODE_NAME" --url "$NODE_URL" --key "$NODE_KEY"
    echo "OK: $NODE_NAME kaydedildi ($NODE_URL)"
    ;;
  list)
    hermes peer list
    ;;
  dm)
    NODE_NAME="${2:?NODE_ADI gerekli}"
    MSG="${3:?Mesaj gerekli}"
    hermes peer dm "$NODE_NAME" "$MSG"
    ;;
  apiserver-open)
    python3 - <<'PY'
import yaml
p = "$CONFIG"
with open(p) as f: cfg = yaml.safe_load(f)
cfg.setdefault('api_server', {})['enabled'] = True
cfg['api_server']['host'] = '0.0.0.0'
cfg['api_server']['port'] = 8642
with open(p, 'w') as f: yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
print("OK: api_server host -> 0.0.0.0:8642")
PY
    ;;
  ufw-tailscale)
    ufw allow from 100.64.0.0/10 to any port 8642 proto tcp \
      comment "Hermes api_server Tailscale-only" 2>&1 | tail -1
    ;;
  *)
    echo "Kullanım: $0 {generate-key|add-peer NODE URL KEY|list|dm NODE MSG|apiserver-open|ufw-tailscale}"
    ;;
esac
