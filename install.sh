#!/usr/bin/env bash
# Instalador de Local Media para Raspberry Pi OS / Debian / Ubuntu (ARM64, ARMHF o x86_64).
#   ./install.sh                 instala y arranca el servicio
#   ./install.sh --tunnel        ademas instala cloudflared (Cloudflare Tunnel)
#   ./install.sh --music /media/usb/Musica
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
DATA_DIR="$RUN_HOME/.localmedia"
WANT_TUNNEL=0
MUSIC=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tunnel) WANT_TUNNEL=1 ;;
    --music) MUSIC+=("$2"); shift ;;
    --data) DATA_DIR="$2"; shift ;;
    *) echo "Opcion desconocida: $1"; exit 1 ;;
  esac
  shift
done

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"

say "Instalando dependencias del sistema (python3, ffmpeg)"
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq python3 python3-venv python3-pip ffmpeg ca-certificates curl \
  libjpeg-dev zlib1g-dev >/dev/null

say "Creando entorno de Python en $APP_DIR/.venv"
sudo -u "$RUN_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
# piwheels (Raspberry Pi OS) trae ruedas ARM precompiladas: no hace falta compilar nada
sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# Instalacion anterior con el nombre PiMedia: se para su servicio y se reutilizan sus datos
if systemctl list-unit-files pimedia.service >/dev/null 2>&1 && [[ -f /etc/systemd/system/pimedia.service ]]; then
  say "Quitando el servicio antiguo 'pimedia'"
  $SUDO systemctl disable --now pimedia || true
  $SUDO rm -f /etc/systemd/system/pimedia.service
fi
if [[ -d "$RUN_HOME/.pimedia" && ! -e "$DATA_DIR" ]]; then
  mv "$RUN_HOME/.pimedia" "$DATA_DIR"
fi

mkdir -p "$DATA_DIR"; chown "$RUN_USER" "$DATA_DIR"
if [[ ${#MUSIC[@]} -gt 0 ]]; then
  ARGS=(); for m in "${MUSIC[@]}"; do ARGS+=(--music "$m"); done
  # crea config.json con las carpetas y sale enseguida
  sudo -u "$RUN_USER" timeout 5 "$APP_DIR/.venv/bin/python" -m localmedia --data "$DATA_DIR" "${ARGS[@]}" >/dev/null 2>&1 || true
fi

say "Creando el servicio systemd 'localmedia'"
$SUDO tee /etc/systemd/system/localmedia.service >/dev/null <<EOF
[Unit]
Description=Local Media - musica local para Alexa
After=network-online.target local-fs.target remote-fs.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/.venv/bin/python -m localmedia --data $DATA_DIR
Restart=on-failure
RestartSec=5
Nice=5

[Install]
WantedBy=multi-user.target
EOF
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now localmedia

if [[ $WANT_TUNNEL -eq 1 ]]; then
  say "Instalando cloudflared"
  ARCH="$(dpkg --print-architecture)"   # arm64 | armhf | amd64
  TMP="$(mktemp -d)"
  curl -fsSL -o "$TMP/cloudflared.deb" \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
  $SUDO dpkg -i "$TMP/cloudflared.deb"
  rm -rf "$TMP"
  cat <<EOF

  cloudflared instalado. Para crear un tunel con TU dominio (gestionado en Cloudflare):
    cloudflared tunnel login
    cloudflared tunnel create localmedia
    cloudflared tunnel route dns localmedia musica.TU-DOMINIO.com
  y crea ~/.cloudflared/config.yml con:
    tunnel: localmedia
    credentials-file: $RUN_HOME/.cloudflared/<ID-DEL-TUNEL>.json
    ingress:
      - hostname: musica.TU-DOMINIO.com
        service: http://localhost:8765
      - service: http_status:404
  despues:  sudo cloudflared --config $RUN_HOME/.cloudflared/config.yml service install
EOF
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
say "¡Listo!"
cat <<EOF
  Web de gestion:   http://${IP:-localhost}:8080
  Puerto para Alexa: 8765 (exponlo por HTTPS; ver la guia "Configurar Alexa" en la web)

  Logs:       journalctl -u localmedia -f
  Reiniciar:  sudo systemctl restart localmedia
EOF
