"""Normalizacion de texto y busqueda aproximada (lo que Alexa oye nunca es exacto)."""
import re
import unicodedata
from difflib import SequenceMatcher

ARTICLES = {"the", "el", "la", "los", "las", "le", "les", "die", "der", "das",
            "il", "lo", "gli", "a", "an", "un", "una"}
CONNECTORS = {"and", "y", "e", "und", "et"}
NUM_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "cero": "0", "uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5",
    "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10",
}


def norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " ").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    words = [NUM_WORDS.get(w, w) for w in s.split() if w not in CONNECTORS]
    if len(words) > 1 and words[0] in ARTICLES:
        words = words[1:]
    return " ".join(words)


def score(q, cand):
    """Parecido entre consulta y candidato, ambos ya normalizados (0..1)."""
    if not q or not cand:
        return 0.0
    if q == cand:
        return 1.0
    qc, cc = q.replace(" ", ""), cand.replace(" ", "")
    if qc == cc:
        return 0.98
    r = SequenceMatcher(None, qc, cc).ratio()
    qt, ct = q.split(), cand.split()
    if set(qt) <= set(ct):
        r = max(r, 0.72 + 0.25 * len(qt) / len(ct))
    elif set(ct) <= set(qt) and len(ct) >= 2:
        r = max(r, 0.7)
    if len(qc) >= 4 and cc.startswith(qc):
        r = max(r, 0.85)
    # "acdc" frente a "a c d c" / "ac dc"
    if len(qc) >= 3 and qc in cc:
        r = max(r, 0.6 + 0.35 * len(qc) / len(cc))
    return min(r, 0.97)


def best(q, items, key=lambda x: x, threshold=0.62, limit=10):
    """items: iterable; key(item) -> texto normalizado. Devuelve [(score, item)]."""
    q = norm(q)
    out = []
    for it in items:
        s = score(q, key(it))
        if s >= threshold:
            out.append((s, it))
    out.sort(key=lambda x: -x[0])
    return out[:limit]
