"""Logica de la skill de Alexa: intents, cola por dispositivo y eventos del AudioPlayer."""
import json
import logging
import random
import secrets
import threading
import time

from .i18n import T
from .media import needs_transcode

log = logging.getLogger("localmedia.alexa")

DEFAULT_STATE = {"queue": [], "order": [], "pos": 0, "offset": 0, "shuffle": False,
                 "loop": False, "qid": "", "desc": "", "pending": False, "playing": False,
                 "fails": 0, "updated": 0}


class Devices:
    def __init__(self, db):
        self.db = db

    def get(self, device_id):
        r = self.db.one("SELECT * FROM devices WHERE device_id=?", (device_id,))
        st = dict(DEFAULT_STATE)
        if r and r["state"]:
            try:
                st.update(json.loads(r["state"]))
            except ValueError:
                pass
        return st

    def save(self, device_id, st, user_id=None):
        st["updated"] = time.time()
        self.db.x("INSERT INTO devices(device_id, name, user_id, last_seen, state) "
                  "VALUES(?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET "
                  "user_id=COALESCE(excluded.user_id, devices.user_id), "
                  "last_seen=excluded.last_seen, state=excluded.state",
                  (device_id, None, user_id, time.time(), json.dumps(st)))

    def list(self):
        out = []
        for r in self.db.q("SELECT device_id, name, last_seen, state FROM devices "
                           "ORDER BY last_seen DESC"):
            st = dict(DEFAULT_STATE)
            try:
                st.update(json.loads(r["state"] or "{}"))
            except ValueError:
                pass
            out.append({"id": r["device_id"], "name": r["name"], "last_seen": r["last_seen"],
                        "state": st})
        return out

    def rename(self, device_id, name):
        self.db.x("UPDATE devices SET name=? WHERE device_id=?", (name, device_id))

    def delete(self, device_id):
        self.db.x("DELETE FROM devices WHERE device_id=?", (device_id,))


# ---------------------------------------------------------------- utilidades de cola
def set_queue(st, ids, desc, shuffle, max_queue, first=None):
    """first: indice de la cancion que debe sonar primero (None = la primera, o una al
    azar si es aleatorio)."""
    ids = list(ids)
    if shuffle and len(ids) > max_queue:
        ids = random.sample(ids, max_queue)
        first = None
    if first is None:
        first = random.randrange(len(ids)) if (shuffle and ids) else 0
    ids = ids[:max_queue]
    st["queue"] = ids
    st["qid"] = secrets.token_hex(3)
    st["desc"] = desc
    st["shuffle"] = bool(shuffle)
    order = list(range(len(ids)))
    if shuffle:
        rest = [i for i in order if i != first]
        random.shuffle(rest)
        order = ([first] if ids else []) + rest
        st["pos"] = 0
    else:
        st["pos"] = min(first, max(0, len(ids) - 1))
    st["order"] = order
    st["offset"] = 0
    st["fails"] = 0


def track_at(st, pos):
    if 0 <= pos < len(st["order"]):
        return st["queue"][st["order"][pos]]
    return None


def make_token(st, pos, start_ms):
    return f"{st['qid']}:{pos}:{track_at(st, pos)}:{int(start_ms)}:{secrets.token_hex(2)}"


def parse_token(tok):
    try:
        qid, pos, tid, start, _ = (tok or "").split(":")
        return qid, int(pos), int(tid), int(start)
    except ValueError:
        return None


def locate(st, tok):
    """Posicion en la cola de la pista de este token (o None si es de otra cola)."""
    p = parse_token(tok)
    if not p or p[0] != st["qid"]:
        return None
    qid, pos, tid, _ = p
    if track_at(st, pos) == tid:
        return pos
    for i, idx in enumerate(st["order"]):
        if st["queue"][idx] == tid:
            return i
    return None


def next_pos(st, pos):
    n = len(st["order"])
    if n == 0:
        return None
    if pos + 1 < n:
        return pos + 1
    return 0 if st["loop"] else None


def prev_pos(st, pos):
    n = len(st["order"])
    if n == 0:
        return None
    if pos > 0:
        return pos - 1
    return n - 1 if st["loop"] else 0


# ---------------------------------------------------------------- respuesta
def response(speech=None, reprompt=None, directives=None, end=True, card=None):
    r = {}
    if speech:
        r["outputSpeech"] = {"type": "PlainText", "text": speech}
    if reprompt:
        r["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": reprompt}}
    if card:
        r["card"] = {"type": "Simple", "title": card[0], "content": card[1]}
    if directives:
        r["directives"] = directives
    if end is not None:
        r["shouldEndSession"] = end
    return {"version": "1.0", "response": r}


EMPTY = {"version": "1.0", "response": {}}
STOP = {"type": "AudioPlayer.Stop"}


class AlexaSkill:
    def __init__(self, cfg, lib, db):
        self.cfg = cfg
        self.lib = lib
        self.devices = Devices(db)
        self.lock = threading.RLock()
        self.last_requests = []  # para la pagina de diagnostico

    # -------------------------------------------------------------- entrada
    def handle(self, body):
        req = body.get("request", {})
        ctx = body.get("context", {})
        system = ctx.get("System", {})
        device_id = system.get("device", {}).get("deviceId", "desconocido")
        user_id = system.get("user", {}).get("userId")
        rtype = req.get("type", "")
        name = req.get("intent", {}).get("name") if rtype == "IntentRequest" else None
        self.last_requests = ([{"t": time.time(), "type": rtype, "intent": name,
                                "device": device_id[-12:]}] + self.last_requests)[:30]
        log.info("Alexa %s %s", rtype, name or "")
        t = T(req.get("locale") or "es-ES")
        with self.lock:
            st = self.devices.get(device_id)
            c = Ctx(self, st, t, req, ctx.get("AudioPlayer", {}), body.get("session"))
            try:
                if rtype == "LaunchRequest":
                    out = c.launch()
                elif rtype == "IntentRequest":
                    out = c.intent(req["intent"])
                elif rtype.startswith("AudioPlayer."):
                    out = c.audio_event(rtype.split(".", 1)[1])
                elif rtype.startswith("PlaybackController."):
                    out = c.controller(rtype.split(".", 1)[1])
                elif rtype == "System.ExceptionEncountered":
                    log.warning("Alexa informa de un error: %s", req.get("error"))
                    out = EMPTY
                else:
                    out = EMPTY
            finally:
                self.devices.save(device_id, st, user_id)
        return out

    def app_id(self, body):
        return (body.get("context", {}).get("System", {}).get("application", {})
                .get("applicationId") or
                body.get("session", {}).get("application", {}).get("applicationId"))

    # -------------------------------------------------------------- directiva Play
    def play_directive(self, st, pos, offset_ms=0, behavior="REPLACE_ALL", expected=None):
        tid = track_at(st, pos)
        tr = self.lib.track(tid) if tid is not None else None
        if tr is None:
            return None
        base = self.cfg.public_base()
        secret = self.cfg["secret"]
        trans = needs_transcode(tr, self.cfg)
        start_ms = 0
        if trans:
            ext = "mp3"
            url = f"{base}/s/{secret}/{tid}.mp3"
            if offset_ms > 1000:
                start_ms = offset_ms
                url += f"?start={offset_ms / 1000:.1f}"
            offset_ms = 0
        else:
            ext = tr["ext"].lstrip(".")
            url = f"{base}/s/{secret}/{tid}.{ext}"
        stream = {"url": url, "token": make_token(st, pos, start_ms),
                  "offsetInMilliseconds": int(offset_ms)}
        if expected and behavior == "ENQUEUE":
            stream["expectedPreviousToken"] = expected
        sub = " — ".join(x for x in (tr["artist"] or tr["album_artist"], tr["album"]) if x)
        meta = {"title": tr["title"] or "", "subtitle": sub}
        has_art = bool(tr.get("art_url")) if tr["source"] == "upnp" else \
            self.lib.art_for(tr) is not None
        if has_art:
            art = {"sources": [{"url": f"{base}/a/{secret}/{tid}.jpg"}]}
            meta["art"] = art
            meta["backgroundImage"] = art
        return {"type": "AudioPlayer.Play", "playBehavior": behavior,
                "audioItem": {"stream": stream, "metadata": meta}}


class Ctx:
    """Una peticion concreta."""

    def __init__(self, skill, st, t, req, audio, session):
        self.s = skill
        self.lib = skill.lib
        self.cfg = skill.cfg
        self.st = st
        self.t = t
        self.req = req
        self.audio = audio or {}
        self.session = session

    # -------------------------------------------------------------- ayudas
    def _sync_from_context(self):
        """Actualiza pos/offset con lo que el Echo dice que estaba sonando."""
        tok = self.audio.get("token")
        pos = locate(self.st, tok)
        if pos is not None:
            self.st["pos"] = pos
            p = parse_token(tok)
            self.st["offset"] = int(self.audio.get("offsetInMilliseconds") or 0) + p[3]
        return pos

    def _start(self, tracks, speech, shuffle=False, first=None):
        ids = [x["id"] if isinstance(x, dict) else x for x in tracks]
        if not ids:
            return None
        set_queue(self.st, ids, speech, shuffle, int(self.cfg["max_queue"]), first)
        self.st["pending"] = False
        d = self.s.play_directive(self.st, self.st["pos"])
        if d is None:
            return response(self.t("not_understood"), end=True)
        return response(speech, directives=[d], end=True)

    def _not_found(self, kind, q):
        what = self.t("kind_" + kind, q=q or "")
        return response(self.t("not_found", what=what), self.t("welcome_reprompt"), end=False)

    @staticmethod
    def _slot(intent, name, resolved=True):
        s = (intent.get("slots") or {}).get(name) or {}
        if resolved:
            for auth in (s.get("resolutions") or {}).get("resolutionsPerAuthority", []):
                if auth.get("status", {}).get("code") == "ER_SUCCESS_MATCH" and auth.get("values"):
                    v = auth["values"][0]["value"]
                    return v.get("name") or s.get("value")
        return s.get("value")

    @staticmethod
    def _slot_id(intent, name):
        s = (intent.get("slots") or {}).get(name) or {}
        for auth in (s.get("resolutions") or {}).get("resolutionsPerAuthority", []):
            if auth.get("status", {}).get("code") == "ER_SUCCESS_MATCH" and auth.get("values"):
                return auth["values"][0]["value"].get("id")
        return None

    def _current_track(self):
        tok = self.audio.get("token")
        if self.audio.get("playerActivity") in ("PLAYING", "PAUSED", "STOPPED",
                                               "BUFFER_UNDERRUN"):
            pos = locate(self.st, tok)
            if pos is not None:
                return self.lib.track(track_at(self.st, pos))
        if self.st["playing"]:
            tid = track_at(self.st, self.st["pos"])
            return self.lib.track(tid) if tid else None
        return None

    # -------------------------------------------------------------- tipos de peticion
    def launch(self):
        if self.st["pending"] and self.st["queue"]:
            self.st["pending"] = False
            d = self.s.play_directive(self.st, self.st["pos"], 0)
            if d:
                return response(self.t("welcome_queue", desc=self.st["desc"]), directives=[d])
        if self.lib.counts()["tracks"] == 0:
            return response(self.t("empty_library"), end=True)
        return response(self.t("welcome"), self.t("welcome_reprompt"), end=False)

    def intent(self, intent):
        name = intent.get("name", "")
        fn = getattr(self, "i_" + name.replace("AMAZON.", "amz_"), None)
        if fn is None:
            log.info("Intent sin manejar: %s", name)
            return response(self.t("fallback"), self.t("help_reprompt"), end=False)
        return fn(intent)

    # ---- busquedas
    def i_PlayArtistIntent(self, intent):
        q = self._slot(intent, "artist")
        if not q:
            return response(self.t("not_understood"), self.t("welcome_reprompt"), end=False)
        res = self.lib.find_artist(q)
        if not res:
            return self._not_found("artist", q)
        _, n, name = res[0]
        return self._start(self.lib.artist_tracks(n), self.t("playing_artist", name=name),
                           shuffle=bool(self.cfg["shuffle_artist"]))

    def i_PlayAlbumIntent(self, intent):
        q = self._slot(intent, "album")
        artist = self._slot(intent, "artist")
        if not q:
            return response(self.t("not_understood"), self.t("welcome_reprompt"), end=False)
        res = self.lib.find_album(q, artist)
        if not res:
            return self._not_found("album", q)
        a = res[0][1]
        tracks = self.lib.album_tracks(a["key"])
        art = tracks[0]["album_artist"] or tracks[0]["artist"] if tracks else ""
        by = self.t("by", artist=art) if art else ""
        return self._start(tracks, self.t("playing_album", name=a["name"], by=by))

    def i_PlaySongIntent(self, intent):
        q = self._slot(intent, "song")
        artist = self._slot(intent, "artist")
        if not q:
            return response(self.t("not_understood"), self.t("welcome_reprompt"), end=False)
        res = self.lib.find_song(q, artist)
        if not res:
            return self._not_found("song", q)
        tr = res[0][1]
        # despues de la cancion, mas del mismo artista
        more = [x for x in self.lib.artist_tracks(tr["n_artist"]) if x["id"] != tr["id"]] \
            if tr["n_artist"] else []
        random.shuffle(more)
        by = self.t("by", artist=tr["artist"]) if tr["artist"] else ""
        return self._start([tr] + more, self.t("playing_song", name=tr["title"], by=by))

    def i_PlayGenreIntent(self, intent):
        q = self._slot(intent, "genre")
        res = self.lib.find_genre(q) if q else []
        if not res:
            return self._not_found("genre", q)
        _, n, name = res[0]
        return self._start(self.lib.genre_tracks(n), self.t("playing_genre", name=name),
                           shuffle=True)

    SPECIAL_LISTS = {
        "favoritas": "fav", "favoritos": "fav", "favorites": "fav", "favourites": "fav",
        "mis favoritas": "fav", "mis favoritos": "fav", "my favorites": "fav",
        "mas escuchadas": "most", "most played": "most", "recientes": "recent",
        "recently added": "recent", "novedades": "recent",
    }

    def i_PlayPlaylistIntent(self, intent):
        q = self._slot(intent, "playlist")
        if not q:
            return response(self.t("not_understood"), self.t("welcome_reprompt"), end=False)
        res = self.lib.find_playlist(q)
        if res and res[0][0] >= 0.8:
            p = res[0][1]
            return self._start(self.lib.playlist_tracks(p["id"]),
                               self.t("playing_playlist", name=p["name"]))
        from .textnorm import norm
        special = self.SPECIAL_LISTS.get(norm(q))
        if special == "fav":
            return self.i_PlayFavoritesIntent(intent)
        if special == "most":
            return self.i_PlayMostPlayedIntent(intent)
        if special == "recent":
            return self.i_PlayRecentIntent(intent)
        if res:
            p = res[0][1]
            return self._start(self.lib.playlist_tracks(p["id"]),
                               self.t("playing_playlist", name=p["name"]))
        return self._not_found("playlist", q)

    def i_PlayFolderIntent(self, intent):
        q = self._slot(intent, "folder")
        res = self.lib.find_folder(q) if q else []
        if not res:
            return self._not_found("folder", q)
        import os
        path = res[0][1][0]
        return self._start(self.lib.folder_tracks(path),
                           self.t("playing_folder", name=os.path.basename(path)))

    def i_PlayYearIntent(self, intent):
        q = self._slot(intent, "year", resolved=False)
        try:
            y = int(q)
        except (TypeError, ValueError):
            return self._not_found("year", q)
        if y < 100:  # "el 92"
            y += 1900 if y > 30 else 2000
        return self._start(self.lib.year_tracks(y, y), self.t("playing_year", name=str(y)),
                           shuffle=True) or self._not_found("year", str(y))

    def i_PlayDecadeIntent(self, intent):
        d = self._slot_id(intent, "decade")
        raw = self._slot(intent, "decade", resolved=False)
        if not d and raw:
            from .textnorm import norm
            words = {"cincuenta": 1950, "sesenta": 1960, "setenta": 1970, "ochenta": 1980,
                     "noventa": 1990, "fifties": 1950, "sixties": 1960, "seventies": 1970,
                     "eighties": 1980, "nineties": 1990, "noughties": 2000}
            n = norm(raw).replace("anos ", "")
            d = next((y for w, y in words.items() if w in n), None)
            if d is None and ("dos mil" in n or "two thousand" in n):
                d = 2020 if "veinte" in n or "twent" in n else 2010 if "diez" in n or "ten" in n \
                    else 2000
            if d is None:
                digits = "".join(ch for ch in n if ch.isdigit())
                d = int(digits) if digits else None
        try:
            y = int(d)
        except (TypeError, ValueError):
            return self._not_found("year", raw)
        if y < 100:
            y += 1900 if y > 20 else 2000
        y -= y % 10
        label = self.t("decade", d=str(y)[2:] if self.t.lang == "en" else
                       {1950: "cincuenta", 1960: "sesenta", 1970: "setenta", 1980: "ochenta",
                        1990: "noventa", 2000: "dos mil", 2010: "dos mil diez",
                        2020: "dos mil veinte"}.get(y, str(y)))
        return self._start(self.lib.year_tracks(y, y + 9), self.t("playing_year", name=label),
                           shuffle=True) or self._not_found("year", label)

    def i_PlayAnythingIntent(self, intent):
        q = self._slot(intent, "query", resolved=False)
        if not q:
            return response(self.t("not_understood"), self.t("welcome_reprompt"), end=False)
        r = self.lib.resolve_any(q)
        if not r:
            return self._not_found("any", q)
        kind, name, tracks = r
        if kind == "song" and tracks:
            tr = tracks[0]
            more = [x for x in self.lib.artist_tracks(tr["n_artist"]) if x["id"] != tr["id"]] \
                if tr["n_artist"] else []
            random.shuffle(more)
            by = self.t("by", artist=tr["artist"]) if tr["artist"] else ""
            return self._start([tr] + more, self.t("playing_song", name=name, by=by))
        key = {"artist": "playing_artist", "album": "playing_album", "genre": "playing_genre",
               "playlist": "playing_playlist"}[kind]
        return self._start(tracks, self.t(key, name=name, by=""),
                           shuffle=(kind == "genre" or
                                    (kind == "artist" and bool(self.cfg["shuffle_artist"]))))

    def i_ShuffleAllIntent(self, intent):
        n = int(self.cfg["max_queue"])
        ids = self.lib.random_ids(n)
        if not ids:
            return response(self.t("empty_library"))
        return self._start(ids, self.t("playing_all"), shuffle=True)

    def i_PlayRecentIntent(self, intent):
        return self._start(self.lib.recent_tracks(), self.t("playing_recent")) or \
            response(self.t("empty_library"))

    def i_PlayFavoritesIntent(self, intent):
        return self._start(self.lib.favorite_tracks(), self.t("playing_favorites"),
                           shuffle=True) or response(self.t("no_favorites"))

    def i_PlayMostPlayedIntent(self, intent):
        return self._start(self.lib.most_played(), self.t("playing_most"), shuffle=True) or \
            response(self.t("no_plays"))

    def i_PlayMoreByArtistIntent(self, intent):
        tr = self._current_track()
        if not tr or not tr["n_artist"]:
            return response(self.t("nothing_playing"))
        return self._start(self.lib.artist_tracks(tr["n_artist"]),
                           self.t("playing_more_artist", name=tr["artist"]), shuffle=True)

    def i_PlayCurrentAlbumIntent(self, intent):
        tr = self._current_track()
        if not tr:
            return response(self.t("nothing_playing"))
        tracks = self.lib.album_tracks(tr["album_key"])
        first = next((i for i, x in enumerate(tracks) if x["id"] == tr["id"]), 0)
        return self._start(tracks, self.t("playing_current_album", name=tr["album"]),
                           first=first)

    def i_WhatIsPlayingIntent(self, intent):
        tr = self._current_track()
        if not tr:
            return response(self.t("nothing_playing"))
        by = self.t("by", artist=tr["artist"]) if tr["artist"] else ""
        album = self.t("np_album", album=tr["album"]) if tr["album"] else ""
        text = self.t("now_playing", title=tr["title"], by=by, album=album)
        return response(text, card=(tr["title"], f"{tr['artist']}\n{tr['album']}"))

    # ---- integrados de Amazon
    def i_amz_HelpIntent(self, intent):
        return response(self.t("help"), self.t("help_reprompt"), end=False)

    def i_amz_FallbackIntent(self, intent):
        return response(self.t("fallback"), self.t("help_reprompt"), end=False)

    def i_amz_NavigateHomeIntent(self, intent):
        return response(None, end=True)

    def _stop(self):
        self._sync_from_context()
        self.st["playing"] = False
        return response(None, directives=[STOP], end=True)

    def i_amz_PauseIntent(self, intent):
        return self._stop()

    def i_amz_StopIntent(self, intent):
        if self.audio.get("playerActivity") == "PLAYING" or self.session is None:
            return self._stop()
        return response(self.t("bye"), end=True)

    i_amz_CancelIntent = i_amz_StopIntent

    def i_amz_ResumeIntent(self, intent):
        if not self.st["queue"]:
            return response(self.t("nothing_to_resume"), self.t("welcome_reprompt"), end=False)
        self._sync_from_context()
        self.st["pending"] = False
        d = self.s.play_directive(self.st, self.st["pos"], self.st["offset"])
        return response(None, directives=[d] if d else None, end=True)

    def _jump(self, delta, speak=True):
        if not self.st["queue"]:
            return response(self.t("nothing_to_resume"), end=True) if speak else EMPTY
        cur = self._sync_from_context()
        cur = self.st["pos"] if cur is None else cur
        n = next_pos(self.st, cur) if delta > 0 else prev_pos(self.st, cur)
        if n is None:
            return response(self.t("end_of_queue"), end=True) if speak else EMPTY
        self.st["pos"], self.st["offset"] = n, 0
        d = self.s.play_directive(self.st, n)
        if speak:
            return response(None, directives=[d] if d else None, end=True)
        return {"version": "1.0", "response": {"directives": [d]}} if d else EMPTY

    def i_amz_NextIntent(self, intent):
        return self._jump(1)

    def i_amz_PreviousIntent(self, intent):
        return self._jump(-1)

    def i_amz_StartOverIntent(self, intent):
        if not self.st["queue"]:
            return response(self.t("nothing_to_resume"), end=True)
        self._sync_from_context()
        d = self.s.play_directive(self.st, self.st["pos"], 0)
        return response(None, directives=[d] if d else None, end=True)

    i_amz_RepeatIntent = i_amz_StartOverIntent

    def _reorder(self, shuffle):
        st = self.st
        self._sync_from_context()
        st["shuffle"] = shuffle
        if not st["queue"]:
            return
        cur_idx = st["order"][st["pos"]] if st["order"] else 0
        if shuffle:
            rest = [i for i in range(len(st["queue"])) if i != cur_idx]
            random.shuffle(rest)
            st["order"] = [cur_idx] + rest
            st["pos"] = 0
        else:
            st["order"] = list(range(len(st["queue"])))
            st["pos"] = cur_idx

    def _enqueue_next_after_change(self):
        """Tras cambiar el orden, sustituye lo que el Echo tenia en cola."""
        if self.audio.get("playerActivity") != "PLAYING":
            return None
        n = next_pos(self.st, self.st["pos"])
        if n is None:
            return None
        return self.s.play_directive(self.st, n, 0, behavior="REPLACE_ENQUEUED")

    def i_amz_ShuffleOnIntent(self, intent):
        self._reorder(True)
        d = self._enqueue_next_after_change()
        return response(self.t("shuffle_on"), directives=[d] if d else None, end=True)

    def i_amz_ShuffleOffIntent(self, intent):
        self._reorder(False)
        d = self._enqueue_next_after_change()
        return response(self.t("shuffle_off"), directives=[d] if d else None, end=True)

    def i_amz_LoopOnIntent(self, intent):
        self._sync_from_context()
        self.st["loop"] = True
        d = self._enqueue_next_after_change()
        return response(self.t("loop_on"), directives=[d] if d else None, end=True)

    def i_amz_LoopOffIntent(self, intent):
        self._sync_from_context()
        self.st["loop"] = False
        return response(self.t("loop_off"), end=True)

    # -------------------------------------------------------------- eventos del Echo
    def audio_event(self, ev):
        st, req = self.st, self.req
        tok = req.get("token")
        pos = locate(st, tok)
        if ev == "PlaybackStarted":
            if pos is not None:
                st["pos"], st["offset"], st["playing"], st["fails"] = pos, 0, True, 0
                tid = track_at(st, pos)
                if tid:
                    self.lib.record_play(tid)
            return EMPTY
        if ev == "PlaybackNearlyFinished":
            if pos is None:
                return EMPTY
            n = next_pos(st, pos)
            if n is None:
                return EMPTY
            d = self.s.play_directive(st, n, 0, behavior="ENQUEUE", expected=tok)
            return {"version": "1.0", "response": {"directives": [d]}} if d else EMPTY
        if ev == "PlaybackStopped":
            if pos is not None:
                st["pos"] = pos
                st["offset"] = int(req.get("offsetInMilliseconds") or 0) + parse_token(tok)[3]
            st["playing"] = False
            return EMPTY
        if ev == "PlaybackFinished":
            if pos is not None and next_pos(st, pos) is None:
                st["playing"] = False
                st["offset"] = 0
            return EMPTY
        if ev == "PlaybackFailed":
            log.warning("Fallo de reproduccion: %s", req.get("error"))
            tok = tok or (req.get("currentPlaybackState") or {}).get("token")
            pos = locate(st, tok)
            st["fails"] = st.get("fails", 0) + 1
            if pos is None or st["fails"] > 5:
                st["playing"] = False
                return EMPTY
            n = next_pos(st, pos)
            if n is None or n == pos:
                return EMPTY
            st["pos"] = n
            d = self.s.play_directive(st, n)
            return {"version": "1.0", "response": {"directives": [d]}} if d else EMPTY
        return EMPTY

    def controller(self, ev):
        """Botones fisicos / pantalla del Echo / app de Alexa."""
        if ev == "PlayCommandIssued":
            if not self.st["queue"]:
                return EMPTY
            self._sync_from_context()
            d = self.s.play_directive(self.st, self.st["pos"], self.st["offset"])
            return {"version": "1.0", "response": {"directives": [d]}} if d else EMPTY
        if ev == "PauseCommandIssued":
            self._sync_from_context()
            self.st["playing"] = False
            return {"version": "1.0", "response": {"directives": [STOP]}}
        if ev == "NextCommandIssued":
            return self._jump(1, speak=False)
        if ev == "PreviousCommandIssued":
            return self._jump(-1, speak=False)
        return EMPTY
