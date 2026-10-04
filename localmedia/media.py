"""Envio de audio a Alexa / navegador, con conversion a MP3 cuando hace falta."""
import logging
import os
import re
import subprocess
import urllib.request

from flask import Response, request, send_file, abort

log = logging.getLogger("localmedia.media")

# Lo que los Echo reproducen directamente (AAC/MP4 y MP3).
NATIVE_EXT = {".mp3", ".m4a", ".m4b", ".aac", ".mp4"}
MIME = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".m4b": "audio/mp4", ".mp4": "audio/mp4",
        ".aac": "audio/aac", ".flac": "audio/flac", ".ogg": "audio/ogg", ".oga": "audio/ogg",
        ".opus": "audio/ogg", ".wav": "audio/wav", ".wma": "audio/x-ms-wma"}


def needs_transcode(track, cfg):
    mode = cfg["transcode"]
    if mode == "never":
        return False
    if mode == "always":
        return track["ext"] != ".mp3"
    if track["ext"] not in NATIVE_EXT:
        return True
    if (track.get("codec") or "").startswith("alac"):
        return True
    br = track.get("bitrate") or 0
    return br > 384  # limite de Alexa


def stream(track, cfg, start=0.0, transcode=None):
    if track is None:
        abort(404)
    if transcode is None:
        transcode = needs_transcode(track, cfg)
    remote = track["source"] in ("upnp", "radio")
    src = track["path"].split(":", 1)[1] if remote else track["path"]
    if track["source"] == "radio":
        start = 0  # en directo no se puede saltar
    if transcode:
        return _transcode(src, cfg, start)
    if remote:
        # las radios suelen ser http: pasan por aqui para que Alexa las reciba por https
        return _proxy(src)
    if not os.path.exists(src):
        abort(404)
    return send_file(src, mimetype=MIME.get(track["ext"], "application/octet-stream"),
                     conditional=True, etag=True, max_age=0)


def _transcode(src, cfg, start):
    headers = {"Content-Type": "audio/mpeg", "Cache-Control": "no-cache",
               "Accept-Ranges": "none"}
    if request.method == "HEAD":
        return Response(status=200, headers=headers)
    cmd = [cfg["ffmpeg"], "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start and start > 0:
        cmd += ["-ss", f"{start:.2f}"]
    cmd += ["-i", src, "-map", "0:a:0", "-vn", "-c:a", "libmp3lame",
            "-b:a", f"{int(cfg['transcode_bitrate'])}k", "-ar", "44100", "-ac", "2",
            "-f", "mp3", "pipe:1"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                bufsize=0)
    except FileNotFoundError:
        log.error("No se encuentra ffmpeg (%s). Instalalo: sudo apt install ffmpeg",
                  cfg["ffmpeg"])
        abort(500)

    def gen():
        try:
            while True:
                chunk = proc.stdout.read(32768)
                if not chunk:
                    break
                yield chunk
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    return Response(gen(), headers=headers, direct_passthrough=True)


def _proxy(url):
    """Reenvia un archivo de un servidor UPnP (que solo es visible en la red local)."""
    hdrs = {}
    if request.headers.get("Range"):
        hdrs["Range"] = request.headers["Range"]
    req = urllib.request.Request(url, headers=hdrs, method=request.method)
    try:
        r = urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as e:
        r = e
    out_headers = {}
    for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
        if r.headers.get(h):
            out_headers[h] = r.headers[h]

    def gen():
        try:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            r.close()

    if request.method == "HEAD":
        r.close()
        return Response(status=r.status, headers=out_headers)
    return Response(gen(), status=r.status, headers=out_headers, direct_passthrough=True)


def parse_start(v):
    try:
        return max(0.0, float(v or 0))
    except ValueError:
        return 0.0


SAFE_EXT = re.compile(r"^[a-z0-9]{1,5}$")
