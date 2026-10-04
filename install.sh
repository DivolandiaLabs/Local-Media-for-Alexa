#!/usr/bin/env bash
# Instalador de Local Media para Raspberry Pi OS / Debian / Ubuntu (ARM64, ARMHF o x86_64).
#   ./install.sh                 instala y arranca el servicio
#   ./install.sh --cloudflare    ademas deja un tunel rapido de Cloudflare como servicio
#                                (gratis, sin dominio ni limite de datos; recomendado)
#   ./install.sh --tunnel        instala cloudflared para un tunel con dominio propio
#   ./install.sh --music /media/usb/Musica
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
DATA_DIR="$RUN_HOME/.localmedia"
WANT_TUNNEL=0
WANT_QUICK=0
MUSIC=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tunnel) WANT_TUNNEL=1 ;;
    --cloudflare) WANT_QUICK=1 ;;
    --music) MUSIC+=("$2"); shift ;;
    --data) DATA_DIR="$2"; shift ;;
    *) echo "Opcion desconocida: $1"; exit 1 ;;
  esac
  shift
done

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"

. /etc/os-release 2>/dev/null || true
if [[ "${VERSION_CODENAME:-}" == "buster" || "${VERSION_CODENAME:-}" == "bullseye" ]]; then
  printf '\n\033[1;33m!! Tu sistema es Raspberry Pi OS / Debian "%s", que ya no recibe soporte.\n' "$VERSION_CODENAME"
  printf '   Local Media funciona igual; si apt falla mira "Raspberry Pi OS antiguo" en el README.\033[0m\n'
fi

say "Instalando dependencias del sistema (python3, ffmpeg)"
$SUDO apt-get update || echo "  (apt-get update ha dado errores; sigo con lo que haya)"
# Solo se instala lo que falta: asi no se intenta actualizar paquetes ya instalados
# (en sistemas sin soporte esas actualizaciones dan 404 y paraban la instalacion).
missing() { for p in "$@"; do dpkg -s "$p" >/dev/null 2>&1 || echo "$p"; done; }
NEED=$(missing python3 python3-venv python3-pip)
if [[ -n "$NEED" ]]; then
  $SUDO apt-get install -y --no-upgrade --fix-missing $NEED || {
    echo "ERROR: no se pudo instalar: $NEED"
    echo "Mira la seccion 'Raspberry Pi OS antiguo' del README."; exit 1; }
fi
NEED=$(missing ffmpeg ca-certificates curl)
if [[ -n "$NEED" ]]; then
  $SUDO apt-get install -y --no-upgrade --fix-missing $NEED || \
    printf '\n\033[1;33m!! No se pudo instalar: %s. Sin ffmpeg, FLAC/WMA/OGG no sonaran en Alexa.\033[0m\n' "$NEED"
fi

say "Creando entorno de Python en $APP_DIR/.venv"
sudo -u "$RUN_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
# piwheels (Raspberry Pi OS) trae ruedas ARM precompiladas: no hace falta compilar nada
sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install --prefer-binary -r "$APP_DIR/requirements.txt"
# Opcionales: si alguno no tiene rueda para tu sistema, se sigue sin el
for pkg in "cryptography>=40" certifi pillow; do
  sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install -q --prefer-binary "$pkg" || \
    printf '\033[1;33m!! No se pudo instalar %s (opcional)\033[0m\n' "$pkg"
done

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

install_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then return; fi
  say "Instalando cloudflared"
  ARCH="$(dpkg --print-architecture)"   # arm64 | armhf | amd64
  TMP="$(mktemp -d)"
  curl -fsSL -o "$TMP/cloudflared.deb" \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
  $SUDO dpkg -i "$TMP/cloudflared.deb"
  rm -rf "$TMP"
}

if [[ $WANT_QUICK -eq 1 ]]; then
  install_cloudflared
  say "Creando el servicio 'cloudflared-localmedia' (tunel rapido de Cloudflare)"
  # Local Media lee la direccion del tunel en http://127.0.0.1:20241/quicktunnel y
  # actualiza la skill de Alexa cuando cambia (en cada reinicio de la Pi).
  CF_BIN="$(command -v cloudflared)"
  $SUDO tee /etc/systemd/system/cloudflared-localmedia.service >/dev/null <<EOF
[Unit]
Description=Tunel rapido de Cloudflare para Local Media
After=network-online.target localmedia.service
Wants=network-online.target

[Service]
User=$RUN_USER
ExecStart=$CF_BIN tunnel --no-autoupdate --metrics 127.0.0.1:20241 --url http://localhost:8765
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now cloudflared-localmedia
  # Alexa no acepta los dominios gratuitos de ngrok: si habia un tunel ngrok, se apaga
  if [[ -f /etc/systemd/system/ngrok-localmedia.service ]]; then
    $SUDO systemctl disable --now ngrok-localmedia || true
    echo "  (servicio ngrok-localmedia apagado: Alexa no acepta los dominios gratis de ngrok)"
  fi
  URL=""
  for _ in $(seq 1 15); do
    URL=$(curl -s --max-time 2 http://127.0.0.1:20241/quicktunnel \
          | grep -o '[a-z0-9-]*[.]trycloudflare[.]com' || true)
    [[ -n "$URL" ]] && break
    sleep 2
  done
  echo "  Direccion del tunel: https://${URL:-(todavia arrancando; mirala en la web)}"
  echo "  Local Media la detecta sola y, si estas conectado con Amazon, actualiza la skill."
fi

if [[ $WANT_TUNNEL -eq 1 ]]; then
  install_cloudflared
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
