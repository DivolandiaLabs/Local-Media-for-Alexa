"""Genera el modelo de interaccion de la skill (JSON para la consola de Alexa).

Con library=None usa valores de ejemplo; con la biblioteca, rellena los tipos de slot
con tus artistas, albumes, canciones... (mejora mucho el reconocimiento)."""
import re

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
                           "reproduce el tema {song}"],
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
                           "play the track {song} by {artist}", "i want to hear the song {song}"],
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

# conjugaciones para "Alexa, pide a mi colección que PONGA..."
SUBJ = {"pon ": "ponga ", "reproduce ": "reproduzca ", "busca ": "busque ",
        "toca ": "toque ", "mezcla ": "mezcle ", "sorpréndeme": "me sorprenda"}

SLOTS = {
    "PlayArtistIntent": {"artist": "ARTIST_NAME"},
    "PlayAlbumIntent": {"album": "ALBUM_NAME", "artist": "ARTIST_NAME"},
    "PlaySongIntent": {"song": "SONG_NAME", "artist": "ARTIST_NAME"},
    "PlayGenreIntent": {"genre": "GENRE_NAME"},
    "PlayPlaylistIntent": {"playlist": "PLAYLIST_NAME"},
    "PlayFolderIntent": {"folder": "FOLDER_NAME"},
    "PlayYearIntent": {"year": "AMAZON.FOUR_DIGIT_NUMBER"},
    "PlayDecadeIntent": {"decade": "DECADE"},
    "PlayAnythingIntent": {"query": "AMAZON.SearchQuery"},
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
           "FOLDER_NAME": ["descargas", "vinilos", "bandas sonoras", "conciertos"]},
    "en": {"ARTIST_NAME": ["Queen", "The Beatles", "Taylor Swift", "Coldplay", "AC DC",
                           "Pink Floyd", "Adele", "Drake", "Radiohead", "Daft Punk"],
           "ALBUM_NAME": ["Thriller", "Abbey Road", "Back in Black", "Dark Side of the Moon",
                          "Rumours", "Nevermind"],
           "SONG_NAME": ["Bohemian Rhapsody", "Imagine", "Hey Jude", "Billie Jean",
                         "Smells Like Teen Spirit", "Hotel California"],
           "GENRE_NAME": ["rock", "pop", "jazz", "classical", "country", "electronic", "blues",
                          "metal", "indie", "hip hop", "soul", "reggae"],
           "PLAYLIST_NAME": ["favorites", "road trip", "party", "chill", "workout", "dinner"],
           "FOLDER_NAME": ["downloads", "vinyl rips", "soundtracks", "live"]},
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
                  "GENRE_NAME": "genres", "PLAYLIST_NAME": "playlists", "FOLDER_NAME": "folders"}


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

    return {"interactionModel": {"languageModel": {
        "invocationName": INVOCATION[lang], "intents": intents, "types": types}}}


ALL_LOCALES = ("es-ES", "es-MX", "es-US", "en-US", "en-GB", "en-CA", "en-AU", "en-IN")


def manifest(public_url="https://TU-DOMINIO", only=None):
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
            "endpoint": {"uri": f"{base}/alexa", "sslCertificateType": "Trusted"},
            "interfaces": [{"type": "AUDIO_PLAYER"}]}},
    }}
