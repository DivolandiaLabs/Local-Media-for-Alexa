"""Cliente UPnP/DLNA: descubre servidores multimedia de la red (NAS, Plex, MiniDLNA,
Serviio, Jellyfin...) y añade su musica a la biblioteca."""
import logging
import os
import socket
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html import escape

from .textnorm import norm

log = logging.getLogger("localmedia.upnp")

NS = {
    "d": "urn:schemas-upnp-org:device-1-0",
    "didl": "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/",
}
CD = "urn:schemas-upnp-org:service:ContentDirectory:1"
MIME_EXT = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
            "audio/aac": ".aac", "audio/flac": ".flac", "audio/x-flac": ".flac",
            "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/L16": ".wav",
            "audio/x-ms-wma": ".wma", "audio/opus": ".opus"}


def discover(timeout=3.0):
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
           "MX: 2\r\nST: urn:schemas-upnp-org:device:MediaServer:1\r\n\r\n").encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.settimeout(0.5)
    found = {}
    try:
        for _ in range(2):
            s.sendto(msg, ("239.255.255.250", 1900))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, _ = s.recvfrom(65507)
            except socket.timeout:
                continue
            headers = {}
            for line in data.decode(errors="ignore").split("\r\n")[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            loc = headers.get("location")
            if loc and loc not in found:
                found[loc] = None
    finally:
        s.close()
    out = []
    for loc in found:
        try:
            info = describe(loc)
            if info:
                out.append(info)
        except Exception as e:
            log.debug("describe %s: %s", loc, e)
    return out


def describe(location):
    with urllib.request.urlopen(location, timeout=5) as r:
        root = ET.fromstring(r.read())
    base = root.findtext("d:URLBase", namespaces=NS) or location
    for dev in root.iter("{%s}device" % NS["d"]):
        for svc in dev.iter("{%s}service" % NS["d"]):
            if svc.findtext("d:serviceType", namespaces=NS, default="").startswith(
                    "urn:schemas-upnp-org:service:ContentDirectory"):
                return {
                    "location": location,
                    "name": dev.findtext("d:friendlyName", namespaces=NS, default=location),
                    "control": urllib.parse.urljoin(base, svc.findtext("d:controlURL",
                                                                       namespaces=NS)),
                    "service": svc.findtext("d:serviceType", namespaces=NS),
                }
    return None


def browse(control, service, object_id, start=0, count=200):
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:Browse xmlns:u="{service}"><ObjectID>{escape(object_id)}</ObjectID>'
        '<BrowseFlag>BrowseDirectChildren</BrowseFlag><Filter>*</Filter>'
        f'<StartingIndex>{start}</StartingIndex><RequestedCount>{count}</RequestedCount>'
        '<SortCriteria></SortCriteria></u:Browse></s:Body></s:Envelope>').encode()
    req = urllib.request.Request(control, data=body, headers={
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": f'"{service}#Browse"'})
    with urllib.request.urlopen(req, timeout=20) as r:
        env = ET.fromstring(r.read())
    result = total = returned = None
    for el in env.iter():
        tag = el.tag.split("}")[-1]
        if tag == "Result":
            result = el.text or ""
        elif tag == "TotalMatches":
            total = int(el.text or 0)
        elif tag == "NumberReturned":
            returned = int(el.text or 0)
    didl = ET.fromstring(result) if result else None
    return didl, total or 0, returned or 0


def _dur(s):
    if not s:
        return None
    try:
        parts = [float(p) for p in s.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except ValueError:
        return None


def walk(server, max_items=100000, max_depth=14):
    """Genera dicts de pista recorriendo el arbol del servidor."""
    seen_items, seen_cont = set(), set()
    stack = [("0", 0)]
    while stack and len(seen_items) < max_items:
        oid, depth = stack.pop()
        if oid in seen_cont or depth > max_depth:
            continue
        seen_cont.add(oid)
        start = 0
        while True:
            try:
                didl, total, returned = browse(server["control"], server["service"], oid, start)
            except Exception as e:
                log.warning("UPnP browse %s/%s: %s", server["name"], oid, e)
                break
            if didl is None or returned == 0:
                break
            for el in didl:
                tag = el.tag.split("}")[-1]
                if tag == "container":
                    stack.append((el.get("id"), depth + 1))
                elif tag == "item":
                    cls = el.findtext("upnp:class", namespaces=NS, default="")
                    if not cls.startswith("object.item.audioItem"):
                        continue
                    res = None
                    for r in el.findall("didl:res", NS):
                        pi = r.get("protocolInfo", "")
                        if ":audio/" in pi or res is None:
                            res = r
                    if res is None or not (res.text or "").strip():
                        continue
                    url = res.text.strip()
                    if url in seen_items:
                        continue
                    seen_items.add(url)
                    pi = (res.get("protocolInfo") or "").split(":")
                    mime = pi[2] if len(pi) > 2 else ""
                    yield {
                        "url": url,
                        "title": el.findtext("dc:title", namespaces=NS, default=""),
                        "artist": el.findtext("upnp:artist", namespaces=NS) or
                        el.findtext("dc:creator", namespaces=NS) or "",
                        "album_artist": el.findtext("upnp:albumArtist", namespaces=NS) or "",
                        "album": el.findtext("upnp:album", namespaces=NS, default=""),
                        "genre": el.findtext("upnp:genre", namespaces=NS, default=""),
                        "date": el.findtext("dc:date", namespaces=NS, default=""),
                        "track_no": el.findtext("upnp:originalTrackNumber", namespaces=NS),
                        "art": el.findtext("upnp:albumArtURI", namespaces=NS),
                        "duration": _dur(res.get("duration")),
                        "ext": MIME_EXT.get(mime.split(";")[0].strip(),
                                            os.path.splitext(urllib.parse.urlparse(url).path)[1]
                                            .lower() or ".mp3"),
                    }
            start += returned
            if start >= total:
                break


def index_all(lib):
    """Sincroniza todos los servidores activados con la tabla tracks (source='upnp')."""
    db, st = lib.db, lib.status
    keep_ok = True
    seen = set()
    now = time.time()
    for srv_cfg in lib.cfg["upnp_servers"]:
        if not srv_cfg.get("enabled", True):
            continue
        try:
            server = describe(srv_cfg["location"])
        except Exception as e:
            log.warning("Servidor UPnP no disponible %s: %s", srv_cfg.get("name"), e)
            keep_ok = False
            continue
        if not server:
            continue
        st["phase"] = f"UPnP: {server['name']}"
        existing = {r["path"]: r["id"] for r in db.q(
            "SELECT id, path FROM tracks WHERE source='upnp'")}
        with db.write_lock:
            c = db.conn()
            for n, it in enumerate(walk(server)):
                path = "upnp:" + it["url"]
                seen.add(path)
                year = None
                if it["date"][:4].isdigit():
                    year = int(it["date"][:4])
                try:
                    tn = int(it["track_no"]) if it["track_no"] else None
                except ValueError:
                    tn = None
                folder = "upnp:" + server["name"]
                album = it["album"] or server["name"]
                akey = norm(album) + "|" + (norm(it["album_artist"]) or
                                            norm(it["artist"]) or folder)
                row = {"path": path, "source": "upnp", "folder": folder,
                       "title": it["title"], "artist": it["artist"],
                       "album_artist": it["album_artist"], "album": album,
                       "genre": it["genre"], "year": year, "track_no": tn, "disc_no": None,
                       "duration": it["duration"], "ext": it["ext"], "art_url": it["art"],
                       "album_key": akey, "n_title": norm(it["title"]),
                       "n_artist": norm(it["artist"]),
                       "n_album_artist": norm(it["album_artist"]), "n_album": norm(album),
                       "n_genre": norm(it["genre"])}
                if path in existing:
                    cols = ", ".join(f"{k}=?" for k in row)
                    c.execute(f"UPDATE tracks SET {cols} WHERE id=?",
                              list(row.values()) + [existing[path]])
                else:
                    row["added"] = now
                    c.execute(f"INSERT INTO tracks({','.join(row)}) VALUES "
                              f"({','.join('?' * len(row))})", list(row.values()))
                    st["added"] += 1
                if n % 200 == 0:
                    c.commit()
            c.commit()
    # Si algun servidor no respondia no borramos nada (evita vaciar la biblioteca
    # porque el NAS estaba dormido).
    if keep_ok:
        remove_upnp_tracks(db, keep=seen)


def remove_upnp_tracks(db, keep=frozenset()):
    gone = [r["id"] for r in db.q("SELECT id, path FROM tracks WHERE source='upnp'")
            if r["path"] not in keep]
    for i in range(0, len(gone), 500):
        chunk = gone[i:i + 500]
        ph = ",".join("?" * len(chunk))
        db.x(f"DELETE FROM tracks WHERE id IN ({ph})", chunk)
        db.x(f"DELETE FROM playlist_items WHERE track_id IN ({ph})", chunk)
