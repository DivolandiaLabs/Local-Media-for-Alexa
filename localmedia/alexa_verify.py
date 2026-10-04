"""Verificacion de que la peticion viene de verdad de Amazon (firma + certificado).
https://developer.amazon.com/docs/custom-skills/host-a-custom-skill-as-a-web-service.html
"""
import base64
import logging
import os
import posixpath
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("localmedia.verify")

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

_cache = {}
_lock = threading.Lock()
CA_BUNDLES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
              "/etc/ssl/cert.pem")


class VerifyError(Exception):
    pass


def _check_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme.lower() != "https":
        raise VerifyError("SignatureCertChainUrl no es https")
    if (u.hostname or "").lower() != "s3.amazonaws.com":
        raise VerifyError("host del certificado incorrecto")
    if not posixpath.normpath(u.path).startswith("/echo.api/"):
        raise VerifyError("ruta del certificado incorrecta")
    if u.port not in (None, 443):
        raise VerifyError("puerto del certificado incorrecto")


def _roots():
    paths = []
    try:
        import certifi
        paths.append(certifi.where())
    except ImportError:
        pass
    paths += [p for p in CA_BUNDLES if os.path.exists(p)]
    for p in paths:
        try:
            with open(p, "rb") as f:
                return x509.load_pem_x509_certificates(f.read())
        except Exception:
            continue
    return None


def _load_chain(url):
    with _lock:
        hit = _cache.get(url)
        if hit and hit[0] > time.time():
            return hit[1]
    with urllib.request.urlopen(url, timeout=10) as r:
        pem = r.read()
    certs = x509.load_pem_x509_certificates(pem)
    leaf = certs[0]
    now = datetime.now(timezone.utc)
    nb = getattr(leaf, "not_valid_before_utc", None) or \
        leaf.not_valid_before.replace(tzinfo=timezone.utc)
    na = getattr(leaf, "not_valid_after_utc", None) or \
        leaf.not_valid_after.replace(tzinfo=timezone.utc)
    if not (nb <= now <= na):
        raise VerifyError("certificado caducado")
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if "echo-api.amazon.com" not in san.get_values_for_type(x509.DNSName):
        raise VerifyError("el certificado no es de echo-api.amazon.com")
    # Cadena hasta una CA de confianza
    try:
        from cryptography.x509.verification import PolicyBuilder, Store
        roots = _roots()
        if roots:
            verifier = PolicyBuilder().store(Store(roots)).time(now) \
                .build_server_verifier(x509.DNSName("echo-api.amazon.com"))
            verifier.verify(leaf, certs[1:])
        else:
            log.warning("No hay almacen de CAs; solo se comprueba la firma")
    except ImportError:
        for child, parent in zip(certs, certs[1:]):
            child.verify_directly_issued_by(parent)
    except Exception as e:
        raise VerifyError(f"cadena de certificados no valida: {e}")
    key = leaf.public_key()
    with _lock:
        _cache[url] = (min(time.time() + 3600, na.timestamp()), key)
    return key


def verify(headers, body, timestamp):
    """Lanza VerifyError si algo no cuadra."""
    if not HAVE_CRYPTO:
        raise VerifyError("falta el paquete 'cryptography' (pip install cryptography)")
    url = headers.get("SignatureCertChainUrl")
    sig256 = headers.get("Signature-256")
    sig = sig256 or headers.get("Signature")
    if not url or not sig:
        raise VerifyError("faltan cabeceras de firma")
    _check_url(url)
    key = _load_chain(url)
    try:
        key.verify(base64.b64decode(sig), body, padding.PKCS1v15(),
                   hashes.SHA256() if sig256 else hashes.SHA1())
    except Exception:
        raise VerifyError("firma no valida")
    try:
        ts = datetime.fromisoformat(timestamp.split(".")[0].replace("Z", "") + "+00:00")
    except Exception:
        raise VerifyError("timestamp ilegible")
    if abs((datetime.now(timezone.utc) - ts).total_seconds()) > 150:
        raise VerifyError("peticion demasiado antigua (¿hora del sistema mal?)")
