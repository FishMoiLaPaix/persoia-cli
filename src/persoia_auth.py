# VENDORÉ depuis https://github.com/FishMoiLaPaix/persoia-auth (garder synchro).
"""persoia_auth — authentification persoIA partagée pour les outils.

Un seul module, **stdlib pure** (aucune dépendance), pour que tous les outils
persoIA (scan-cartes-visites, marchéspublic, app-plan-areas…) partagent **une
seule connexion** : l'utilisateur s'identifie une fois, la clé est stockée dans
un emplacement commun, et chaque outil la relit.

API publique (c'est tout ce qu'un outil a besoin d'appeler) :

    import persoia_auth

    key = persoia_auth.get_api_key(client="scan-cartes")     # lit/obtient la clé
    headers = persoia_auth.auth_headers(client="scan-cartes")  # {Authorization, X-Persoia-Client}
    base = persoia_auth.api_base()                            # URL de base (démo/prod)

Le store partagé est `~/.config/persoia/config.env` (Linux/Mac, respecte
XDG_CONFIG_HOME) et `%APPDATA%\\persoia\\config.env` (Windows) — **le même
fichier que persoia-cli**, au format env (PERSOIA_API_KEY=…). Surchargeable par
les variables d'environnement et par PERSOIA_CONFIG.

Le login navigateur réutilise le portail persoIA : un serveur loopback éphémère
sur 127.0.0.1 reçoit la clé émise par la page `/cli` (protégée par un `state`
anti-CSRF, usage unique, CORS limité à l'origine du portail). Le mot de passe
n'est jamais vu par l'outil.
"""

from __future__ import annotations

import http.server
import json
import os
import platform
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

__version__ = "0.1.2"

__all__ = [
    "get_api_key",
    "auth_headers",
    "api_base",
    "login",
    "logout",
    "load_config",
    "save_config",
    "get_config_path",
    "MissingKeyError",
]

DEFAULT_API_BASE = "https://chat.persoia.com/v1"
DEMO_API_BASE = "https://demo.chat.persoia.com/v1"
CLIENT_HEADER = "X-Persoia-Client"

# En-tête optionnel d'identification de l'outil (suivi de conso côté persoIA).
# Renseigné via get_api_key/auth_headers(client=...).


class MissingKeyError(RuntimeError):
    """Aucune clé persoIA et impossible d'en obtenir une (mode non interactif)."""


# --- Emplacement & format du store partagé ---------------------------------
def get_config_dir() -> Path:
    """Dossier de config persoIA, partagé par tous les outils."""
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        return Path(base) / "persoia"
    base = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    return Path(base) / "persoia"


def get_config_path() -> Path:
    """Chemin du fichier de config (surchargeable par PERSOIA_CONFIG)."""
    return Path(os.environ.get("PERSOIA_CONFIG", get_config_dir() / "config.env"))


def load_config() -> dict[str, str]:
    """Charge la config : variables d'environnement prioritaires sur le fichier.

    Seules les clés préfixées ``PERSOIA_`` sont retenues. ``PERSOIA_API_BASE`` est
    auto-déduit du préfixe du token s'il n'est pas explicitement défini.
    """
    config = {
        "PERSOIA_API_KEY": os.environ.get("PERSOIA_API_KEY", ""),
        "PERSOIA_API_BASE": os.environ.get("PERSOIA_API_BASE", ""),
        "PERSOIA_MODEL": os.environ.get("PERSOIA_MODEL", ""),
        "PERSOIA_TENANT_NAME": os.environ.get("PERSOIA_TENANT_NAME", ""),
    }
    path = get_config_path()
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            raw = ""  # un fichier corrompu ne doit pas casser la lecture
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("PERSOIA_") and not config.get(key):
                config[key] = value.strip()
    config["PERSOIA_API_BASE"] = resolve_api_base(
        config["PERSOIA_API_KEY"], config["PERSOIA_API_BASE"]
    )
    return config


def save_config(values: dict[str, str]) -> None:
    """Écrit la config (perms 0600 sur Unix). Fusionne avec l'existant."""
    current = {
        k: v for k, v in _read_file_config().items() if k.startswith("PERSOIA_")
    }
    current.update({k: v for k, v in values.items() if k.startswith("PERSOIA_")})

    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    path = get_config_path()
    lines = ["# persoIA configuration — partagée par les outils persoIA"]
    for key, value in sorted(current.items()):
        if value:
            lines.append(f"{key}={value}")
    content = "\n".join(lines) + "\n"

    if platform.system() == "Windows":
        path.write_text(content, encoding="utf-8")
    else:
        # Ouverture en 0600 d'emblée (pas de fenêtre world-readable), PUIS chmod
        # explicite : le mode de O_CREAT ne s'applique qu'à la création, donc un
        # fichier préexistant aux permissions trop larges resterait inchangé.
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(path, 0o600)


def _read_file_config() -> dict[str, str]:
    path = get_config_path()
    out: dict[str, str] = {}
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return out
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


def resolve_api_base(api_key: str, explicit_base: str = "") -> str:
    """URL de base : explicite > préfixe du token (démo/prod)."""
    if explicit_base.strip():
        return explicit_base.strip()
    if api_key.strip().startswith("persoia_demo_sk_"):
        return DEMO_API_BASE
    return DEFAULT_API_BASE


def _valid_api_base(raw: str | None) -> str:
    """Renvoie ``raw`` si c'est une URL https persoia.com sûre, sinon ""."""
    raw = (raw or "").strip()
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return ""
    if (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and (parsed.hostname == "persoia.com" or parsed.hostname.endswith(".persoia.com"))
    ):
        return raw
    return ""


# --- API publique -----------------------------------------------------------
def api_base(api_key: str | None = None) -> str:
    """URL de base de l'API persoIA pour la clé courante (ou fournie)."""
    config = load_config()
    key = api_key if api_key is not None else config["PERSOIA_API_KEY"]
    return resolve_api_base(key, config["PERSOIA_API_BASE"])


def get_api_key(client: str | None = None, interactive: bool = True) -> str:
    """Renvoie la clé persoIA, en lançant le login navigateur si nécessaire.

    Ordre : variable d'environnement / store partagé. Si absente et ``interactive``
    et qu'un navigateur est disponible, ouvre le portail pour s'identifier et
    mémorise la clé. Lève ``MissingKeyError`` si aucune clé et non interactif.

    Args:
        client: identifiant de l'outil appelant (ex. "scan-cartes"). Sert au
            suivi de consommation (en-tête X-Persoia-Client) et est transmis au
            portail au login.
        interactive: autorise l'ouverture du navigateur si la clé manque.
    """
    key = load_config()["PERSOIA_API_KEY"].strip()
    if key:
        return key
    if interactive and _can_open_browser():
        if login(client=client):
            return load_config()["PERSOIA_API_KEY"].strip()
    raise MissingKeyError(
        "Aucune clé persoIA. Connectez-vous (persoia_auth.login()) "
        "ou définissez la variable d'environnement PERSOIA_API_KEY."
    )


def auth_headers(client: str | None = None, interactive: bool = True) -> dict[str, str]:
    """En-têtes HTTP prêts à l'emploi : Authorization + X-Persoia-Client.

    L'en-tête ``X-Persoia-Client`` identifie l'outil pour le suivi de conso côté
    persoIA (sans effet tant que le serveur ne l'exploite pas — sans danger).
    """
    headers = {"Authorization": f"Bearer {get_api_key(client, interactive)}"}
    if client:
        headers[CLIENT_HEADER] = client
    return headers


def logout() -> None:
    """Efface la clé du store partagé (laisse api_base/model/tenant intacts).

    `save_config` relit le fichier et fusionne : retirer la clé via un `pop()`
    serait réécrasé par la relecture du disque. On passe donc une valeur VIDE,
    qui n'est pas réécrite (cf. `if value` dans `save_config`) → la clé disparaît
    tout en conservant les autres champs.
    """
    save_config({"PERSOIA_API_KEY": ""})


def login(client: str | None = None, timeout: int = 180) -> str | None:
    """Login navigateur (flux loopback). Mémorise et renvoie la clé, ou None."""
    config = load_config()
    captured = _browser_login(config, client=client, timeout=timeout)
    if not captured or "token" not in captured:
        return None
    values = {"PERSOIA_API_KEY": captured["token"]}
    if captured.get("api_base"):
        values["PERSOIA_API_BASE"] = captured["api_base"]
    if captured.get("model"):
        values["PERSOIA_MODEL"] = captured["model"]
    if captured.get("tenant_name"):
        values["PERSOIA_TENANT_NAME"] = captured["tenant_name"]
    save_config(values)
    return captured["token"]


# --- Login navigateur (loopback) -------------------------------------------
def _portal_base(config: dict) -> str:
    """Origine du portail web (https://<host>) déduite de l'API base, host de confiance."""
    api_base_url = config.get("PERSOIA_API_BASE", DEFAULT_API_BASE)
    parsed = urllib.parse.urlparse(api_base_url)
    host = (parsed.hostname or "chat.persoia.com").lower()
    if host != "persoia.com" and not host.endswith(".persoia.com"):
        portal_host = "chat.persoia.com"
    elif host.startswith("api."):
        portal_host = "chat." + host[len("api.") :]
    else:
        portal_host = host
    return f"https://{portal_host}"


def _can_open_browser() -> bool:
    """Heuristique : un navigateur est ouvrable (pas en CI/headless pur)."""
    if not sys.stdin or not sys.stdin.isatty():
        # Tolère les apps GUI bundlées (pas de TTY mais navigateur dispo).
        if os.environ.get("PERSOIA_NONINTERACTIVE"):
            return False
    try:
        webbrowser.get()
        return True
    except webbrowser.Error:
        return False


def _browser_login(config: dict, client: str | None = None, timeout: int = 180) -> dict | None:
    """Démarre un serveur loopback, ouvre le portail /cli, capture la clé.

    Le portail POST `{token, state, api_base?, model?, tenant_name?}` sur le
    callback loopback (token jamais dans l'URL), avec fallback GET. `state`
    anti-CSRF, usage unique, CORS limité à l'origine du portail, et gestion du
    preflight « Private Network Access » de Chrome/Edge.
    """
    portal = _portal_base(config)
    state = secrets.token_urlsafe(24)
    result: dict = {}
    done = threading.Event()

    class _Handler(http.server.BaseHTTPRequestHandler):
        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", portal)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _page(self, status: int, message: str) -> None:
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = (
                "<!doctype html><html lang='fr'><meta charset='utf-8'>"
                "<title>persoIA</title>"
                "<body style='font-family:sans-serif;text-align:center;margin-top:4em'>"
                f"<h2>{message}</h2><p>Vous pouvez fermer cet onglet.</p></body></html>"
            )
            self.wfile.write(html.encode("utf-8"))

        def _accept(self, token: str, got_state: str, extra: dict) -> bool:
            if result.get("token"):  # usage unique
                self._page(200, "Connexion déjà reçue.")
                return True
            if not got_state or not secrets.compare_digest(got_state, state):
                self._page(400, "État invalide — connexion refusée.")
                return False
            if not token:
                self._page(400, "Token manquant.")
                return False
            result["token"] = token
            valid_base = _valid_api_base(extra.get("api_base", ""))
            if valid_base:
                result["api_base"] = valid_base
            if extra.get("model"):
                result["model"] = extra["model"]
            if extra.get("tenant_name"):
                result["tenant_name"] = extra["tenant_name"]
            self._page(200, "Connexion réussie !")
            return True

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            if self.headers.get("Access-Control-Request-Private-Network") == "true":
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            if urllib.parse.urlparse(self.path).path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            if self._accept(str(data.get("token", "")), str(data.get("state", "")), data):
                done.set()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            q = urllib.parse.parse_qs(parsed.query)
            extra = {
                "api_base": q.get("api_base", [""])[0],
                "model": q.get("model", [""])[0],
                "tenant_name": q.get("tenant_name", [""])[0],
            }
            if self._accept(q.get("token", [""])[0], q.get("state", [""])[0], extra):
                done.set()

        def log_message(self, *args: object) -> None:
            pass

    try:
        server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:
        print(f"Impossible de démarrer le serveur local de connexion : {exc}", file=sys.stderr)
        return None

    port = server.server_address[1]
    callback = f"http://127.0.0.1:{port}/callback"
    params = {"callback": callback, "state": state}
    if client:  # hook forward-compat pour l'étiquetage par outil (option A)
        params["client"] = client
    authorize_url = f"{portal}/cli?" + urllib.parse.urlencode(params)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print(f"Ouverture de {portal} pour la connexion...")
        print("Si la page ne s'ouvre pas, collez cette URL dans votre navigateur :")
        print(f"  {authorize_url}\n")
        print("En attente de la connexion dans le navigateur...")
        webbrowser.open(authorize_url)
        got = done.wait(timeout=timeout)
    finally:
        server.shutdown()
        server.server_close()

    if not got or "token" not in result:
        return None
    return result
