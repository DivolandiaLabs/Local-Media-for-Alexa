"""Genera el modelo de interaccion de la skill (JSON para la consola de Alexa).

Con library=None usa valores de ejemplo; con la biblioteca, rellena los tipos de slot
con tus artistas, albumes, canciones... (mejora mucho el reconocimiento)."""
import re
import socket
import ssl
import urllib.parse

INVOCATION = {"es": "mi colección", "en": "my collection"}

U = {
    "es": {
        "PlayArtistIntent": ["pon música de {artist}", "pon canciones de {artist}",
                             "reproduce música de {artist}", "pon al artista {artist}",
                             "pon al grupo {artist}", "pon algo de {artist}",
                             "quiero escuchar a {artist}", "pon a {artist}",
                             "reproduce a {artist}", "pon temas de {artist}"],
        "PlayAlbumIntent": ["pon el álbum {album}", "pon el disco {album}",
                            "reproduce el álbum {album}", "reproduce el disco {album}",
                            "pon el álbum {album} de {artist}", "pon el disco {album} de {artist}",
                            "quiero escuchar el disco {album}", "quiero escuchar el álbum {album}"],
        "PlaySongIntent": ["pon la canción {song}", "reproduce la canción {song}",
                           "pon la canción {song} de {artist}", "pon el tema {song}",
                           "pon el tema {song} de {artist}", "quiero escuchar la canción {song}",
                           "reproduce el tema {song}",
                           "reproduce la pista {song}", "pon la pista {song}",
                           "reproduce la pista {song} de {artist}", "quiero escuchar la pista {song}",
                           "reproduce el audio {song}", "pon el audio {song}",
                           "quiero escuchar el audio {song}", "reproduce la grabación {song}",
                           "pon la grabación {song}", "reproduce la meditación {song}",
                           "pon la meditación {song}", "abre la pista {song}",
                           "abre el audio {song}"],
        "PlayGenreIntent": ["pon música {genre}", "pon el género {genre}",
                            "reproduce música {genre}", "pon música del género {genre}",
                            "quiero escuchar música {genre}"],
        "PlayPlaylistIntent": ["pon la lista {playlist}", "pon la lista de reproducción {playlist}",
                               "pon mi lista {playlist}", "reproduce la lista {playlist}",
                               "pon la playlist {playlist}", "reproduce la playlist {playlist}"],
        "PlayFolderIntent": ["pon la carpeta {folder}", "reproduce la carpeta {folder}",
                             "pon lo que hay en la carpeta {folder}"],
        "PlayYearIntent": ["pon música del {year}", "pon música del año {year}",
                           "pon canciones del {year}", "pon canciones del año {year}",
                           "reproduce música del año {year}"],
        "PlayDecadeIntent": ["pon música de los {decade}", "pon canciones de los {decade}",
                             "pon éxitos de los {decade}", "reproduce música de los {decade}",
                             "pon algo de los {decade}"],
        "ShuffleAllIntent": ["pon toda mi música", "pon música aleatoria", "pon algo",
                             "pon música", "mezcla toda mi música", "sorpréndeme",
                             "reproduce toda la biblioteca", "pon todo",
                             "pon mi música en aleatorio", "pon toda la música"],
        "PlayRecentIntent": ["pon lo último que he añadido", "pon lo más nuevo",
                             "pon las novedades", "pon la música reciente",
                             "pon lo último añadido", "pon los últimos discos"],
        "PlayFavoritesIntent": ["pon mis favoritas", "pon mis favoritos",
                                "pon mis canciones favoritas", "pon mi música favorita"],
        "PlayMostPlayedIntent": ["pon lo más escuchado", "pon mis canciones más escuchadas",
                                 "pon lo que más escucho", "pon lo más reproducido"],
        "PlayMoreByArtistIntent": ["pon más de este artista", "más de este artista",
                                   "pon más de este grupo", "más canciones de este artista",
                                   "pon más canciones de este grupo"],
        "PlayCurrentAlbumIntent": ["pon este álbum", "pon el álbum entero", "pon el disco completo",
                                   "pon este disco", "pon el álbum completo"],
        "WhatIsPlayingIntent": ["qué está sonando", "qué suena", "qué canción es esta",
                                "cómo se llama esta canción", "quién canta esto",
                                "qué es esto", "qué canción suena", "de quién es esta canción"],
        "PlayAnythingIntent": ["pon {query}", "reproduce {query}", "quiero escuchar {query}",
                               "busca {query}", "toca {query}"],
    },
    "en": {
        "PlayArtistIntent": ["play music by {artist}", "play songs by {artist}",
                             "play the artist {artist}", "play the band {artist}",
                             "play something by {artist}", "i want to hear {artist}",
                             "play artist {artist}", "shuffle {artist}", "play tracks by {artist}"],
        "PlayAlbumIntent": ["play the album {album}", "play album {album}",
                            "play the record {album}", "play the album {album} by {artist}",
                            "play album {album} by {artist}", "i want to hear the album {album}"],
        "PlaySongIntent": ["play the song {song}", "play song {song}",
                           "play the song {song} by {artist}", "play the track {song}",
                           "play the track {song} by {artist}", "i want to hear the song {song}",
                           "play the audio {song}", "play the recording {song}",
                           "play the meditation {song}", "open the track {song}"],
        "PlayGenreIntent": ["play {genre} music", "play the genre {genre}", "play genre {genre}",
                            "play some {genre} music", "play {genre} songs"],
        "PlayPlaylistIntent": ["play the playlist {playlist}", "play playlist {playlist}",
                               "play my playlist {playlist}", "play my {playlist} playlist",
                               "play the {playlist} playlist"],
        "PlayFolderIntent": ["play the folder {folder}", "play folder {folder}",
                             "play the {folder} folder"],
        "PlayYearIntent": ["play music from {year}", "play songs from {year}",
                           "play music from the year {year}", "play songs from the year {year}"],
        "PlayDecadeIntent": ["play music from the {decade}", "play songs from the {decade}",
                             "play hits from the {decade}", "play {decade} music"],
        "ShuffleAllIntent": ["play all my music", "shuffle all my music", "play some music",
                             "play music", "shuffle my library", "surprise me", "play everything",
                             "play random music", "shuffle everything"],
        "PlayRecentIntent": ["play recently added music", "play my newest music",
                             "play what i added recently", "play the latest albums",
                             "play new music"],
        "PlayFavoritesIntent": ["play my favorites", "play my favourites",
                                "play my favorite songs", "play my favourite music"],
        "PlayMostPlayedIntent": ["play my most played songs", "play my most played music",
                                 "play what i listen to most", "play my top songs"],
        "PlayMoreByArtistIntent": ["play more by this artist", "more by this artist",
                                   "play more from this band", "play more songs by this artist"],
        "PlayCurrentAlbumIntent": ["play this album", "play the whole album",
                                   "play the full album", "play the rest of this album"],
        "WhatIsPlayingIntent": ["what's playing", "what is playing", "what song is this",
                                "what is this song", "who sings this", "what's this song",
                                "who is this"],
        "PlayAnythingIntent": ["play {query}", "i want to hear {query}", "search for {query}",
                               "find {query}", "put on {query}"],
    },
}

# ---- Frases de My Media for Alexa que faltaban (todas funcionan tambien con
#      "Alexa, abre mi colección reproduzca/ponga ..." gracias a SUBJ)
_V = ("pon", "reproduce")


def _both(*tpls):
    """'{v} la pista {song}' -> con pon y con reproduce."""
    return [t.format(v=v, song="{song}", album="{album}", artist="{artist}",
                     playlist="{playlist}", genre="{genre}", station="{station}",
                     book="{book}", query="{query}") for t in tpls for v in _V]


def _add(lang, intent, samples):
    U[lang].setdefault(intent, [])
    U[lang][intent] += [s for s in samples if s not in U[lang][intent]]


_add("es", "PlayAlbumIntent", _both(
    "{v} álbum {album}", "{v} disco {album}", "{v} música del álbum {album}",
    "{v} canciones del álbum {album}", "{v} el álbum {album} entero"))
_add("es", "PlaySongIntent", _both(
    "{v} pista {song}", "{v} canción {song}", "{v} audio {song}",
    "{v} pista {song} de {artist}", "{v} canción {song} de {artist}",
    "{v} la canción {song} de {artist}", "{v} {song} de {artist}",
    "{v} {song} del álbum {album}", "{v} la canción {song} del álbum {album}",
    "{v} la pista {song} del álbum {album}"))
_add("es", "PlayArtistIntent", _both("{v} canciones de {artist}", "{v} temas de {artist}"))
_add("es", "PlayPlaylistIntent", _both(
    "{v} playlist {playlist}", "{v} mi playlist {playlist}", "{v} la playlist {playlist}",
    "{v} playlist itunes {playlist}", "{v} mi playlist itunes {playlist}",
    "{v} la playlist itunes {playlist}", "{v} la playlist {playlist} de itunes",
    "{v} la playlist {playlist} en itunes", "{v} mi lista {playlist}"))
_add("es", "PlayGenreIntent", _both(
    "{v} algo de música {genre}", "{v} canciones {genre}", "{v} música de {genre}"))
_add("es", "RepeatModeOnIntent", [
    f"{v} {m}" for v in ("activa", "enciende")
    for m in ("la repetición", "repetición", "el modo repetición", "modo repetición",
              "el modo loop", "modo loop", "looping", "el bucle")])
_add("es", "RepeatModeOffIntent", [
    f"{v} {m}" for v in ("desactiva", "apaga", "quita")
    for m in ("la repetición", "repetición", "el modo repetición", "modo repetición",
              "el modo loop", "modo loop", "looping", "el bucle")])
_add("es", "ShuffleModeOnIntent", [
    f"{v} {m}" for v in ("activa", "enciende")
    for m in ("el aleatorio", "aleatorio", "el modo aleatorio", "modo aleatorio",
              "shuffle", "el modo shuffle", "modo shuffle", "la reproducción aleatoria")])
_add("es", "ShuffleModeOffIntent", [
    f"{v} {m}" for v in ("desactiva", "apaga", "quita")
    for m in ("el aleatorio", "aleatorio", "el modo aleatorio", "modo aleatorio",
              "shuffle", "el modo shuffle", "modo shuffle", "la reproducción aleatoria")])
_add("es", "ShuffleAlbumIntent", _both(
    "{v} aleatoriamente el álbum {album}", "{v} aleatoriamente álbum {album}",
    "{v} aleatoriamente {album} el álbum", "{v} aleatoriamente música del álbum {album}",
    "{v} el álbum {album} en aleatorio", "{v} el álbum {album} aleatoriamente",
    "{v} el disco {album} en aleatorio"))
_add("es", "ShuffleArtistIntent", _both(
    "{v} aleatoriamente música de {artist}", "{v} aleatoriamente canciones de {artist}",
    "{v} aleatoriamente a {artist}", "{v} música de {artist} en aleatorio",
    "{v} canciones de {artist} en aleatorio"))
_add("es", "ShufflePlaylistIntent", _both(
    "{v} aleatoriamente playlist {playlist}", "{v} aleatoriamente la playlist {playlist}",
    "{v} aleatoriamente mi playlist {playlist}", "{v} aleatoriamente la lista {playlist}",
    "{v} aleatoriamente mi playlist itunes {playlist}",
    "{v} aleatoriamente la playlist {playlist} de itunes",
    "{v} la playlist {playlist} en aleatorio", "{v} la lista {playlist} en aleatorio"))
_add("es", "ShuffleGenreIntent", _both(
    "{v} aleatoriamente música {genre}", "{v} aleatoriamente algo de música {genre}",
    "{v} música {genre} en aleatorio"))
_add("es", "ShuffleAnythingIntent", _both("{v} aleatoriamente {query}", "{v} en aleatorio {query}"))
_add("es", "PlayThisIntent", _both(
    "{v} esta", "{v} esto", "{v} esta canción", "{v} esta pista", "{v} esta música",
    "{v} lo que se muestra", "{v} lo que está en mi pantalla", "{v} la selección actual"))
_add("es", "PlayCurrentAlbumIntent", ["reproduce este álbum", "reproduce este disco"])
_add("es", "PlayMoreByArtistIntent", ["pon este artista", "reproduce este artista"])
_add("es", "IgnoreTrackIntent", [
    "ignora esta canción", "ignora esta pista", "ignora lo que se está reproduciendo",
    "ignora esto", "olvida esta canción", "olvida esta pista", "desindexa esta canción",
    "desindexa esta pista"] + [
    f"no {v} {w}{e}" for v in ("pongas", "ponga", "reproduzcas", "reproduzca")
    for w in ("esta", "esto", "esta canción", "esta pista")
    for e in (" de nuevo", " más")] + [
    f"no {v} más {w}" for v in ("pongas", "ponga", "reproduzcas", "reproduzca")
    for w in ("esta", "esto", "esta canción", "esta pista")] + [
    "no reproducir esta de nuevo", "no reproducir esto de nuevo"])
_add("es", "AddToPlaylistIntent", [
    f"añade {w} a {p} {{playlist}}" for w in ("esta", "esta pista", "esta canción", "esto")
    for p in ("mi playlist", "la playlist", "playlist", "mi lista", "la lista",
              "mi playlist itunes", "la playlist itunes")] + [
    "añade esta a la playlist {playlist} de itunes", "añade esta canción a la lista {playlist}",
    "guarda esta en la lista {playlist}", "guarda esta canción en la lista {playlist}"])
_add("es", "PlayStreamIntent", _both(
    "{v} la radio {station}", "{v} radio {station}", "{v} la emisora {station}",
    "{v} emisora {station}", "{v} mi stream {station}", "{v} el stream {station}",
    "{v} stream {station}", "{v} mi flujo {station}", "{v} el flujo {station}",
    "{v} flujo {station}", "{v} mi stream web {station}", "{v} mi flujo web {station}",
    "{v} el stream web {station}", "{v} stream web {station}",
    "{v} mi stream internet {station}", "{v} stream internet {station}",
    "{v} la radio internet {station}", "{v} radio internet {station}",
    "{v} la emisora internet {station}", "{v} emisora internet {station}",
    "{v} la emisora de radio internet {station}", "{v} emisora de radio internet {station}",
    "{v} mi playlist web {station}", "{v} la playlist web {station}",
    "{v} playlist web {station}", "{v} mi playlist internet {station}",
    "{v} la playlist internet {station}", "{v} playlist internet {station}",
    "{v} {station} de internet", "{v} {station} de la web", "{v} {station} de web") + [
    "stream {station} de internet", "stream {station} de la web", "stream {station} de web"])
_add("es", "ReadBookIntent", [
    "lee {book}", "lee el libro {book}", "lee el audiolibro {book}", "pon el audiolibro {book}",
    "pon el libro {book}", "reproduce el audiolibro {book}", "continúa el libro {book}",
    "sigue con el libro {book}", "quiero escuchar el libro {book}"])
_add("es", "WhatIsPlayingIntent", [
    "qué se está reproduciendo", "qué está reproduciendo", "qué es esta pista",
    "cuál es esta pista", "quién está cantando", "quién canta"])
_add("es", "ServerInfoIntent", [
    "lista mis servidores", "qué servidores puedo usar", "qué servidores puedo acceder",
    "dime mis servidores", "cuál es mi servidor actual", "cuál es mi servidor activo",
    "qué servidor está activo", "cuál es el servidor actual", "cuál es el servidor activo",
    "qué servidores puedo registrar", "qué servidores se pueden registrar",
    "cambia servidor", "cambia de servidor", "cambia servidores", "cambia de servidores",
    "conmuta servidor", "conmuta de servidor", "conmuta servidores", "conmuta de servidores"])
_add("es", "FamilyIntent", [
    "lista mis invitaciones", "dime mis invitaciones", "dame mis invitaciones",
    "qué puedo registrar", "si tengo algunos registros pendientes",
    "si tengo algunos servidores pendientes", "tengo invitaciones pendientes"])

_add("en", "RepeatModeOnIntent", ["turn on repeat", "turn on looping", "enable loop mode",
                                  "turn repeat on", "enable repeat"])
_add("en", "RepeatModeOffIntent", ["turn off repeat", "turn off looping", "disable loop mode",
                                   "turn repeat off", "disable repeat"])
_add("en", "ShuffleModeOnIntent", ["turn on shuffle", "enable shuffle mode", "turn shuffle on"])
_add("en", "ShuffleModeOffIntent", ["turn off shuffle", "disable shuffle mode",
                                    "turn shuffle off"])
_add("en", "ShuffleAlbumIntent", ["shuffle the album {album}", "shuffle album {album}"])
_add("en", "ShuffleArtistIntent", ["shuffle music by {artist}", "shuffle songs by {artist}"])
_add("en", "ShufflePlaylistIntent", ["shuffle the playlist {playlist}",
                                     "shuffle my playlist {playlist}"])
_add("en", "ShuffleGenreIntent", ["shuffle {genre} music"])
_add("en", "ShuffleAnythingIntent", ["shuffle play {query}", "play {query} on shuffle"])
_add("en", "PlayThisIntent", ["play this", "play this song", "play this track",
                              "play what's on my screen", "play the current selection"])
_add("en", "IgnoreTrackIntent", ["ignore this song", "ignore this track",
                                 "don't play this again", "never play this song again",
                                 "forget this song"])
_add("en", "AddToPlaylistIntent", ["add this to my playlist {playlist}",
                                   "add this song to the playlist {playlist}",
                                   "add this track to playlist {playlist}"])
_add("en", "PlayStreamIntent", ["play the radio {station}", "play the station {station}",
                                "play my stream {station}", "play internet radio {station}",
                                "play {station} from the internet"])
_add("en", "ReadBookIntent", ["read {book}", "read the book {book}",
                              "play the audiobook {book}", "continue the book {book}"])
_add("en", "WhatIsPlayingIntent", ["who is singing", "what track is this"])
_add("en", "ServerInfoIntent", ["list my servers", "what is my current server",
                                "which server is active", "switch server"])
_add("en", "FamilyIntent", ["list my invitations", "do i have pending invitations"])

# conjugaciones para "Alexa, pide a mi colección que PONGA..." y para la forma de
# My Media "Alexa, abre mi colección PONGA/REPRODUZCA..."
SUBJ = {"pon ": "ponga ", "reproduce ": "reproduzca ", "busca ": "busque ",
        "toca ": "toque ", "mezcla ": "mezcle ", "abre ": "abra ",
        "sorpréndeme": "me sorprenda", "activa ": "active ", "enciende ": "encienda ",
        "desactiva ": "desactive ", "apaga ": "apague ", "quita ": "quite ",
        "ignora ": "ignore ", "olvida ": "olvide ", "desindexa ": "desindexe ",
        "añade ": "añada ", "guarda ": "guarde ", "lee ": "lea ", "continúa ": "continúe ",
        "sigue ": "siga ", "lista ": "liste ", "dime ": "me diga ", "dame ": "me dé ",
        "cambia ": "cambie ", "conmuta ": "conmute "}

SLOTS = {
    "PlayArtistIntent": {"artist": "ARTIST_NAME"},
    "PlayAlbumIntent": {"album": "ALBUM_NAME", "artist": "ARTIST_NAME"},
    "PlaySongIntent": {"song": "SONG_NAME", "artist": "ARTIST_NAME", "album": "ALBUM_NAME"},
    "PlayGenreIntent": {"genre": "GENRE_NAME"},
    "PlayPlaylistIntent": {"playlist": "PLAYLIST_NAME"},
    "PlayFolderIntent": {"folder": "FOLDER_NAME"},
    "PlayYearIntent": {"year": "AMAZON.FOUR_DIGIT_NUMBER"},
    "PlayDecadeIntent": {"decade": "DECADE"},
    "PlayAnythingIntent": {"query": "AMAZON.SearchQuery"},
    "ShuffleAlbumIntent": {"album": "ALBUM_NAME"},
    "ShuffleArtistIntent": {"artist": "ARTIST_NAME"},
    "ShufflePlaylistIntent": {"playlist": "PLAYLIST_NAME"},
    "ShuffleGenreIntent": {"genre": "GENRE_NAME"},
    "ShuffleAnythingIntent": {"query": "AMAZON.SearchQuery"},
    "AddToPlaylistIntent": {"playlist": "PLAYLIST_NAME"},
    "PlayStreamIntent": {"station": "STATION_NAME"},
    "ReadBookIntent": {"book": "ALBUM_NAME"},
}

SAMPLES = {
    "es": {"ARTIST_NAME": ["Estopa", "Queen", "Rosalía", "Los Beatles", "Alejandro Sanz",
                           "Coldplay", "Mecano", "Bad Bunny", "AC DC", "Héroes del Silencio"],
           "ALBUM_NAME": ["Thriller", "Abbey Road", "El Mal Querer", "Descanso dominical",
                          "Back in Black", "Dark Side of the Moon"],
           "SONG_NAME": ["Bohemian Rhapsody", "La Flaca", "Despacito", "Hijo de la Luna",
                         "Entre dos tierras", "Imagine"],
           "GENRE_NAME": ["rock", "pop", "jazz", "flamenco", "clásica", "reggaeton", "electrónica",
                          "blues", "metal", "indie", "salsa", "hip hop"],
           "PLAYLIST_NAME": ["favoritas", "viaje", "fiesta", "relax", "gimnasio", "cena"],
           "FOLDER_NAME": ["descargas", "vinilos", "bandas sonoras", "conciertos"],
           "STATION_NAME": ["radio tres", "los cuarenta", "radio clásica", "jazz radio"]},
    "en": {"ARTIST_NAME": ["Queen", "The Beatles", "Taylor Swift", "Coldplay", "AC DC",
                           "Pink Floyd", "Adele", "Drake", "Radiohead", "Daft Punk"],
           "ALBUM_NAME": ["Thriller", "Abbey Road", "Back in Black", "Dark Side of the Moon",
                          "Rumours", "Nevermind"],
           "SONG_NAME": ["Bohemian Rhapsody", "Imagine", "Hey Jude", "Billie Jean",
                         "Smells Like Teen Spirit", "Hotel California"],
           "GENRE_NAME": ["rock", "pop", "jazz", "classical", "country", "electronic", "blues",
                          "metal", "indie", "hip hop", "soul", "reggae"],
           "PLAYLIST_NAME": ["favorites", "road trip", "party", "chill", "workout", "dinner"],
           "FOLDER_NAME": ["downloads", "vinyl rips", "soundtracks", "live"],
           "STATION_NAME": ["jazz radio", "classic fm", "radio paradise", "lofi radio"]},
}

DECADES = {
    "es": [(1950, ["cincuenta", "años cincuenta"]), (1960, ["sesenta", "años sesenta"]),
           (1970, ["setenta", "años setenta"]), (1980, ["ochenta", "años ochenta"]),
           (1990, ["noventa", "años noventa"]),
           (2000, ["dos mil", "años dos mil"]),
           (2010, ["dos mil diez", "años diez"]),
           (2020, ["dos mil veinte", "años veinte"])],
    "en": [(1950, ["fifties", "nineteen fifties"]), (1960, ["sixties"]),
           (1970, ["seventies"]), (1980, ["eighties"]), (1990, ["nineties"]),
           (2000, ["two thousands", "noughties"]), (2010, ["twenty tens"]),
           (2020, ["twenty twenties"])],
}

BUILTINS = ["AMAZON.CancelIntent", "AMAZON.HelpIntent", "AMAZON.StopIntent",
            "AMAZON.NavigateHomeIntent", "AMAZON.FallbackIntent", "AMAZON.PauseIntent",
            "AMAZON.ResumeIntent", "AMAZON.NextIntent", "AMAZON.PreviousIntent",
            "AMAZON.ShuffleOnIntent", "AMAZON.ShuffleOffIntent", "AMAZON.LoopOnIntent",
            "AMAZON.LoopOffIntent", "AMAZON.StartOverIntent", "AMAZON.RepeatIntent"]

TYPE_FOR_NAMES = {"ARTIST_NAME": "artists", "ALBUM_NAME": "albums", "SONG_NAME": "songs",
                  "GENRE_NAME": "genres", "PLAYLIST_NAME": "playlists", "FOLDER_NAME": "folders",
                  "STATION_NAME": "stations"}


def _clean(v):
    """Alexa solo acepta letras, numeros, espacios, apostrofes y puntos en los valores."""
    v = re.sub(r"\(.*?\)|\[.*?\]", " ", v)
    v = v.replace("&", " and ").replace("/", " ").replace("-", " ").replace("_", " ")
    v = re.sub(r"[^\w\s'.]", " ", v, flags=re.UNICODE)
    v = re.sub(r"\s+", " ", v).strip()
    return v[:140]


def _expand(utts, lang):
    out = list(utts)
    if lang == "es":
        for u in utts:
            for a, b in SUBJ.items():
                if u.startswith(a) or u == a.strip():
                    out.append(b + u[len(a):] if u != a.strip() else b)
    # sin duplicados, manteniendo orden
    seen, res = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            res.append(u)
    return res


def build(locale="es-ES", names=None, per_type=2500):
    lang = "es" if locale.lower().startswith("es") else "en"
    intents = []
    for name, utts in U[lang].items():
        it = {"name": name, "samples": _expand(utts, lang)}
        slots = SLOTS.get(name)
        if slots:
            used = {s for u in utts for s in re.findall(r"\{(\w+)\}", u)}
            it["slots"] = [{"name": s, "type": t} for s, t in slots.items() if s in used]
        intents.append(it)
    intents += [{"name": b, "samples": []} for b in BUILTINS]

    types = []
    for tname, key in TYPE_FOR_NAMES.items():
        vals = []
        if names:
            seen = set()
            for v in names.get(key, []):
                c = _clean(v or "")
                if c and c.lower() not in seen:
                    seen.add(c.lower())
                    vals.append(c)
                if len(vals) >= per_type:
                    break
        if len(vals) < 5:
            vals += [v for v in SAMPLES[lang][tname] if v not in vals]
        types.append({"name": tname, "values": [{"name": {"value": v}} for v in vals]})
    types.append({"name": "DECADE", "values": [
        {"id": str(y), "name": {"value": syn[0], "synonyms": syn[1:]}}
        for y, syn in DECADES[lang]]})

    lm = {"invocationName": INVOCATION[lang], "intents": intents, "types": types}
    # Sensibilidad baja del FallbackIntent: con nombres de musica raros, Alexa prefiere
    # mandar la frase a la skill (que busca por parecido) antes que decir "no te entiendo".
    # Amazon solo lo permite en ingles y aleman ("Unsupported model configuration").
    if locale.lower().startswith(("en", "de")):
        lm["modelConfiguration"] = {"fallbackIntentSensitivity": {"level": "LOW"}}
    return {"interactionModel": {"languageModel": lm}}


ALL_LOCALES = ("es-ES", "es-MX", "es-US", "en-US", "en-GB", "en-CA", "en-AU", "en-IN")


def manifest(public_url="https://TU-DOMINIO", only=None, ssl_type="Trusted"):
    """only: lista de idiomas a incluir (por defecto todos). Con SMAPI conviene poner
    solo los idiomas a los que se les sube modelo de voz."""
    base = (public_url or "https://TU-DOMINIO").rstrip("/")

    def loc(name, summary, desc, phrases):
        return {"name": name, "summary": summary, "description": desc,
                "examplePhrases": phrases, "keywords": ["música", "music", "media"]}

    es = loc("Mi Colección", "Tu música de la Raspberry Pi en Alexa",
             "Reproduce la música de tu Raspberry Pi o NAS en tus dispositivos Echo.",
             ["Alexa, abre mi colección", "Alexa, pide a mi colección que ponga Queen",
              "Alexa, pide a mi colección que ponga el álbum Thriller"])
    en = loc("My Collection", "Your Raspberry Pi music on Alexa",
             "Play the music stored on your Raspberry Pi or NAS on your Echo devices.",
             ["Alexa, open my collection", "Alexa, ask my collection to play Queen",
              "Alexa, ask my collection to play the album Thriller"])
    locales = {l: (es if l.startswith("es") else en) for l in (only or ALL_LOCALES)}
    return {"manifest": {
        "manifestVersion": "1.0",
        "publishingInformation": {"locales": locales, "isAvailableWorldwide": True,
                                  "testingInstructions": "Skill privada de Local Media."},
        "privacyAndCompliance": {"allowsPurchases": False, "usesPersonalInfo": False,
                                 "isChildDirected": False, "isExportCompliant": True,
                                 "containsAds": False,
                                 "locales": {l: {"privacyPolicyUrl": f"{base}/privacidad"}
                                             for l in locales}},
        "apis": {"custom": {
            "endpoint": {"uri": f"{base}/alexa", "sslCertificateType": ssl_type},
            "interfaces": [{"type": "AUDIO_PLAYER"}]}},
    }}


def ssl_certificate_type(public_url):
    """Alexa distingue certificados normales ("Trusted") de los comodin ("Wildcard",
    p. ej. *.ngrok-free.dev o *.trycloudflare.com). Si se indica el tipo equivocado,
    Alexa ni siquiera llama a la skill ("No puedo conectar con la skill")."""
    host = urllib.parse.urlparse(public_url or "").hostname
    if not host:
        return "Trusted"
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
    except (OSError, ssl.SSLError):
        return "Trusted"
    names = [v.lower() for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    if host.lower() in names:
        return "Trusted"
    return "Wildcard" if any(n.startswith("*.") for n in names) else "Trusted"
