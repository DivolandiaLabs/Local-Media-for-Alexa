#!/usr/bin/env bash
# Quita el servicio de Local Media. No borra tu musica ni ~/.localmedia (borralo a mano si quieres).
set -euo pipefail
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"
$SUDO systemctl disable --now localmedia 2>/dev/null || true
$SUDO rm -f /etc/systemd/system/localmedia.service
$SUDO systemctl daemon-reload
echo "Servicio eliminado. Tus datos siguen en ~/.localmedia y el programa en $(cd "$(dirname "$0")" && pwd)"
