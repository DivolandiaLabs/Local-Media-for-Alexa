"""SQLite con una conexion por hilo."""
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks(
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  source TEXT NOT NULL DEFAULT 'local',
  folder TEXT, title TEXT, artist TEXT, album_artist TEXT, album TEXT, genre TEXT,
  year INTEGER, track_no INTEGER, disc_no INTEGER, duration REAL, bitrate INTEGER,
  ext TEXT, codec TEXT, size INTEGER, mtime REAL, added REAL, art_url TEXT,
  album_key TEXT,
  n_title TEXT, n_artist TEXT, n_album_artist TEXT, n_album TEXT, n_genre TEXT
);
CREATE INDEX IF NOT EXISTS ix_artist ON tracks(n_artist);
CREATE INDEX IF NOT EXISTS ix_aartist ON tracks(n_album_artist);
CREATE INDEX IF NOT EXISTS ix_album ON tracks(album_key);
CREATE INDEX IF NOT EXISTS ix_genre ON tracks(n_genre);
CREATE INDEX IF NOT EXISTS ix_folder ON tracks(folder);
CREATE INDEX IF NOT EXISTS ix_added ON tracks(added);
CREATE INDEX IF NOT EXISTS ix_year ON tracks(year);

CREATE TABLE IF NOT EXISTS playlists(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, n_name TEXT,
  kind TEXT NOT NULL DEFAULT 'user', path TEXT UNIQUE, created REAL
);
CREATE TABLE IF NOT EXISTS playlist_items(
  playlist_id INTEGER NOT NULL, pos INTEGER NOT NULL, track_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pli ON playlist_items(playlist_id, pos);

CREATE TABLE IF NOT EXISTS favorites(track_id INTEGER PRIMARY KEY, added REAL);
CREATE TABLE IF NOT EXISTS plays(track_id INTEGER PRIMARY KEY, count INTEGER, last REAL);
CREATE TABLE IF NOT EXISTS devices(
  device_id TEXT PRIMARY KEY, name TEXT, user_id TEXT, last_seen REAL, state TEXT
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
-- "Alexa, ... no ponga esta de nuevo": no se mete en las colas de voz
CREATE TABLE IF NOT EXISTS ignored(track_id INTEGER PRIMARY KEY, added REAL);
-- audiolibros: por donde ibas en cada libro (album)
CREATE TABLE IF NOT EXISTS bookmarks(
  album_key TEXT PRIMARY KEY, track_id INTEGER, offset_ms INTEGER, updated REAL
);
"""


class DB:
    def __init__(self, path):
        self.path = path
        self._local = threading.local()
        self.write_lock = threading.RLock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        c = self.conn()
        c.executescript(SCHEMA)
        c.commit()

    def conn(self):
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.c = c
        return c

    def q(self, sql, args=()):
        return [dict(r) for r in self.conn().execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self.conn().execute(sql, args).fetchone()
        return dict(r) if r else None

    def x(self, sql, args=()):
        with self.write_lock:
            c = self.conn()
            cur = c.execute(sql, args)
            c.commit()
            return cur

    def meta_get(self, key, default=None):
        r = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return r["value"] if r else default

    def meta_set(self, key, value):
        self.x("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))
