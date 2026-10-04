"""Configuracion persistente de Local Media (JSON en el directorio de datos)."""
import json
import os
import secrets
import threading

DEFAULTS = {
    "music_folders": [],
    # Puerto de la web de gestion (solo red local).
    "lan_bind": "0.0.0.0",
    "lan_port": 8080,
    # Puerto publico: solo /alexa, /s/<secreto>/... y /a/<secreto>/...
    # Es el que se expone a Internet (Cloudflare Tunnel, ngrok, Caddy...).
    "public_bind": "0.0.0.0",
    "public_port": 8765,
    "public_url": "",            # p. ej. https://musica.midominio.com
    "skill_ids": [],             # amzn1.ask.skill.xxx (vacio = aceptar cualquiera)
    "verify_signatures": True,   # firma de Amazon en /alexa
    "transcode": "auto",         # auto | always | never
    "transcode_bitrate": 192,
    "ffmpeg": "ffmpeg",
    "rescan_minutes": 60,        # 0 = sin reescaneo automatico
    "web_password": "",
    "secret": "",
    "upnp_enabled": False,
    "upnp_servers": [],          # [{location, name, enabled}]
    "max_queue": 1000,
    "shuffle_artist": False,     # al pedir un artista, mezclar sus canciones
    # Conectar con Amazon (perfil de seguridad de Login with Amazon del usuario)
    "lwa_client_id": "",
    "lwa_client_secret": "",
    "amazon": {},                # tokens, vendor_id, skill_id (nunca se envia a la web)
    "skill_locales": ["es-ES"],
    "amazon_auto_model": True,   # subir el modelo de voz tras cada escaneo si cambia
}
PRIVATE = ("secret", "amazon")


class Config:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "config.json")
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        if not self.data.get("secret"):
            self.data["secret"] = secrets.token_urlsafe(24)
        self.save()

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def get(self, key, default=None):
        return self.data.get(key, default)

    def update(self, values):
        with self._lock:
            for k, v in values.items():
                if k in DEFAULTS and k != "secret":
                    self.data[k] = v
        self.save()

    def save(self):
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)  # lleva tokens de Amazon
            except OSError:
                pass

    def public_base(self):
        return (self["public_url"] or "").rstrip("/")

    def public_view(self):
        """Config para la web (sin secretos)."""
        d = {k: v for k, v in self.data.items() if k not in PRIVATE}
        for k in ("web_password", "lwa_client_secret"):
            d[k] = "********" if self.data.get(k) else ""
        return d
