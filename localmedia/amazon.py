"""Conectar con Amazon: inicia sesion con Login with Amazon y usa la API de skills
(SMAPI) para crear y mantener la skill del usuario sin pasar por la consola.

Necesita un perfil de seguridad de Login with Amazon del propio usuario (Client ID y
Client Secret) con la URL de retorno https://<url-publica>/amazon/callback.
https://developer.amazon.com/docs/smapi/get-access-token-smapi.html
"""
import hashlib
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import skillmodel

log = logging.getLogger("localmedia.amazon")

AUTH_URL = "https://www.amazon.com/ap/oa"
TOKEN_URL = "https://api.amazon.com/auth/o2/token"
SMAPI = "https://api.amazonalexa.com"
SCOPES = "alexa::ask:skills:readwrite alexa::ask:models:readwrite alexa::ask:skills:test"


class AmazonError(Exception):
    pass


class Amazon:
    def __init__(self, cfg, lib):
        self.cfg = cfg
        self.lib = lib
        self._states = {}
        self._lock = threading.Lock()
        self.job = {"running": False, "kind": "", "steps": [], "error": None,
                    "started": None, "finished": None}

    # ------------------------------------------------------------ estado
    def redirect_uri(self):
        return self.cfg.public_base() + "/amazon/callback"

    def privacy_url(self):
        return self.cfg.public_base() + "/privacidad"

    def acc(self):
        return dict(self.cfg["amazon"] or {})

    def connected(self):
        return bool(self.acc().get("refresh_token"))

    def state(self):
        a = self.acc()
        return {
            "configured": bool(self.cfg["lwa_client_id"] and self.cfg["lwa_client_secret"]),
            "client_id": self.cfg["lwa_client_id"],
            "connected": self.connected(),
            "vendor_name": a.get("vendor_name"),
            "skill_id": a.get("skill_id"),
            "connected_at": a.get("connected_at"),
            "redirect_uri": self.redirect_uri() if self.cfg.public_base() else "",
            "privacy_url": self.privacy_url() if self.cfg.public_base() else "",
            "public_ok": self.cfg.public_base().startswith("https://"),
            "locales": self.cfg["skill_locales"],
            "auto_model": self.cfg["amazon_auto_model"],
            "job": self.job,
        }

    # ------------------------------------------------------------ inicio de sesion
    def login_url(self):
        if not (self.cfg["lwa_client_id"] and self.cfg["lwa_client_secret"]):
            raise AmazonError("Falta el Client ID o el Client Secret del perfil de seguridad.")
        if not self.cfg.public_base().startswith("https://"):
            raise AmazonError("Primero pon la URL pública (https://…) de tu Raspberry.")
        st = secrets.token_urlsafe(24)
        now = time.time()
        with self._lock:
            self._states = {k: v for k, v in self._states.items() if v > now}
            self._states[st] = now + 900
        q = {"client_id": self.cfg["lwa_client_id"], "scope": SCOPES, "response_type": "code",
             "redirect_uri": self.redirect_uri(), "state": st}
        return AUTH_URL + "?" + urllib.parse.urlencode(q)

    def callback(self, code, state, error=None):
        if error:
            raise AmazonError(f"Amazon ha cancelado el inicio de sesión ({error}).")
        with self._lock:
            exp = self._states.pop(state or "", 0)
        if exp < time.time():
            raise AmazonError("El enlace ha caducado o no es válido. "
                              "Vuelve a pulsar «Conectar con Amazon».")
        if not code:
            raise AmazonError("Amazon no ha devuelto ningún código.")
        self._save_tokens(self._token({"grant_type": "authorization_code", "code": code,
                                       "redirect_uri": self.redirect_uri()}))
        vendors = self._api("GET", "/v1/vendors").get("vendors") or []
        if not vendors:
            raise AmazonError("Tu cuenta aún no es de desarrollador de Alexa. Entra una vez en "
                              "developer.amazon.com con esa cuenta, acepta las condiciones y "
                              "vuelve a conectar.")
        a = self.acc()
        a.update(vendor_id=vendors[0]["id"], vendor_name=vendors[0].get("name"),
                 connected_at=time.time())
        self.cfg.update({"amazon": a})
        log.info("Conectado con Amazon (%s)", a["vendor_name"])

    def disconnect(self):
        a = self.acc()
        # se recuerda la skill para no crear otra al volver a conectar
        self.cfg.update({"amazon": {"skill_id": a["skill_id"]} if a.get("skill_id") else {}})

    # ------------------------------------------------------------ tokens y API
    def _token(self, data):
        data = dict(data, client_id=self.cfg["lwa_client_id"],
                    client_secret=self.cfg["lwa_client_secret"])
        req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(data).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read())
                msg = err.get("error_description") or err.get("error")
            except ValueError:
                msg = str(e)
            if "invalid_client" in str(msg) or e.code == 401:
                msg = f"{msg}. Revisa el Client ID y el Client Secret."
            raise AmazonError(f"Amazon rechaza el inicio de sesión: {msg}")
        except urllib.error.URLError as e:
            raise AmazonError(f"No se puede contactar con Amazon: {e.reason}")

    def _save_tokens(self, tok):
        a = self.acc()
        a["access_token"] = tok["access_token"]
        a["expires"] = time.time() + int(tok.get("expires_in", 3600)) - 60
        if tok.get("refresh_token"):
            a["refresh_token"] = tok["refresh_token"]
        self.cfg.update({"amazon": a})

    def _access(self):
        a = self.acc()
        if not a.get("refresh_token"):
            raise AmazonError("No estás conectado con Amazon.")
        if a.get("access_token") and a.get("expires", 0) > time.time():
            return a["access_token"]
        self._save_tokens(self._token({"grant_type": "refresh_token",
                                       "refresh_token": a["refresh_token"]}))
        return self.acc()["access_token"]

    def _api(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(SMAPI + path, data=data, method=method, headers={
            "Authorization": self._access(), "Content-Type": "application/json",
            "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                out = json.loads(raw) if raw.strip() else {}
                if isinstance(out, dict):
                    out["_location"] = r.headers.get("Location")
                return out
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                err = json.loads(raw)
                msg = err.get("message") or str(err)
                for v in err.get("violations") or []:
                    msg += f" · {v.get('message')}"
            except ValueError:
                msg = raw[:300].decode(errors="ignore") or str(e)
            raise AmazonApiError(e.code, msg)
        except urllib.error.URLError as e:
            raise AmazonError(f"No se puede contactar con Amazon: {e.reason}")

    # ------------------------------------------------------------ trabajos en segundo plano
    def _step(self, text):
        log.info("Amazon: %s", text)
        self.job["steps"].append({"t": time.time(), "text": text})

    def _run(self, kind, fn, *args):
        if self.job["running"]:
            return False
        self.job.update(running=True, kind=kind, steps=[], error=None, started=time.time(),
                        finished=None)

        def work():
            try:
                fn(*args)
            except AmazonError as e:
                self.job["error"] = str(e)
                log.warning("Amazon: %s", e)
            except Exception as e:  # noqa: BLE001 - se muestra en la web
                log.exception("Amazon")
                self.job["error"] = f"Error inesperado: {e}"
            finally:
                self.job.update(running=False, finished=time.time())

        threading.Thread(target=work, daemon=True).start()
        return True

    def start_setup(self):
        return self._run("setup", self._setup)

    def start_model_update(self, only_if_changed=False):
        return self._run("model", self._update_models, only_if_changed)

    def auto_update_after_scan(self):
        if self.connected() and self.acc().get("skill_id") and self.cfg["amazon_auto_model"]:
            self.start_model_update(only_if_changed=True)

    # ------------------------------------------------------------ crear / actualizar la skill
    def _locales(self):
        locs = [l for l in (self.cfg["skill_locales"] or []) if l in skillmodel.ALL_LOCALES]
        return locs or ["es-ES"]

    def _setup(self):
        base = self.cfg.public_base()
        if not base.startswith("https://"):
            raise AmazonError("Falta la URL pública https.")
        a = self.acc()
        if not a.get("vendor_id"):
            raise AmazonError("No estás conectado con Amazon.")
        locales = self._locales()
        man = skillmodel.manifest(base, locales)
        sid = a.get("skill_id")
        if sid:
            try:
                self._api("GET", f"/v1/skills/{sid}/stages/development/manifest")
            except AmazonApiError as e:
                if e.status in (403, 404):
                    self._step("La skill guardada ya no existe en tu cuenta: creo una nueva.")
                    sid = None
                else:
                    raise
        if sid:
            self._step("Actualizando tu skill (nombre, dirección, reproductor de audio)…")
            self._api("PUT", f"/v1/skills/{sid}/stages/development/manifest", man)
        else:
            self._step("Creando tu skill «Mi Colección»…")
            r = self._api("POST", "/v1/skills", dict(man, vendorId=a["vendor_id"]))
            sid = r.get("skillId")
            if not sid:
                raise AmazonError("Amazon no ha devuelto el identificador de la skill.")
            a = self.acc()
            a["skill_id"] = sid
            self.cfg.update({"amazon": a})
        self._wait(sid, "manifest")
        self._upload_models(sid, locales)
        self._step("Activando la skill en tus dispositivos Echo…")
        self._api("PUT", f"/v1/skills/{sid}/stages/development/enablement")
        ids = [i for i in (self.cfg["skill_ids"] or []) if i]
        if sid not in ids:
            self.cfg.update({"skill_ids": ids + [sid]})
        self._step("¡Listo! Di «Alexa, abre mi colección».")

    def _update_models(self, only_if_changed):
        sid = self.acc().get("skill_id")
        if not sid:
            raise AmazonError("Todavía no hay skill creada. Pulsa «Crear mi skill».")
        locales = self._locales()
        names = self.lib.names_for_model()
        h = hashlib.sha1(json.dumps([names, locales], sort_keys=True).encode()).hexdigest()
        if only_if_changed and h == self.acc().get("model_hash"):
            self._step("El modelo de voz ya estaba al día.")
            return
        self._upload_models(sid, locales, names)
        self._step("Modelo de voz actualizado.")

    def _upload_models(self, sid, locales, names=None):
        names = names if names is not None else self.lib.names_for_model()
        for loc in locales:
            self._step(f"Subiendo el modelo de voz con tu biblioteca ({loc})…")
            self._api("PUT", f"/v1/skills/{sid}/stages/development/interactionModel/locales/{loc}",
                      skillmodel.build(loc, names))
        for loc in locales:
            self._step(f"Amazon está preparando el modelo de voz ({loc}). Tarda 1–2 minutos…")
            self._wait(sid, "interactionModel", loc)
        a = self.acc()
        a["model_hash"] = hashlib.sha1(json.dumps([names, locales], sort_keys=True)
                                       .encode()).hexdigest()
        self.cfg.update({"amazon": a})

    def _wait(self, sid, resource, locale=None, timeout=600):
        end = time.time() + timeout
        while time.time() < end:
            r = self._api("GET", f"/v1/skills/{sid}/status?resource={resource}")
            node = r.get(resource) or {}
            if locale:
                node = node.get(locale) or {}
            last = node.get("lastUpdateRequest") or {}
            st = last.get("status")
            if st == "SUCCEEDED":
                return
            if st == "FAILED":
                errs = "; ".join(e.get("message", "") for e in last.get("errors") or [])
                raise AmazonError(f"Amazon no ha aceptado el cambio ({resource}): {errs}")
            time.sleep(3)
        raise AmazonError("Amazon está tardando demasiado. Vuelve a intentarlo en unos minutos.")


class AmazonApiError(AmazonError):
    def __init__(self, status, msg):
        super().__init__(f"Amazon responde {status}: {msg}")
        self.status = status
