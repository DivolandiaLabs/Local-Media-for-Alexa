"""Biblioteca musical: escaneo de carpetas, etiquetas, caratulas, listas y consultas."""
import hashlib
import logging
import os
import random
import re
import threading
import time
import urllib.parse

from .textnorm import norm, best

log = logging.getLogger("localmedia.library")

try:
    import mutagen
except ImportError:  # el escaneo sigue funcionando con nombres de archivo
    mutagen = None

AUDIO_EXT = {".mp3", ".m4a", ".m4b", ".aac", ".mp4", ".flac", ".ogg", ".oga", ".opus",
             ".wav", ".wma", ".aif", ".aiff", ".alac", ".ape", ".wv", ".mpc", ".dsf"}
PLAYLIST_EXT = {".m3u", ".m3u8", ".pls"}
COVER_NAMES = ("cover", "folder", "front", "album", "albumart", "albumartlarge",
               "artwork", "thumb", "albumartsmall")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def _first(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if v is None:
        return None
    return str(v).strip() or None


def _int(v):
    v = _first(v)
    if not v:
        return None
    m = re.match(r"\s*(\d+)", v)
    return int(m.group(1)) if m else None


def _year(v):
    v = _first(v)
    if not v:
        return None
    m = re.search(r"(1[89]\d\d|20\d\d)", v)
    return int(m.group(1)) if m else None


ASF_MAP = {"title": "Title", "artist": "Author", "album": "WM/AlbumTitle",
           "albumartist": "WM/AlbumArtist", "genre": "WM/Genre", "date": "WM/Year",
           "tracknumber": "WM/TrackNumber", "discnumber": "WM/PartOfSet"}


def read_tags(path):
    """Devuelve dict con title, artist, album_artist, album, genre, year, track_no,
    disc_no, duration, bitrate, codec."""
    out = {}
    if mutagen is None:
        return out
    try:
        f = mutagen.File(path, easy=True)
    except Exception as e:  # archivo roto
        log.debug("tags %s: %s", path, e)
        return out
    if f is None:
        return out
    info = getattr(f, "info", None)
    if info is not None:
        out["duration"] = float(getattr(info, "length", 0) or 0)
        br = getattr(info, "bitrate", 0) or 0
        out["bitrate"] = int(br / 1000) if br > 2000 else int(br)
        out["codec"] = str(getattr(info, "codec", "") or "").lower() or None
    tags = f.tags or {}
    is_asf = type(f).__name__ == "ASF"

    def g(key):
        try:
            if is_asf:
                v = tags.get(ASF_MAP.get(key, key))
                if isinstance(v, list):
                    v = [str(getattr(x, "value", x)) for x in v]
                return v
            return tags.get(key)
        except Exception:
            return None

    out["title"] = _first(g("title"))
    out["artist"] = _first(g("artist"))
    out["album_artist"] = _first(g("albumartist")) or _first(g("album artist"))
    out["album"] = _first(g("album"))
    out["genre"] = _first(g("genre"))
    out["year"] = _year(g("date")) or _year(g("originaldate")) or _year(g("year"))
    out["track_no"] = _int(g("tracknumber"))
    out["disc_no"] = _int(g("discnumber"))
    return out


def title_from_filename(path):
    name = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r"^\s*\d{1,3}\s*[-._ ]\s*", "", name)
    return name.replace("_", " ").strip() or os.path.basename(path)


def spoken_title(title):
    """Titulo para decirlo y buscarlo por voz: sin numero de pista delante ni guiones
    de nombre de archivo ("1-control-de-sueno" -> "control de sueno")."""
    t = (title or "").strip()
    if re.match(r"^[\w.]+([-_][\w.]+)+$", t):     # parece un nombre de archivo
        t = re.sub(r"^\d{1,3}[-_.]+", "", t)       # "1-control..." -> "control..."
        t = re.sub(r"[-_]+", " ", t)
    else:
        t = re.sub(r"^\d{1,3}\s*[-.)]\s+", "", t)  # "01 - Titulo", "3. Titulo"
    return t.strip() or (title or "")


def _cover_file(folder):
    try:
        files = os.listdir(folder)
    except OSError:
        return None
    lower = {f.lower(): f for f in files}
    for n in COVER_NAMES:
        for e in IMG_EXT:
            if n + e in lower:
                return os.path.join(folder, lower[n + e])
    imgs = sorted(f for f in files if f.lower().endswith(IMG_EXT))
    return os.path.join(folder, imgs[0]) if imgs else None


def embedded_art(path):
    if mutagen is None:
        return None
    try:
        f = mutagen.File(path)
    except Exception:
        return None
    if f is None:
        return None
    try:
        pics = getattr(f, "pictures", None)
        if pics:
            return pics[0].data, pics[0].mime or "image/jpeg"
        tags = f.tags
        if tags is None:
            return None
        if hasattr(tags, "getall"):  # ID3
            apic = tags.getall("APIC")
            if apic:
                return apic[0].data, apic[0].mime or "image/jpeg"
        if "covr" in tags:  # MP4
            c = tags["covr"][0]
            mime = "image/png" if getattr(c, "imageformat", 13) == 14 else "image/jpeg"
            return bytes(c), mime
        for key in ("metadata_block_picture",):  # Ogg
            if key in tags:
                import base64
                from mutagen.flac import Picture
                p = Picture(base64.b64decode(tags[key][0]))
                return p.data, p.mime or "image/jpeg"
        if "WM/Picture" in tags:  # ASF: mime\0desc\0data
            raw = tags["WM/Picture"][0].value
            idx = raw.find(b"\xff\xd8")
            if idx >= 0:
                return raw[idx:], "image/jpeg"
    except Exception as e:
        log.debug("art %s: %s", path, e)
    return None


class Library:
    def __init__(self, cfg, db):
        self.cfg = cfg
        self.db = db
        self.art_dir = os.path.join(cfg.data_dir, "art")
        os.makedirs(self.art_dir, exist_ok=True)
        self.status = {"running": False, "phase": "", "done": 0, "total": 0,
                       "added": 0, "updated": 0, "removed": 0, "error": None,
                       "started": None, "finished": None}
        self._scan_lock = threading.Lock()
        self._names_cache = None
        self.on_scan_done = None  # lo pone __main__ (subir el modelo de voz a Amazon)
        self._migrate_titles()

    def _migrate_titles(self):
        """v1.1: n_title se calcula sobre el titulo hablado. Se recalcula una vez para las
        pistas ya escaneadas (el escaneo incremental no vuelve a leer archivos sin cambios)."""
        if self.db.meta_get("ntitle_v") == "2":
            return
        rows = self.db.q("SELECT id, title FROM tracks")
        with self.db.write_lock:
            c = self.db.conn()
            c.executemany("UPDATE tracks SET n_title=? WHERE id=?",
                          [(norm(spoken_title(r["title"])), r["id"]) for r in rows])
            c.commit()
        self.db.meta_set("ntitle_v", "2")

    # ------------------------------------------------------------ escaneo
    def start_scan(self, full=False):
        if self.status["running"]:
            return False
        threading.Thread(target=self._scan_safe, args=(full,), daemon=True).start()
        return True

    def _scan_safe(self, full):
        with self._scan_lock:
            st = self.status
            st.update(running=True, phase="Buscando archivos", done=0, total=0, added=0,
                      updated=0, removed=0, error=None, started=time.time())
            try:
                self._scan(full)
                from . import upnp
                if self.cfg["upnp_enabled"]:
                    st["phase"] = "Servidores UPnP/DLNA"
                    upnp.index_all(self)
                else:
                    upnp.remove_upnp_tracks(self.db)
            except Exception as e:
                log.exception("Error en el escaneo")
                st["error"] = str(e)
            finally:
                self._names_cache = None
                st.update(running=False, phase="", finished=time.time())
                self.db.meta_set("last_scan", time.time())
            if self.on_scan_done and not st["error"]:
                try:
                    self.on_scan_done()
                except Exception:
                    log.exception("Tras el escaneo")

    def _scan(self, full):
        st = self.status
        audio, playlists, roots_ok, itunes_xml = [], [], [], []
        for root in self.cfg["music_folders"]:
            root = os.path.abspath(os.path.expanduser(root))
            if not os.path.isdir(root):
                log.warning("Carpeta no disponible (se conservan sus pistas): %s", root)
                continue
            roots_ok.append(root)
            for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fn in filenames:
                    if fn.startswith("."):
                        continue
                    ext = os.path.splitext(fn)[1].lower()
                    p = os.path.join(dirpath, fn)
                    if ext in AUDIO_EXT:
                        audio.append(p)
                    elif ext in PLAYLIST_EXT:
                        playlists.append(p)
                    elif ext == ".xml" and ("library" in fn.lower() or "itunes" in fn.lower()
                                            or "biblioteca" in fn.lower()):
                        itunes_xml.append(p)
        st["total"] = len(audio)
        st["phase"] = "Leyendo etiquetas"
        existing = {r["path"]: r for r in self.db.q(
            "SELECT id, path, mtime, size FROM tracks WHERE source='local'")}
        seen = set()
        now = time.time()
        conn = self.db.conn()
        batch = 0
        with self.db.write_lock:
            for p in audio:
                st["done"] += 1
                seen.add(p)
                try:
                    stt = os.stat(p)
                except OSError:
                    continue
                old = existing.get(p)
                if old and not full and abs((old["mtime"] or 0) - stt.st_mtime) < 1 \
                        and old["size"] == stt.st_size:
                    continue
                row = self._make_row(p, stt)
                if old:
                    cols = ", ".join(f"{k}=?" for k in row)
                    conn.execute(f"UPDATE tracks SET {cols} WHERE id=?",
                                 list(row.values()) + [old["id"]])
                    st["updated"] += 1
                else:
                    row["added"] = now
                    row["source"] = "local"
                    conn.execute(f"INSERT INTO tracks({','.join(row)}) VALUES "
                                 f"({','.join('?' * len(row))})", list(row.values()))
                    st["added"] += 1
                batch += 1
                if batch >= 200:
                    conn.commit()
                    batch = 0
            conn.commit()
            # Borrar pistas que ya no existen (solo de carpetas disponibles, o de
            # carpetas que se han quitado de la configuracion)
            configured = [os.path.abspath(os.path.expanduser(r))
                          for r in self.cfg["music_folders"]]
            gone = []
            for p, r in existing.items():
                if p in seen:
                    continue
                under_ok = any(p.startswith(root + os.sep) for root in roots_ok)
                under_cfg = any(p.startswith(root + os.sep) for root in configured)
                if under_ok or not under_cfg:
                    gone.append(r["id"])
            for i in range(0, len(gone), 500):
                chunk = gone[i:i + 500]
                ph = ",".join("?" * len(chunk))
                conn.execute(f"DELETE FROM tracks WHERE id IN ({ph})", chunk)
                conn.execute(f"DELETE FROM playlist_items WHERE track_id IN ({ph})", chunk)
            st["removed"] = len(gone)
            conn.commit()
        st["phase"] = "Listas de reproduccion"
        self._import_playlists(playlists, itunes_xml)

    def _make_row(self, p, stt):
        t = read_tags(p)
        folder = os.path.dirname(p)
        title = t.get("title") or title_from_filename(p)
        album = t.get("album") or os.path.basename(folder)
        artist = t.get("artist") or t.get("album_artist") or ""
        aartist = t.get("album_artist") or ""
        ext = os.path.splitext(p)[1].lower()
        akey = norm(album) + "|" + (norm(aartist) if aartist else folder)
        return {
            "path": p, "folder": folder, "title": title, "artist": artist,
            "album_artist": aartist, "album": album, "genre": t.get("genre") or "",
            "year": t.get("year"), "track_no": t.get("track_no"), "disc_no": t.get("disc_no"),
            "duration": t.get("duration"), "bitrate": t.get("bitrate"), "ext": ext,
            "codec": t.get("codec"), "size": stt.st_size, "mtime": stt.st_mtime,
            "album_key": akey, "n_title": norm(spoken_title(title)), "n_artist": norm(artist),
            "n_album_artist": norm(aartist), "n_album": norm(album),
            "n_genre": norm(t.get("genre") or ""),
        }

    def _import_playlists(self, files, itunes_xml=()):
        ids_by_path = {}
        for r in self.db.q("SELECT id, path FROM tracks WHERE source='local'"):
            ids_by_path[os.path.normcase(r["path"])] = r["id"]
        by_name = {}
        for p, i in ids_by_path.items():
            by_name.setdefault(os.path.basename(p), i)
        keep = set()
        for pl in files:
            try:
                entries = self._parse_playlist(pl)
            except Exception as e:
                log.warning("Lista %s: %s", pl, e)
                continue
            base = os.path.dirname(pl)
            pl_name = os.path.splitext(os.path.basename(pl))[0]
            ids = []
            for e, title in entries:
                if re.match(r"^https?://", e, re.I):   # emisora de radio / stream
                    many = sum(1 for x, _ in entries if re.match(r"^https?://", x, re.I)) > 1
                    ids.append(self.add_radio(title or (e if many else pl_name), e))
                    continue
                e = e.replace("\\", os.sep).replace("/", os.sep)
                cand = e if os.path.isabs(e) else os.path.normpath(os.path.join(base, e))
                i = ids_by_path.get(os.path.normcase(cand)) or \
                    by_name.get(os.path.normcase(os.path.basename(e)))
                if i:
                    ids.append(i)
            if not ids:
                continue
            keep.add(pl)
            self._save_file_playlist(pl, pl_name, ids)
        for r in self.db.q("SELECT id, path FROM playlists WHERE kind='file'"):
            if r["path"] not in keep:
                self.delete_playlist(r["id"])
        if itunes_xml:
            self._import_itunes(itunes_xml, by_name)

    @staticmethod
    def _parse_playlist(path):
        """[(entrada, titulo o None)] de un .m3u/.m3u8/.pls."""
        with open(path, "rb") as f:
            raw = f.read()
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        out = []
        if path.lower().endswith(".pls"):
            files, titles = {}, {}
            for line in text.splitlines():
                m = re.match(r"\s*(File|Title)(\d+)\s*=\s*(.+)", line, re.I)
                if m:
                    (files if m.group(1).lower() == "file" else titles)[m.group(2)] = \
                        m.group(3).strip()
            for k in sorted(files, key=lambda x: int(x)):
                out.append((files[k], titles.get(k)))
        else:
            title = None
            for line in text.splitlines():
                line = line.strip()
                if line.upper().startswith("#EXTINF"):
                    title = line.split(",", 1)[1].strip() if "," in line else None
                elif line and not line.startswith("#"):
                    if line.startswith("file://"):
                        line = urllib.parse.unquote(urllib.parse.urlparse(line).path)
                    out.append((line, title))
                    title = None
        return out

    # ------------------------------------------------------------ caratulas
    def art_for(self, track):
        """(bytes, mime) o None. Cachea por carpeta/album."""
        if track is None:
            return None
        key = hashlib.sha1((track["album_key"] or track["path"]).encode()).hexdigest()
        for e, mime in ((".jpg", "image/jpeg"), (".png", "image/png")):
            cp = os.path.join(self.art_dir, key + e)
            if os.path.exists(cp):
                with open(cp, "rb") as f:
                    return f.read(), mime
        if os.path.exists(os.path.join(self.art_dir, key + ".none")):
            if time.time() - os.path.getmtime(os.path.join(self.art_dir, key + ".none")) < 86400:
                return None
        data = None
        if track["source"] == "upnp":
            if track.get("art_url"):
                try:
                    import urllib.request
                    with urllib.request.urlopen(track["art_url"], timeout=8) as r:
                        data = (r.read(), r.headers.get("Content-Type", "image/jpeg"))
                except Exception:
                    data = None
        else:
            cf = _cover_file(track["folder"])
            if cf:
                with open(cf, "rb") as f:
                    data = (f.read(), "image/png" if cf.lower().endswith(".png") else "image/jpeg")
            else:
                data = embedded_art(track["path"])
        if not data:
            open(os.path.join(self.art_dir, key + ".none"), "w").close()
            return None
        data = (_shrink(data[0]) or data[0], data[1])
        if data[0][:4] == b"\x89PNG":
            ext, mime = ".png", "image/png"
        else:
            ext, mime = ".jpg", "image/jpeg"
        with open(os.path.join(self.art_dir, key + ext), "wb") as f:
            f.write(data[0])
        return data[0], mime

    # ------------------------------------------------------------ consultas
    def track(self, tid):
        return self.db.one("SELECT * FROM tracks WHERE id=?", (tid,))

    def tracks(self, ids):
        if not ids:
            return []
        out = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for r in self.db.q(f"SELECT * FROM tracks WHERE id IN ({','.join('?' * len(chunk))})",
                               chunk):
                out[r["id"]] = r
        return [out[i] for i in ids if i in out]

    def counts(self):
        return self.db.one(
            "SELECT COUNT(*) tracks, COUNT(DISTINCT album_key) albums, "
            "COUNT(DISTINCT n_artist) artists, COUNT(DISTINCT n_genre) genres, "
            "COALESCE(SUM(duration),0) seconds FROM tracks WHERE source<>'radio'")

    ORDER_ALBUM = "COALESCE(disc_no,1), COALESCE(track_no,9999), n_title"

    def artists(self):
        return self.db.q(
            "SELECT artist name, n_artist n, COUNT(*) tracks, COUNT(DISTINCT album_key) albums, "
            "MIN(id) sample FROM tracks WHERE n_artist<>'' GROUP BY n_artist ORDER BY n_artist")

    def albums(self, n_artist=None, n_genre=None, order="name"):
        where, args = ["source<>'radio'"], []   # las radios tienen su propio apartado
        if n_artist:
            where.append("(n_artist=? OR n_album_artist=?)")
            args += [n_artist, n_artist]
        if n_genre:
            where.append("n_genre=?")
            args.append(n_genre)
        w = ("WHERE " + " AND ".join(where)) if where else ""
        ob = {"name": "n_album", "recent": "MAX(added) DESC", "year": "MAX(year) DESC"}[order]
        return self.db.q(
            "SELECT album_key key, album name, n_album n, "
            "COALESCE(NULLIF(MAX(album_artist),''), MAX(artist)) artist, MAX(year) year, "
            f"COUNT(*) tracks, MIN(id) sample, MAX(added) added FROM tracks {w} "
            f"GROUP BY album_key ORDER BY {ob}", args)

    def album_tracks(self, key):
        return self.db.q(f"SELECT * FROM tracks WHERE album_key=? ORDER BY {self.ORDER_ALBUM}",
                         (key,))

    def artist_tracks(self, n_artist):
        return self.db.q(
            "SELECT * FROM tracks WHERE n_artist=? OR n_album_artist=? "
            f"ORDER BY COALESCE(year,0), album_key, {self.ORDER_ALBUM}", (n_artist, n_artist))

    def genres(self):
        return self.db.q("SELECT genre name, n_genre n, COUNT(*) tracks, MIN(id) sample "
                         "FROM tracks WHERE n_genre<>'' AND source<>'radio' "
                         "GROUP BY n_genre ORDER BY n_genre")

    def genre_tracks(self, n_genre):
        return self.db.q("SELECT * FROM tracks WHERE n_genre=? ORDER BY album_key, "
                         f"{self.ORDER_ALBUM}", (n_genre,))

    def year_tracks(self, y0, y1):
        return self.db.q("SELECT * FROM tracks WHERE year BETWEEN ? AND ? ORDER BY album_key, "
                         f"{self.ORDER_ALBUM}", (y0, y1))

    def all_tracks(self, order="title", offset=0, limit=200, q=None):
        ob = {"title": "n_title", "artist": "n_artist, album_key", "album": "album_key",
              "recent": "added DESC", "year": "year DESC"}.get(order, "n_title")
        where, args = "WHERE source<>'radio'", []   # las radios van en su apartado
        if q:
            where += " AND (n_title LIKE ? OR n_artist LIKE ? OR n_album LIKE ?)"
            like = f"%{norm(q)}%"
            args = [like, like, like]
        total = self.db.one(f"SELECT COUNT(*) c FROM tracks {where}", args)["c"]
        rows = self.db.q(f"SELECT * FROM tracks {where} ORDER BY {ob}, {self.ORDER_ALBUM} "
                         "LIMIT ? OFFSET ?", args + [limit, offset])
        return total, rows

    def random_ids(self, n):
        return [r["id"] for r in self.db.q("SELECT id FROM tracks WHERE source<>'radio' "
                                           "ORDER BY RANDOM() LIMIT ?", (n,))]

    def recent_tracks(self, n=150):
        albums = self.db.q("SELECT album_key, MAX(added) a FROM tracks WHERE source<>'radio' "
                           "GROUP BY album_key "
                           "ORDER BY a DESC LIMIT 40")
        out = []
        for a in albums:
            out += self.album_tracks(a["album_key"])
            if len(out) >= n:
                break
        return out[:n]

    def favorite_tracks(self):
        return self.db.q("SELECT t.* FROM favorites f JOIN tracks t ON t.id=f.track_id "
                         "ORDER BY f.added DESC")

    def is_favorite(self, tid):
        return self.db.one("SELECT 1 x FROM favorites WHERE track_id=?", (tid,)) is not None

    def set_favorite(self, tid, on):
        if on:
            self.db.x("INSERT OR REPLACE INTO favorites(track_id, added) VALUES(?,?)",
                      (tid, time.time()))
        else:
            self.db.x("DELETE FROM favorites WHERE track_id=?", (tid,))

    def most_played(self, n=100):
        return self.db.q("SELECT t.*, p.count plays FROM plays p JOIN tracks t ON t.id=p.track_id "
                         "ORDER BY p.count DESC, p.last DESC LIMIT ?", (n,))

    def recently_played(self, n=100):
        return self.db.q("SELECT t.* FROM plays p JOIN tracks t ON t.id=p.track_id "
                         "ORDER BY p.last DESC LIMIT ?", (n,))

    def record_play(self, tid):
        self.db.x("INSERT INTO plays(track_id,count,last) VALUES(?,1,?) ON CONFLICT(track_id) "
                  "DO UPDATE SET count=count+1, last=excluded.last", (tid, time.time()))

    # carpetas
    def roots(self):
        return [os.path.abspath(os.path.expanduser(r)) for r in self.cfg["music_folders"]]

    def folder_listing(self, path=None):
        folders = [r["folder"] for r in self.db.q(
            "SELECT DISTINCT folder FROM tracks WHERE source='local'")]
        if not path:
            subs = [r for r in self.roots() if any(f == r or f.startswith(r + os.sep)
                                                   for f in folders)]
            return {"path": None, "parent": None, "folders": [
                {"path": s, "name": s} for s in subs], "tracks": []}
        subs = set()
        pre = path.rstrip(os.sep) + os.sep
        for f in folders:
            if f.startswith(pre):
                subs.add(pre + f[len(pre):].split(os.sep)[0])
        parent = os.path.dirname(path.rstrip(os.sep))
        if path in self.roots():
            parent = ""
        tracks = self.db.q(f"SELECT * FROM tracks WHERE folder=? ORDER BY {self.ORDER_ALBUM}",
                           (path,))
        return {"path": path, "parent": parent,
                "folders": [{"path": s, "name": os.path.basename(s)} for s in sorted(subs)],
                "tracks": tracks}

    def folder_tracks(self, path):
        pre = path.rstrip(os.sep) + os.sep
        return self.db.q("SELECT * FROM tracks WHERE folder=? OR substr(folder,1,?)=? "
                         f"ORDER BY folder, {self.ORDER_ALBUM}", (path, len(pre), pre))

    def folder_names(self):
        out = {}
        for r in self.db.q("SELECT DISTINCT folder FROM tracks WHERE source='local'"):
            f = r["folder"]
            while f and f not in out and f not in self.roots():
                out[f] = norm(os.path.basename(f))
                f = os.path.dirname(f)
        return out

    # listas
    def playlists(self):
        return self.db.q("SELECT p.id, p.name, p.kind, COUNT(i.track_id) tracks, "
                         "MIN(i.track_id) sample FROM playlists p "
                         "LEFT JOIN playlist_items i ON i.playlist_id=p.id "
                         "GROUP BY p.id ORDER BY p.name COLLATE NOCASE")

    def playlist(self, pid):
        return self.db.one("SELECT * FROM playlists WHERE id=?", (pid,))

    def playlist_tracks(self, pid):
        return self.db.q("SELECT t.*, i.pos FROM playlist_items i JOIN tracks t ON t.id=i.track_id "
                         "WHERE i.playlist_id=? ORDER BY i.pos", (pid,))

    def create_playlist(self, name, ids=()):
        pid = self.db.x("INSERT INTO playlists(name,n_name,kind,created) VALUES(?,?,?,?)",
                        (name, norm(name), "user", time.time())).lastrowid
        self.add_to_playlist(pid, ids)
        self._names_cache = None
        return pid

    def add_to_playlist(self, pid, ids):
        if not ids:
            return
        start = self.db.one("SELECT COALESCE(MAX(pos),-1)+1 n FROM playlist_items "
                            "WHERE playlist_id=?", (pid,))["n"]
        with self.db.write_lock:
            c = self.db.conn()
            c.executemany("INSERT INTO playlist_items(playlist_id,pos,track_id) VALUES(?,?,?)",
                          [(pid, start + n, i) for n, i in enumerate(ids)])
            c.commit()

    def set_playlist_items(self, pid, ids):
        with self.db.write_lock:
            c = self.db.conn()
            c.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
            c.executemany("INSERT INTO playlist_items(playlist_id,pos,track_id) VALUES(?,?,?)",
                          [(pid, n, i) for n, i in enumerate(ids)])
            c.commit()

    def rename_playlist(self, pid, name):
        self.db.x("UPDATE playlists SET name=?, n_name=? WHERE id=?", (name, norm(name), pid))
        self._names_cache = None

    def delete_playlist(self, pid):
        self.db.x("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
        self.db.x("DELETE FROM playlists WHERE id=?", (pid,))
        self._names_cache = None

    # ------------------------------------------------------------ busqueda por voz
    def _names(self):
        if self._names_cache is None:
            artists = {}
            for r in self.db.q("SELECT n_artist n, artist name FROM tracks WHERE n_artist<>'' "
                               "UNION SELECT n_album_artist, album_artist FROM tracks "
                               "WHERE n_album_artist<>''"):
                artists.setdefault(r["n"], r["name"])
            self._names_cache = {
                "artists": artists,
                "albums": self.db.q("SELECT album_key key, n_album n, MAX(album) name, "
                                    "COALESCE(NULLIF(MAX(n_album_artist),''), MAX(n_artist)) "
                                    "na FROM tracks GROUP BY album_key"),
                "genres": {r["n"]: r["name"] for r in self.db.q(
                    "SELECT n_genre n, MAX(genre) name FROM tracks WHERE n_genre<>'' "
                    "GROUP BY n_genre")},
                "playlists": self.db.q("SELECT id, name, n_name n FROM playlists"),
            }
        return self._names_cache

    def find_artist(self, q):
        names = self._names()["artists"]
        return [(s, n, names[n]) for s, n in best(q, names.keys(), key=lambda x: x)]

    def find_album(self, q, artist_q=None):
        albums = self._names()["albums"]
        res = best(q, albums, key=lambda a: a["n"], threshold=0.6, limit=30)
        if artist_q:
            na = norm(artist_q)
            from .textnorm import score
            res = [(s * 0.7 + 0.3 * score(na, a["na"] or ""), a) for s, a in res]
            res.sort(key=lambda x: -x[0])
        return res

    def find_genre(self, q):
        g = self._names()["genres"]
        return [(s, n, g[n]) for s, n in best(q, g.keys(), threshold=0.6)]

    def find_playlist(self, q):
        return best(q, self._names()["playlists"], key=lambda p: p["n"], threshold=0.55)

    def find_song(self, q, artist_q=None):
        nq = norm(q)
        if not nq:
            return []
        words = [w for w in nq.split() if len(w) > 2] or nq.split()
        # prefiltro en SQL: pistas que contienen ALGUNA de las palabras (las 4 mas largas).
        # Sumar y no sustituir: con "la pista control de sueno" la palabra "pista" no
        # esta en ningun titulo, pero "control" si.
        cand = {}
        for w in sorted(set(words), key=len, reverse=True)[:4]:
            for r in self.db.q("SELECT * FROM tracks WHERE n_title LIKE ? LIMIT 2000",
                               (f"%{w}%",)):
                cand[r["id"]] = r
        if len(cand) < 5:   # nada parecido por palabras: probar por el principio
            for r in self.db.q("SELECT * FROM tracks WHERE n_title LIKE ? LIMIT 2000",
                               (f"%{nq[:3]}%",)):
                cand[r["id"]] = r
        res = best(q, cand.values(), key=lambda t: t["n_title"], threshold=0.6, limit=30)
        if artist_q:
            from .textnorm import score
            na = norm(artist_q)
            res = [(s * 0.65 + 0.35 * max(score(na, t["n_artist"]), score(na, t["n_album_artist"]
                                                                           or "")), t)
                   for s, t in res]
            res.sort(key=lambda x: -x[0])
        return res

    def find_folder(self, q):
        names = self.folder_names()
        return [(s, p) for s, p in best(q, names.items(), key=lambda x: x[1], threshold=0.6)]

    def search(self, q, limit=20):
        """Busqueda para la web: devuelve listas por tipo."""
        return {
            "artists": [{"score": s, "n": n, "name": name}
                        for s, n, name in self.find_artist(q)[:limit]],
            "albums": [{"score": s, "key": a["key"], "name": a["name"]}
                       for s, a in self.find_album(q)[:limit]],
            "tracks": [dict(t, score=s) for s, t in self.find_song(q)[:limit]],
            "genres": [{"score": s, "n": n, "name": name} for s, n, name in self.find_genre(q)],
            "playlists": [dict(p, score=s) for s, p in self.find_playlist(q)],
        }

    def resolve_any(self, q):
        """Para 'pon {lo que sea}': elige el mejor tipo. Devuelve (tipo, nombre, tracks)."""
        cands = []
        a = self.find_artist(q)
        if a:
            cands.append((a[0][0] + 0.02, "artist", a[0][2], lambda: self.artist_tracks(a[0][1])))
        al = self.find_album(q)
        if al:
            # -0.03: si una pista se llama igual que su album, gana la pista
            cands.append((al[0][0] - 0.03, "album", al[0][1]["name"],
                          lambda: self.album_tracks(al[0][1]["key"])))
        pl = self.find_playlist(q)
        if pl:
            cands.append((pl[0][0] + 0.01, "playlist", pl[0][1]["name"],
                          lambda: self.playlist_tracks(pl[0][1]["id"])))
        g = self.find_genre(q)
        if g:
            cands.append((g[0][0] - 0.01, "genre", g[0][2], lambda: self.genre_tracks(g[0][1])))
        s = self.find_song(q)
        if s:
            cands.append((s[0][0] - 0.02, "song", spoken_title(s[0][1]["title"]),
                          lambda: [s[0][1]]))
        if not cands:
            return None
        cands.sort(key=lambda c: -c[0])
        sc, kind, name, fn = cands[0]
        tracks = fn()
        if kind == "album" and len(tracks) == 1:   # un "album" de una sola pista es una pista
            return "song", spoken_title(tracks[0]["title"]), tracks
        return kind, name, tracks

    def names_for_model(self, limit=2500):
        n = self._names()
        albums = sorted({a["name"] for a in n["albums"] if a["name"]})
        titles = [spoken_title(r["title"]) for r in self.db.q(
            "SELECT title FROM tracks LEFT JOIN plays ON plays.track_id=tracks.id "
            "GROUP BY n_title ORDER BY COALESCE(MAX(plays.count),0) DESC, n_title LIMIT ?",
            (limit,))]
        folders = sorted({os.path.basename(f) for f in self.folder_names()})
        return {
            "artists": sorted(set(n["artists"].values()))[:limit],
            "albums": albums[:limit], "songs": titles,
            "genres": sorted(set(n["genres"].values()))[:limit],
            "playlists": sorted({p["name"] for p in n["playlists"]})[:limit],
            "folders": folders[:limit],
            "stations": [r["title"] for r in self.radios()][:limit],
        }

    # ------------------------------------------------------------ pistas ignoradas
    def ignored_ids(self):
        return {r["track_id"] for r in self.db.q("SELECT track_id FROM ignored")}

    def set_ignored(self, tid, on=True):
        if on:
            self.db.x("INSERT OR REPLACE INTO ignored(track_id, added) VALUES(?,?)",
                      (tid, time.time()))
        else:
            self.db.x("DELETE FROM ignored WHERE track_id=?", (tid,))

    def ignored_tracks(self):
        return self.db.q("SELECT t.* FROM ignored i JOIN tracks t ON t.id=i.track_id "
                         "ORDER BY i.added DESC")

    # ------------------------------------------------------------ audiolibros
    def bookmark(self, album_key):
        return self.db.one("SELECT * FROM bookmarks WHERE album_key=?", (album_key,))

    def save_bookmark(self, album_key, tid, offset_ms):
        self.db.x("INSERT OR REPLACE INTO bookmarks(album_key, track_id, offset_ms, updated) "
                  "VALUES(?,?,?,?)", (album_key, tid, int(offset_ms or 0), time.time()))

    def clear_bookmark(self, album_key):
        self.db.x("DELETE FROM bookmarks WHERE album_key=?", (album_key,))

    # ------------------------------------------------------------ radios por Internet
    # Se guardan como pistas (source='radio', path='radio:<url>') para reutilizar la cola,
    # el envio de audio y la busqueda por voz.
    def radios(self):
        return self.db.q("SELECT * FROM tracks WHERE source='radio' ORDER BY n_title")

    def add_radio(self, name, url):
        name = (name or "").strip() or url
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
        ext = ext if ext in (".mp3", ".aac", ".m4a", ".ogg", ".opus") else ".mp3"
        path = "radio:" + url.strip()
        row = {"path": path, "source": "radio", "folder": "radio:", "title": name,
               "artist": "", "album_artist": "", "album": "Radios", "genre": "Radio",
               "ext": ext, "album_key": "radio|", "n_title": norm(name), "n_artist": "",
               "n_album_artist": "", "n_album": norm("Radios"), "n_genre": norm("Radio"),
               "added": time.time()}
        old = self.db.one("SELECT id FROM tracks WHERE path=?", (path,))
        if old:
            self.db.x("UPDATE tracks SET title=?, n_title=? WHERE id=?",
                      (name, norm(name), old["id"]))
            self._names_cache = None
            return old["id"]
        rid = self.db.x(f"INSERT INTO tracks({','.join(row)}) VALUES "
                        f"({','.join('?' * len(row))})", list(row.values())).lastrowid
        self._names_cache = None
        return rid

    def delete_radio(self, rid):
        self.db.x("DELETE FROM tracks WHERE id=? AND source='radio'", (rid,))
        self.db.x("DELETE FROM playlist_items WHERE track_id=?", (rid,))
        self._names_cache = None

    def find_radio(self, q):
        return best(q, self.radios(), key=lambda r: r["n_title"], threshold=0.55)

    # ------------------------------------------------------------ playlists de iTunes
    def _import_itunes(self, xml_files, ids_by_name):
        """Lee 'iTunes Library.xml' / 'Library.xml' (Archivo > Biblioteca > Exportar) y
        crea sus playlists, casando las pistas por nombre de archivo."""
        import plistlib
        keep = set()
        for xf in xml_files:
            try:
                with open(xf, "rb") as f:
                    data = plistlib.load(f)
            except Exception as e:
                log.warning("iTunes %s: %s", xf, e)
                continue
            if not isinstance(data, dict) or "Tracks" not in data:
                continue
            loc = {}
            for tid, t in (data.get("Tracks") or {}).items():
                url = t.get("Location") or ""
                name = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path))
                if name:
                    loc[str(tid)] = name
            for pl in data.get("Playlists") or []:
                if pl.get("Master") or pl.get("Distinguished Kind") or pl.get("Folder") \
                        or pl.get("Visible") is False:
                    continue
                ids = []
                for it in pl.get("Playlist Items") or []:
                    i = ids_by_name.get(os.path.normcase(loc.get(str(it.get("Track ID")), "")))
                    if i:
                        ids.append(i)
                if not ids:
                    continue
                name = pl.get("Name") or "iTunes"
                key = f"{xf}#{pl.get('Playlist Persistent ID') or name}"
                keep.add(key)
                self._save_file_playlist(key, name, ids, kind="itunes")
        for r in self.db.q("SELECT id, path FROM playlists WHERE kind='itunes'"):
            if r["path"] not in keep:
                self.delete_playlist(r["id"])

    def _save_file_playlist(self, path, name, ids, kind="file"):
        with self.db.write_lock:
            c = self.db.conn()
            row = c.execute("SELECT id FROM playlists WHERE path=?", (path,)).fetchone()
            if row:
                pid = row[0]
                c.execute("UPDATE playlists SET name=?, n_name=? WHERE id=?",
                          (name, norm(name), pid))
                c.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
            else:
                pid = c.execute("INSERT INTO playlists(name,n_name,kind,path,created) "
                                "VALUES(?,?,?,?,?)",
                                (name, norm(name), kind, path, time.time())).lastrowid
            c.executemany("INSERT INTO playlist_items(playlist_id,pos,track_id) VALUES(?,?,?)",
                          [(pid, n, i) for n, i in enumerate(ids)])
            c.commit()


def _shrink(data, size=800):
    """Reduce caratulas enormes si Pillow esta instalado (Echo Show va mejor)."""
    try:
        from PIL import Image
        import io
    except ImportError:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        if max(im.size) <= size and im.format in ("JPEG", "PNG"):
            return None
        im = im.convert("RGB")
        im.thumbnail((size, size))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=88)
        return out.getvalue()
    except Exception:
        return None


def shuffled(seq):
    seq = list(seq)
    random.shuffle(seq)
    return seq
