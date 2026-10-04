"""Arranque: python -m pimedia [--data DIR]"""
import argparse
import logging
import os
import threading
import time

from . import __version__
from .alexa import AlexaSkill
from .config import Config
from .db import DB
from .library import Library
from .web import make_lan_app, make_public_app

log = logging.getLogger("pimedia")


def serve(app, host, port, name):
    try:
        from waitress import serve as wserve
        log.info("%s escuchando en http://%s:%s", name, host, port)
        wserve(app, host=host, port=port, threads=12, channel_timeout=600,
               ident="PiMedia", clear_untrusted_proxy_headers=True)
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
    ap = argparse.ArgumentParser(description="PiMedia - musica local para Alexa")
    ap.add_argument("--data", default=os.environ.get("PIMEDIA_DATA",
                                                     os.path.expanduser("~/.pimedia")),
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
    log.info("PiMedia %s - datos en %s", __version__, args.data)

    if cfg["music_folders"] or cfg["upnp_enabled"]:
        lib.start_scan(False)
    threading.Thread(target=rescan_loop, args=(cfg, lib), daemon=True).start()

    pub = make_public_app(cfg, lib, skill)
    lan = make_lan_app(cfg, lib, skill)
    threading.Thread(target=serve, args=(pub, cfg["public_bind"], int(cfg["public_port"]),
                                         "Puerto publico (Alexa)"), daemon=True).start()
    serve(lan, cfg["lan_bind"], int(cfg["lan_port"]), "Web de gestion")


if __name__ == "__main__":
    main()
