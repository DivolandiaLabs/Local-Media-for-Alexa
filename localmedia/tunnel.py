"""Tunel rapido de Cloudflare (https://xxx.trycloudflare.com): gratis y sin limite de datos,
pero la direccion cambia cada vez que se reinicia cloudflared. Este vigilante la lee del
servidor de metricas de cloudflared y, si cambia, actualiza la URL publica y la skill.

Ademas comprueba cada 5 minutos que la direccion sigue funcionando desde Internet. A veces
el tunel se queda colgado: cloudflared sigue en marcha y da su direccion, pero Cloudflare
ya la ha borrado. Si falla varias veces seguidas (y nuestra conexion a Internet va bien),
se cierra cloudflared; su servicio (Restart=always) lo arranca de nuevo con otra direccion
y el vigilante se la pasa a Amazon como en cualquier cambio."""
import json
import logging
import os
import signal
import socket
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger("localmedia.tunnel")

HEALTH_EVERY = 300       # segundos entre comprobaciones de la direccion
HEALTH_GRACE = 180       # una direccion recien creada tarda un poco en existir
FAILS_TO_RESTART = 3     # fallos seguidos antes de reiniciar el tunel (~15 min)
RESTART_COOLDOWN = 900   # como mucho un reinicio cada 15 min


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


def tunnel_alive(url):
    """True si la direccion publica responde de verdad (pagina de privacidad de la skill)."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/privacidad", timeout=15) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        # 530/502/1033: Cloudflare no encuentra el tunel; otro codigo = llega hasta nosotros
        return e.code not in (502, 503, 504, 530)
    except (OSError, ValueError):
        return False     # nombre inexistente, sin respuesta...


def internet_ok():
    """Nuestra salida a Internet funciona (si no, el fallo no es culpa del tunel)."""
    for host in ("api.cloudflare.com", "www.google.com"):
        try:
            socket.create_connection((host, 443), timeout=5).close()
            return True
        except OSError:
            pass
    return False


def cloudflared_pids(metrics):
    """Procesos cloudflared de nuestro usuario que sirven este servidor de metricas."""
    port = (metrics or "").rstrip("/").rsplit(":", 1)[-1]
    out = []
    if not port.isdigit() or not os.path.isdir("/proc"):
        return out
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            if os.stat(f"/proc/{d}").st_uid != os.getuid():
                continue
            with open(f"/proc/{d}/cmdline", "rb") as f:
                args = f.read().split(b"\0")
        except OSError:
            continue
        if args and os.path.basename(args[0]) == b"cloudflared" and any(
                a.endswith(b":" + port.encode()) for a in args):
            out.append(int(d))
    return out


class TunnelWatcher:
    def __init__(self, cfg, amazon):
        self.cfg = cfg
        self.amazon = amazon
        self.current = None      # URL que da cloudflared ahora mismo
        self._last_try = 0.0
        self._seen = {}          # url -> momento en que aparecio
        self._last_health = 0.0
        self._fails = 0
        self._last_restart = 0.0

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
        self._seen.setdefault(url, time.time())
        if url != self.cfg.public_base():
            log.info("Nueva direccion del tunel: %s", url)
            self.cfg.update({"public_url": url})
        # se reintenta hasta que Amazon tenga la direccion buena (cada 5 min si falla)
        if (self.amazon.can_update_endpoint() and self.amazon.endpoint_url() != url
                and not self.amazon.job["running"]
                and time.time() - self._last_try > (300 if self.amazon.job["error"] else 0)):
            self._last_try = time.time()
            self.amazon.start_endpoint_update()
        self.health(url)

    def health(self, url):
        now = time.time()
        if now - self._last_health < HEALTH_EVERY or now - self._seen[url] < HEALTH_GRACE:
            return
        self._last_health = now
        if tunnel_alive(url):
            self._fails = 0
            return
        if not internet_ok():
            log.info("Sin Internet: no se comprueba el tunel")
            return
        self._fails += 1
        log.warning("El tunel %s no responde desde Internet (%d/%d)", url, self._fails,
                    FAILS_TO_RESTART)
        if self._fails >= FAILS_TO_RESTART and now - self._last_restart > RESTART_COOLDOWN:
            self.restart_tunnel()

    def restart_tunnel(self):
        pids = cloudflared_pids(self.cfg["quicktunnel_metrics"])
        if not pids:
            log.warning("Tunel colgado, pero no encuentro el proceso cloudflared para reiniciarlo")
            return
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        self._last_restart = time.time()
        self._fails = 0
        log.warning("Tunel colgado: cloudflared reiniciado (su servicio lo vuelve a arrancar "
                    "con una direccion nueva)")
