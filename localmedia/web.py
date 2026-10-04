"""Dos aplicaciones Flask:
 - public_app: lo unico que se expone a Internet (Alexa + audio + caratulas con secreto).
 - lan_app: web de gestion y reproductor (solo red local, con contraseña opcional).
"""
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.request

from flask import Flask, Response, abort, jsonify, request, send_from_directory, session

from . import media, skillmodel, upnp
from .alexa_verify import VerifyError, verify

log = logging.getLogger("localmedia.web")
STATIC = os.path.join(os.path.dirname(__file__), "static")


def _pw_tag(pw):
    return hashlib.sha256(("localmedia:" + pw).encode()).hexdigest()[:24]


def _art_response(lib, tid):
    tr = lib.track(tid)
    art = lib.art_for(tr) if tr else None
    if not art:
        return send_from_directory(STATIC, "cover.svg", max_age=3600)
    return Response(art[0], mimetype=art[1], headers={"Cache-Control": "public, max-age=86400"})


# ======================================================================= publica
def make_public_app(cfg, lib, skill):
    app = Flask("localmedia_public")

    @app.get("/")
    def health():
        return "Local Media OK"

    @app.post("/alexa")
    def alexa():
        raw = request.get_data()
        try:
            body = json.loads(raw)
        except ValueError:
            abort(400)
        if cfg["verify_signatures"]:
            try:
                verify(request.headers, raw, body.get("request", {}).get("timestamp", ""))
            except VerifyError as e:
                log.warning("Peticion rechazada: %s", e)
                abort(400)
        ids = [i for i in (cfg["skill_ids"] or []) if i]
        if ids and skill.app_id(body) not in ids:
            log.warning("applicationId no autorizado: %s", skill.app_id(body))
            abort(403)
        try:
            out = skill.handle(body)
        except Exception:
            log.exception("Error atendiendo a Alexa")
            out = {"version": "1.0", "response": {
                "outputSpeech": {"type": "PlainText", "text": "Ha ocurrido un error en Local Media."},
                "shouldEndSession": True}}
        return jsonify(out)

    @app.route("/s/<secret>/<int:tid>.<ext>", methods=["GET", "HEAD"])
    def stream(secret, tid, ext):
        if not hmac.compare_digest(secret, cfg["secret"]):
            abort(404)
        tr = lib.track(tid)
        if tr is None:
            abort(404)
        trans = True if ext == "mp3" and tr["ext"] != ".mp3" else None
        return media.stream(tr, cfg, media.parse_start(request.args.get("start")), trans)

    @app.get("/a/<secret>/<int:tid>.jpg")
    def art(secret, tid):
        if not hmac.compare_digest(secret, cfg["secret"]):
            abort(404)
        return _art_response(lib, tid)

    return app


# ======================================================================= red local
def make_lan_app(cfg, lib, skill):
    app = Flask("localmedia_lan", static_folder=None)
    app.secret_key = ("localmedia-" + cfg["secret"]).encode()
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.json.ensure_ascii = False

    @app.before_request
    def auth():
        pw = cfg["web_password"]
        if not pw:
            return None
        if request.path in ("/", "/api/login", "/api/auth") or request.path.startswith("/static/"):
            return None
        if session.get("ok") != _pw_tag(pw):
            return jsonify(error="auth"), 401

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html", max_age=0)

    @app.get("/static/<path:p>")
    def static_files(p):
        return send_from_directory(STATIC, p, max_age=0)

    @app.get("/api/auth")
    def auth_state():
        pw = cfg["web_password"]
        return jsonify(required=bool(pw), ok=(not pw) or session.get("ok") == _pw_tag(pw))

    @app.post("/api/login")
    def login():
        pw = cfg["web_password"]
        given = (request.json or {}).get("password", "")
        if pw and hmac.compare_digest(given, pw):
            session["ok"] = _pw_tag(pw)
            session.permanent = True
            return jsonify(ok=True)
        time.sleep(1)
        return jsonify(ok=False), 401

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    # ------------------------------------------------------------ estado y ajustes
    @app.get("/api/status")
    def status():
        c = lib.counts()
        base = cfg.public_base()
        return jsonify(
            counts=c, scan=lib.status, last_scan=float(lib.db.meta_get("last_scan", 0) or 0),
            public_url=base, alexa_endpoint=(base + "/alexa") if base else "",
            devices=len(skill.devices.list()), recent_requests=skill.last_requests[:15],
            ffmpeg=_has_ffmpeg(cfg), mutagen=lib_has_mutagen(),
            crypto=_has_crypto(), version=__import__("localmedia").__version__)

    @app.get("/api/config")
    def get_config():
        return jsonify(cfg.public_view())

    @app.post("/api/config")
    def set_config():
        data = dict(request.json or {})
        if data.get("web_password") == "********":
            data.pop("web_password")
        if "music_folders" in data:
            data["music_folders"] = [f.strip() for f in data["music_folders"] if f.strip()]
        if "skill_ids" in data:
            data["skill_ids"] = [s.strip() for s in data["skill_ids"] if s.strip()]
        for k in ("lan_port", "public_port", "transcode_bitrate", "rescan_minutes", "max_queue"):
            if k in data:
                data[k] = int(data[k])
        old_pw = cfg["web_password"]
        cfg.update(data)
        if cfg["web_password"] and cfg["web_password"] != old_pw:
            pw = cfg["web_password"]
            session["ok"] = _pw_tag(pw)
        return jsonify(cfg.public_view())

    @app.get("/api/browse-dirs")
    def browse_dirs():
        """Explorador de carpetas del sistema para elegir carpetas de musica."""
        path = request.args.get("path") or os.path.expanduser("~")
        path = os.path.abspath(path)
        try:
            entries = sorted(e.name for e in os.scandir(path)
                             if e.is_dir() and not e.name.startswith("."))
        except OSError as e:
            return jsonify(path=path, parent=os.path.dirname(path), dirs=[], error=str(e))
        shortcuts = [p for p in ("/media", "/mnt", "/srv", os.path.expanduser("~/Music"),
                                 os.path.expanduser("~/Música")) if os.path.isdir(p)]
        return jsonify(path=path, parent=os.path.dirname(path), dirs=entries,
                       shortcuts=shortcuts)

    @app.post("/api/scan")
    def scan():
        full = bool((request.json or {}).get("full"))
        return jsonify(started=lib.start_scan(full), scan=lib.status)

    @app.get("/api/test-public")
    def test_public():
        base = cfg.public_base()
        if not base:
            return jsonify(ok=False, msg="No has puesto la URL pública.")
        if not base.startswith("https://"):
            return jsonify(ok=False, msg="La URL pública debe empezar por https://")
        try:
            with urllib.request.urlopen(base + "/", timeout=10) as r:
                txt = r.read(200).decode(errors="ignore")
            ok = "Local Media OK" in txt
            return jsonify(ok=ok, msg="Accesible desde Internet." if ok else
                           f"Responde, pero no es Local Media: {txt[:80]}")
        except Exception as e:
            return jsonify(ok=False, msg=f"No se puede acceder: {e}")

    # ------------------------------------------------------------ biblioteca
    @app.get("/api/artists")
    def artists():
        return jsonify(lib.artists())

    @app.get("/api/albums")
    def albums():
        return jsonify(lib.albums(request.args.get("artist"), request.args.get("genre"),
                                  request.args.get("order", "name")))

    @app.get("/api/album")
    def album():
        return jsonify(lib.album_tracks(request.args["key"]))

    @app.get("/api/artist")
    def artist():
        n = request.args["n"]
        return jsonify(tracks=lib.artist_tracks(n), albums=lib.albums(n_artist=n))

    @app.get("/api/genres")
    def genres():
        return jsonify(lib.genres())

    @app.get("/api/genre")
    def genre():
        n = request.args["n"]
        return jsonify(tracks=lib.genre_tracks(n), albums=lib.albums(n_genre=n))

    @app.get("/api/tracks")
    def tracks():
        total, rows = lib.all_tracks(request.args.get("order", "title"),
                                     int(request.args.get("offset", 0)),
                                     min(500, int(request.args.get("limit", 200))),
                                     request.args.get("q"))
        return jsonify(total=total, tracks=rows)

    @app.get("/api/folders")
    def folders():
        return jsonify(lib.folder_listing(request.args.get("path")))

    @app.get("/api/folder-tracks")
    def folder_tracks():
        return jsonify(lib.folder_tracks(request.args["path"]))

    @app.get("/api/recent")
    def recent():
        return jsonify(albums=lib.albums(order="recent")[:60],
                       played=lib.recently_played(50), most=lib.most_played(50))

    @app.get("/api/search")
    def search():
        q = request.args.get("q", "").strip()
        return jsonify(lib.search(q) if q else {})

    @app.get("/api/favorites")
    def favorites():
        return jsonify(lib.favorite_tracks())

    @app.get("/api/favorite-ids")
    def favorite_ids():
        return jsonify([r["track_id"] for r in lib.db.q("SELECT track_id FROM favorites")])

    @app.post("/api/favorites/<int:tid>")
    def favorite(tid):
        on = bool((request.json or {}).get("on", True))
        lib.set_favorite(tid, on)
        return jsonify(ok=True, on=on)

    # listas
    @app.get("/api/playlists")
    def playlists():
        return jsonify(lib.playlists())

    @app.post("/api/playlists")
    def create_playlist():
        d = request.json or {}
        pid = lib.create_playlist(d.get("name") or "Nueva lista", d.get("track_ids") or [])
        return jsonify(id=pid)

    @app.get("/api/playlists/<int:pid>")
    def get_playlist(pid):
        p = lib.playlist(pid)
        if not p:
            abort(404)
        return jsonify(playlist=p, tracks=lib.playlist_tracks(pid))

    @app.post("/api/playlists/<int:pid>/add")
    def add_playlist(pid):
        lib.add_to_playlist(pid, (request.json or {}).get("track_ids") or [])
        return jsonify(ok=True)

    @app.put("/api/playlists/<int:pid>")
    def update_playlist(pid):
        d = request.json or {}
        if "name" in d:
            lib.rename_playlist(pid, d["name"])
        if "track_ids" in d:
            lib.set_playlist_items(pid, d["track_ids"])
        return jsonify(ok=True)

    @app.delete("/api/playlists/<int:pid>")
    def delete_playlist(pid):
        lib.delete_playlist(pid)
        return jsonify(ok=True)

    @app.get("/api/playlists/<int:pid>/m3u")
    def export_m3u(pid):
        p = lib.playlist(pid)
        if not p:
            abort(404)
        lines = ["#EXTM3U"]
        for t in lib.playlist_tracks(pid):
            lines.append(f"#EXTINF:{int(t['duration'] or 0)},{t['artist']} - {t['title']}")
            lines.append(t["path"])
        return Response("\n".join(lines) + "\n", mimetype="audio/x-mpegurl", headers={
            "Content-Disposition": f'attachment; filename="{p["name"]}.m3u8"'})

    # audio para el reproductor web
    @app.route("/api/stream/<int:tid>", methods=["GET", "HEAD"])
    def lan_stream(tid):
        tr = lib.track(tid)
        if tr is None:
            abort(404)
        # el navegador reproduce FLAC/OGG/OPUS/WAV; solo convertimos lo que no
        browser_ok = {".mp3", ".m4a", ".m4b", ".aac", ".mp4", ".flac", ".ogg", ".oga",
                      ".opus", ".wav"}
        trans = tr["ext"] not in browser_ok or (tr.get("codec") or "").startswith("alac")
        return media.stream(tr, cfg, media.parse_start(request.args.get("start")), trans)

    @app.get("/api/art/<int:tid>")
    def lan_art(tid):
        return _art_response(lib, tid)

    # ------------------------------------------------------------ Alexa
    @app.get("/api/devices")
    def devices():
        out = []
        for d in skill.devices.list():
            st = d["state"]
            cur = None
            if st["queue"] and 0 <= st["pos"] < len(st["order"]):
                cur = lib.track(st["queue"][st["order"][st["pos"]]])
            out.append({"id": d["id"], "name": d["name"], "last_seen": d["last_seen"],
                        "playing": st["playing"], "shuffle": st["shuffle"], "loop": st["loop"],
                        "pending": st["pending"], "desc": st["desc"],
                        "queue_len": len(st["queue"]), "pos": st["pos"],
                        "current": cur})
        return jsonify(out)

    @app.put("/api/devices/<path:did>")
    def rename_device(did):
        skill.devices.rename(did, (request.json or {}).get("name", ""))
        return jsonify(ok=True)

    @app.delete("/api/devices/<path:did>")
    def delete_device(did):
        skill.devices.delete(did)
        return jsonify(ok=True)

    @app.get("/api/devices/<path:did>/queue")
    def device_queue(did):
        st = skill.devices.get(did)
        ids = [st["queue"][i] for i in st["order"]]
        return jsonify(pos=st["pos"], tracks=lib.tracks(ids[:1000]))

    @app.post("/api/devices/<path:did>/queue")
    def set_device_queue(did):
        """Prepara una cola en un Echo. Se reproduce al decir
        'Alexa, abre mi colección' (o 'Alexa, pide a mi colección que continúe')."""
        from .alexa import set_queue
        d = request.json or {}
        ids = [int(i) for i in d.get("track_ids") or []]
        if not ids:
            abort(400)
        with skill.lock:
            st = skill.devices.get(did)
            set_queue(st, ids, d.get("desc") or "", bool(d.get("shuffle")),
                      int(cfg["max_queue"]),
                      None if d.get("first") is None else int(d["first"]))
            st["pending"] = True
            st["playing"] = False
            skill.devices.save(did, st)
        return jsonify(ok=True)

    @app.get("/api/skill/model")
    def skill_model():
        locale = request.args.get("locale", "es-ES")
        names = lib.names_for_model() if request.args.get("library", "1") == "1" else None
        model = skillmodel.build(locale, names)
        return Response(json.dumps(model, ensure_ascii=False, indent=2),
                        mimetype="application/json", headers={
                            "Content-Disposition": f'attachment; filename="{locale}.json"'})

    @app.get("/api/skill/manifest")
    def skill_manifest():
        return Response(json.dumps(skillmodel.manifest(cfg.public_base()), ensure_ascii=False,
                                   indent=2), mimetype="application/json", headers={
            "Content-Disposition": 'attachment; filename="skill.json"'})

    # ------------------------------------------------------------ UPnP
    @app.get("/api/upnp/discover")
    def upnp_discover():
        try:
            return jsonify(upnp.discover())
        except Exception as e:
            return jsonify(error=str(e)), 500

    return app


def _has_ffmpeg(cfg):
    import shutil
    return bool(shutil.which(cfg["ffmpeg"]) or os.path.exists(cfg["ffmpeg"]))


def _has_crypto():
    from .alexa_verify import HAVE_CRYPTO
    return HAVE_CRYPTO


def lib_has_mutagen():
    from .library import mutagen
    return mutagen is not None
