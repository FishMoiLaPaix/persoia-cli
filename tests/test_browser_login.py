#!/usr/bin/env python3
"""Tests for the browser-login (loopback callback) flow in `persoia.py`.

These tests are deterministic and offline:

  - `_valid_api_base()` is a pure function and is tested directly.
  - The loopback `_Handler` is exercised end-to-end by letting `_browser_login`
    spin its real `http.server.HTTPServer` on an ephemeral 127.0.0.1 port, and
    by replacing `webbrowser.open` with a stub that parses the authorize URL
    (to extract the `callback` and `state`) and POSTs/GETs the callback from a
    background thread. No real browser and no network beyond the in-process
    loopback are involved.

Run with: pytest tests/test_browser_login.py
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

# The CLI ships as a single script under src/; import it the way CI does.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import persoia  # noqa: E402


# --------------------------------------------------------------------------- #
# _valid_api_base: strict https + persoia.com (sub)domain allowlist
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "url",
    [
        "https://persoia.com",
        "https://chat.persoia.com",
        "https://x.persoia.com",
        "https://demo.chat.persoia.com/v1",
    ],
)
def test_valid_api_base_accepts_https_persoia(url: str) -> None:
    assert persoia._valid_api_base(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://persoia.com",  # non-https
        "http://chat.persoia.com",  # non-https
        "https://evil.com",
        "https://persoia.com.attacker.tld",  # suffix-trick, not a subdomain
        "https://notpersoia.com",  # not a .persoia.com subdomain
        "https://persoia.com.evil",
        "ftp://persoia.com",
        "",
        "   ",
        "not a url",
    ],
)
def test_valid_api_base_rejects_untrusted(url: str) -> None:
    assert persoia._valid_api_base(url) == ""


def test_valid_api_base_handles_none() -> None:
    # The function guards `raw or ""`; None must not raise.
    assert persoia._valid_api_base(None) == ""  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Loopback handler harness
# --------------------------------------------------------------------------- #

def _parse_authorize_url(authorize_url: str) -> tuple[str, str]:
    """Return (callback_url, state) extracted from the portal authorize URL."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(authorize_url).query)
    return q["callback"][0], q["state"][0]


def _run_browser_login(monkeypatch, opener, *, timeout: int = 5) -> dict | None:
    """Run `_browser_login`, replacing `webbrowser.open` with `opener`.

    `opener` receives the authorize URL and is responsible for hitting the
    loopback callback (in a background thread, so `_browser_login` keeps
    waiting on its event). The config pins the production portal.
    """
    config = {"PERSOIA_API_BASE": "https://chat.persoia.com/v1"}

    def fake_open(url: str) -> bool:
        threading.Thread(target=opener, args=(url,), daemon=True).start()
        return True

    monkeypatch.setattr(persoia.webbrowser, "open", fake_open)
    return persoia._browser_login(config, timeout=timeout)


def _post_callback(callback: str, payload: dict) -> int:
    """POST JSON to the loopback callback; return the HTTP status code.

    A 4xx is a normal, expected outcome here (e.g. rejected state), so the
    HTTPError is converted to its status code rather than propagated out of
    the background thread (which pytest would surface as a warning).
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        callback, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
            return resp.status
    except urllib.error.HTTPError as e:
        e.read()
        return e.code


def _get_callback(callback: str, params: dict) -> int:
    """GET the loopback callback; return the HTTP status code (4xx incl.)."""
    url = callback + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            resp.read()
            return resp.status
    except urllib.error.HTTPError as e:
        e.read()
        return e.code


# --------------------------------------------------------------------------- #
# Happy path: a POST with the correct state is accepted, token captured.
# --------------------------------------------------------------------------- #

def test_post_with_correct_state_is_accepted(monkeypatch) -> None:
    def opener(authorize_url: str) -> None:
        callback, state = _parse_authorize_url(authorize_url)
        _post_callback(
            callback,
            {
                "token": "persoia_sk_good",
                "state": state,
                "api_base": "https://chat.persoia.com/v1",
                "model": "openai/persoia",
                "tenant_name": "Acme",
            },
        )

    result = _run_browser_login(monkeypatch, opener)
    assert result is not None
    assert result["token"] == "persoia_sk_good"
    assert result["api_base"] == "https://chat.persoia.com/v1"
    assert result["model"] == "openai/persoia"
    assert result["tenant_name"] == "Acme"


def test_get_fallback_with_correct_state_is_accepted(monkeypatch) -> None:
    def opener(authorize_url: str) -> None:
        callback, state = _parse_authorize_url(authorize_url)
        _get_callback(callback, {"token": "persoia_sk_get", "state": state})

    result = _run_browser_login(monkeypatch, opener)
    assert result is not None
    assert result["token"] == "persoia_sk_get"


# --------------------------------------------------------------------------- #
# Anti-CSRF: a callback with a WRONG state must be rejected and never accepted.
# (Covers the epic's "anti-CSRF state" follow-up — constant-time compare.)
# --------------------------------------------------------------------------- #

def test_post_with_wrong_state_is_rejected(monkeypatch) -> None:
    def opener(authorize_url: str) -> None:
        callback, _state = _parse_authorize_url(authorize_url)
        # Attacker-controlled state that does not match the CLI-generated one.
        status = _post_callback(
            callback,
            {"token": "persoia_sk_attacker", "state": "totally-wrong-state"},
        )
        # The handler responds 400 and never sets the done event.
        assert status == 400

    # No valid callback ever arrives, so _browser_login times out → None.
    result = _run_browser_login(monkeypatch, opener, timeout=2)
    assert result is None


def test_get_with_wrong_state_is_rejected(monkeypatch) -> None:
    def opener(authorize_url: str) -> None:
        callback, _state = _parse_authorize_url(authorize_url)
        status = _get_callback(
            callback, {"token": "persoia_sk_attacker", "state": "wrong"}
        )
        assert status == 400

    result = _run_browser_login(monkeypatch, opener, timeout=2)
    assert result is None


def test_missing_state_is_rejected(monkeypatch) -> None:
    def opener(authorize_url: str) -> None:
        callback, _state = _parse_authorize_url(authorize_url)
        status = _post_callback(callback, {"token": "persoia_sk_x"})
        assert status == 400

    result = _run_browser_login(monkeypatch, opener, timeout=2)
    assert result is None


def test_correct_state_but_missing_token_is_rejected(monkeypatch) -> None:
    def opener(authorize_url: str) -> None:
        callback, state = _parse_authorize_url(authorize_url)
        status = _post_callback(callback, {"state": state})
        assert status == 400

    result = _run_browser_login(monkeypatch, opener, timeout=2)
    assert result is None


# --------------------------------------------------------------------------- #
# Robustness: untrusted api_base in an otherwise-valid callback is dropped,
# wrong path 404s, and OPTIONS returns the CORS preflight headers.
# --------------------------------------------------------------------------- #

def test_untrusted_api_base_is_dropped_token_still_captured(monkeypatch) -> None:
    def opener(authorize_url: str) -> None:
        callback, state = _parse_authorize_url(authorize_url)
        _post_callback(
            callback,
            {
                "token": "persoia_sk_good",
                "state": state,
                "api_base": "https://evil.com",  # must be filtered out
            },
        )

    result = _run_browser_login(monkeypatch, opener)
    assert result is not None
    assert result["token"] == "persoia_sk_good"
    assert "api_base" not in result


def test_wrong_path_returns_404(monkeypatch) -> None:
    captured: dict = {}

    def opener(authorize_url: str) -> None:
        callback, state = _parse_authorize_url(authorize_url)
        base = callback.rsplit("/callback", 1)[0]
        try:
            urllib.request.urlopen(base + "/nope", timeout=5)
        except urllib.error.HTTPError as e:
            captured["status"] = e.code
        # Then complete the flow so _browser_login returns instead of timing out.
        _post_callback(callback, {"token": "persoia_sk_good", "state": state})

    result = _run_browser_login(monkeypatch, opener)
    assert captured.get("status") == 404
    assert result is not None and result["token"] == "persoia_sk_good"


def test_options_returns_cors_preflight(monkeypatch) -> None:
    captured: dict = {}

    def opener(authorize_url: str) -> None:
        callback, state = _parse_authorize_url(authorize_url)
        req = urllib.request.Request(callback, method="OPTIONS")
        with urllib.request.urlopen(req, timeout=5) as resp:
            captured["status"] = resp.status
            captured["allow_origin"] = resp.headers.get(
                "Access-Control-Allow-Origin"
            )
            captured["allow_methods"] = resp.headers.get(
                "Access-Control-Allow-Methods"
            )
            captured["allow_headers"] = resp.headers.get(
                "Access-Control-Allow-Headers"
            )
        # Complete so _browser_login returns.
        _post_callback(callback, {"token": "persoia_sk_good", "state": state})

    result = _run_browser_login(monkeypatch, opener)
    assert captured.get("status") == 204
    # Only the portal origin (https, no /v1 path) is allowed to post the token.
    assert captured.get("allow_origin") == "https://chat.persoia.com"
    assert "POST" in (captured.get("allow_methods") or "")
    assert "Content-Type" in (captured.get("allow_headers") or "")
    assert result is not None and result["token"] == "persoia_sk_good"


def test_options_grants_private_network_access(monkeypatch) -> None:
    # Chrome/Edge Private Network Access: an https origin posting to a loopback
    # address sends a preflight with `Access-Control-Request-Private-Network`,
    # and the response MUST echo `Access-Control-Allow-Private-Network: true`
    # or the browser blocks the token POST ("Impossible de joindre le terminal").
    captured: dict = {}

    def opener(authorize_url: str) -> None:
        callback, state = _parse_authorize_url(authorize_url)
        req = urllib.request.Request(callback, method="OPTIONS")
        req.add_header("Access-Control-Request-Private-Network", "true")
        with urllib.request.urlopen(req, timeout=5) as resp:
            captured["allow_pna"] = resp.headers.get(
                "Access-Control-Allow-Private-Network"
            )
        _post_callback(callback, {"token": "persoia_sk_good", "state": state})

    result = _run_browser_login(monkeypatch, opener)
    assert captured.get("allow_pna") == "true"
    assert result is not None and result["token"] == "persoia_sk_good"


# --------------------------------------------------------------------------- #
# The CLI advertises the loopback callback on the literal IPv4 127.0.0.1
# (not "localhost", which may resolve to ::1 and break the browser fetch).
# --------------------------------------------------------------------------- #

def test_callback_url_uses_ipv4_loopback(monkeypatch) -> None:
    captured: dict = {}

    def opener(authorize_url: str) -> None:
        callback, state = _parse_authorize_url(authorize_url)
        captured["callback"] = callback
        _post_callback(callback, {"token": "persoia_sk_good", "state": state})

    result = _run_browser_login(monkeypatch, opener)
    assert result is not None
    assert captured["callback"].startswith("http://127.0.0.1:")
    assert "localhost" not in captured["callback"]


class TestPortalBase:
    """_portal_base must only ever derive a portal from a trusted persoia.com
    host; a hostile PERSOIA_API_BASE must fall back to the production portal
    (it is echoed in the CORS Access-Control-Allow-Origin)."""

    @pytest.mark.parametrize(
        "api_base,expected",
        [
            ("https://chat.persoia.com/v1", "https://chat.persoia.com"),
            ("https://api.persoia.com/v1", "https://chat.persoia.com"),
            ("https://demo.chat.persoia.com/v1", "https://demo.chat.persoia.com"),
            ("https://api.demo.persoia.com/v1", "https://chat.demo.persoia.com"),
            # Hostile / untrusted hosts -> production portal fallback.
            ("https://evil.chat.attacker.tld/v1", "https://chat.persoia.com"),
            ("https://chat.attacker.tld/v1", "https://chat.persoia.com"),
            ("https://persoia.com.attacker.tld/v1", "https://chat.persoia.com"),
            ("http://chat.persoia.com/v1", "https://chat.persoia.com"),
        ],
    )
    def test_portal_base_only_trusts_persoia_com(self, api_base, expected):
        assert persoia._portal_base({"PERSOIA_API_BASE": api_base}) == expected


# --------------------------------------------------------------------------- #
# cmd_login idempotence (persoia-cli#26): ne pas re-minter une clé si déjà
# connecté — c'était la cause de la rafale de tokens.
# --------------------------------------------------------------------------- #

def _config_with_valid_key() -> dict:
    return {
        "PERSOIA_API_KEY": "persoia_sk_" + "x" * 40,
        "PERSOIA_API_BASE": "https://chat.persoia.com/v1",
        "PERSOIA_MODEL": "small",
        "PERSOIA_TENANT_NAME": "ACME",
    }


def test_login_idempotent_skips_browser_when_token_valid(monkeypatch, capsys) -> None:
    monkeypatch.setattr(persoia, "load_config", _config_with_valid_key)
    monkeypatch.setattr(persoia, "api_request", lambda *a, **k: (200, {"data": [{"id": "small"}]}))
    called = {"browser": False}
    monkeypatch.setattr(
        persoia, "_browser_login",
        lambda cfg: called.__setitem__("browser", True) or None,
    )

    persoia.cmd_login([])

    assert called["browser"] is False, "un token valide ne doit PAS rouvrir le flow (anti-rafale)"
    assert "Déjà connecté" in capsys.readouterr().out


def test_login_force_bypasses_idempotence(monkeypatch) -> None:
    monkeypatch.setattr(persoia, "load_config", _config_with_valid_key)
    monkeypatch.setattr(persoia, "api_request", lambda *a, **k: (200, {}))
    saved: dict = {}
    monkeypatch.setattr(persoia, "save_config", lambda v: saved.update(v))
    monkeypatch.setattr(
        persoia, "_browser_login",
        lambda cfg: {"token": "persoia_sk_new", "api_base": cfg["PERSOIA_API_BASE"]},
    )

    persoia.cmd_login(["--force"])

    assert saved.get("PERSOIA_API_KEY") == "persoia_sk_new", "--force doit relancer le flow malgré un token valide"


def test_login_proceeds_when_existing_token_invalid(monkeypatch) -> None:
    monkeypatch.setattr(persoia, "load_config", _config_with_valid_key)
    monkeypatch.setattr(persoia, "api_request", lambda *a, **k: (401, {}))
    monkeypatch.setattr(persoia, "save_config", lambda v: None)
    called = {"browser": False}

    def fake_browser(cfg: dict) -> dict:
        called["browser"] = True
        return {"token": "persoia_sk_fresh", "api_base": cfg["PERSOIA_API_BASE"]}

    monkeypatch.setattr(persoia, "_browser_login", fake_browser)

    persoia.cmd_login([])

    assert called["browser"] is True, "un token révoqué/expiré doit relancer une connexion"


def test_login_proceeds_when_api_unreachable(monkeypatch) -> None:
    # API injoignable : la sonde NON-FATALE (fatal=False) renvoie (None, None)
    # → pas de raccourci « déjà connecté », pas de sys.exit, on poursuit vers
    # la connexion normale (review Copilot cli#27).
    monkeypatch.setattr(persoia, "load_config", _config_with_valid_key)
    monkeypatch.setattr(persoia, "api_request", lambda *a, **k: (None, None))
    monkeypatch.setattr(persoia, "save_config", lambda v: None)
    called = {"browser": False}

    def fake_browser(cfg: dict) -> dict:
        called["browser"] = True
        return {"token": "persoia_sk_fresh", "api_base": cfg["PERSOIA_API_BASE"]}

    monkeypatch.setattr(persoia, "_browser_login", fake_browser)

    persoia.cmd_login([])

    assert called["browser"] is True, "API injoignable ne doit pas bloquer login (fatal=False)"
