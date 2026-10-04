"""Arranque: python -m localmedia [--data DIR]"""
import argparse
import logging
import os
import threading
import time

from . import __version__
from .alexa import AlexaSkill
from .amazon import Amazon
from .config import Config
from .db import DB
from .library import Library
from .tunnel import TunnelWatcher
from .web import make_lan_app, make_public_app

log = logging.getLogger("localmedia")


def serve(app, host, port, name):
    try:
        from waitress import serve as wserve
        log.info("%s escuchando en http://%s:%s", name, host, port)
        wserve(app, host=host, port=port, threads=12, channel_timeout=600,
               ident="Local Media", clear_untrusted_proxy_headers=True)
    except ImportError:
        log.warning("waitress no instalado; usando el servidor de desarrollo de Flask")
        app.run(host=host, port=port, threaded=True, use_reloader=False)


def rescan_loop(cfg, lib):
    time.sleep(5)
    last = time.time()
    while True:
        time.sleep(30)
        mins = int(cfg["rescan_minutes"] or 0)
        if mins > 0 and time.time() - last >= mins * 60:
            last = time.time()
            lib.start_scan(False)


def main():
    ap = argparse.ArgumentParser(description="Local Media - musica local para Alexa")
    ap.add_argument("--data", default=os.environ.get("LOCALMEDIA_DATA",
                                                     os.path.expanduser("~/.localmedia")),
                    help="directorio de datos (config, base de datos, caratulas)")
    ap.add_argument("--music", action="append", help="añadir carpeta de musica")
    ap.add_argument("--public-url", help="URL https publica (para Alexa)")
    ap.add_argument("--no-verify", action="store_true",
                    help="no comprobar la firma de Amazon (solo para pruebas)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("waitress.queue").setLevel(logging.ERROR)

    # datos de cuando el programa se llamaba PiMedia
    old = os.path.expanduser("~/.pimedia")
    if args.data == os.path.expanduser("~/.localmedia") and not os.path.exists(args.data) \
            and os.path.isdir(old):
        os.rename(old, args.data)
        log.info("Datos de PiMedia trasladados a %s", args.data)

    cfg = Config(args.data)
    changes = {}
    if args.music:
        changes["music_folders"] = list(dict.fromkeys(cfg["music_folders"] + args.music))
    if args.public_url:
        changes["public_url"] = args.public_url
    if args.no_verify:
        changes["verify_signatures"] = False
    if changes:
        cfg.update(changes)

    db = DB(os.path.join(args.data, "library.db"))
    lib = Library(cfg, db)
    skill = AlexaSkill(cfg, lib, db)
    amazon = Amazon(cfg, lib)
    lib.on_scan_done = amazon.auto_update_after_scan
    tunnel = TunnelWatcher(cfg, amazon)
    tunnel.start()
    log.info("Local Media %s - datos en %s", __version__, args.data)
    from .alexa_verify import HAVE_CRYPTO
    if cfg["verify_signatures"] and not HAVE_CRYPTO:
        log.warning("Falta el paquete 'cryptography': Alexa no podra conectarse mientras la "
                    "comprobacion de firma este activada. Instalalo con "
                    ".venv/bin/pip install cryptography o desactivala en Ajustes.")

    if cfg["music_folders"] or cfg["upnp_enabled"]:
        lib.start_scan(False)
    threading.Thread(target=rescan_loop, args=(cfg, lib), daemon=True).start()

    pub = make_public_app(cfg, lib, skill, amazon)
    lan = make_lan_app(cfg, lib, skill, amazon)
    threading.Thread(target=serve, args=(pub, cfg["public_bind"], int(cfg["public_port"]),
                                         "Puerto publico (Alexa)"), daemon=True).start()
    serve(lan, cfg["lan_bind"], int(cfg["lan_port"]), "Web de gestion")


if __name__ == "__main__":
    main()
