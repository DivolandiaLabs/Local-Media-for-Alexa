"""Tunel rapido de Cloudflare (https://xxx.trycloudflare.com): gratis y sin limite de datos,
pero la direccion cambia cada vez que se reinicia cloudflared. Este vigilante la lee del
servidor de metricas de cloudflared y, si cambia, actualiza la URL publica y la skill."""
import json
import logging
import threading
import time
import urllib.request

log = logging.getLogger("localmedia.tunnel")


def quick_tunnel_url(metrics):
    """https://xxx.trycloudflare.com o None si no hay tunel rapido en marcha."""
    if not metrics:
        return None
    try:
        with urllib.request.urlopen(metrics.rstrip("/") + "/quicktunnel", timeout=3) as r:
            host = (json.loads(r.read()) or {}).get("hostname")
    except (OSError, ValueError):
        return None
    return f"https://{host}" if host else None


class TunnelWatcher:
    def __init__(self, cfg, amazon):
        self.cfg = cfg
        self.amazon = amazon
        self.current = None      # URL que da cloudflared ahora mismo
        self._last_try = 0.0

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        time.sleep(8)
        while True:
            try:
                self.check()
            except Exception:
                log.exception("Vigilante del tunel")
            time.sleep(30)

    def check(self):
        url = quick_tunnel_url(self.cfg["quicktunnel_metrics"])
        self.current = url
        if not url:
            return
        if url != self.cfg.public_base():
            log.info("Nueva direccion del tunel: %s", url)
            self.cfg.update({"public_url": url})
        # se reintenta hasta que Amazon tenga la direccion buena (cada 5 min si falla)
        if (self.amazon.can_update_endpoint() and self.amazon.endpoint_url() != url
                and not self.amazon.job["running"]
                and time.time() - self._last_try > (300 if self.amazon.job["error"] else 0)):
            self._last_try = time.time()
            self.amazon.start_endpoint_update()
