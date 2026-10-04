#!/usr/bin/env bash
# Quita el servicio de PiMedia. No borra tu musica ni ~/.pimedia (borralo a mano si quieres).
set -euo pipefail
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"
$SUDO systemctl disable --now pimedia 2>/dev/null || true
$SUDO rm -f /etc/systemd/system/pimedia.service
$SUDO systemctl daemon-reload
echo "Servicio eliminado. Tus datos siguen en ~/.pimedia y el programa en $(cd "$(dirname "$0")" && pwd)"
