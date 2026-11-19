"""
Login to WebUntis with plain HTTP requests, the same ones the login page of WebUntis sends. It takes about
a second and needs no browser.

The class offers this small interface to get_week_and_lesson_information.py:

    auth.bearer()        value for the Authorization header ("Bearer ...")
    auth.tenant_id       value for the Tenant-Id header
    auth.get(url, params, headers)   GET request with the session cookies
    auth.session_lost(response)      True if WebUntis answers like "you are not logged in"
    auth.login()         log in again

After a failed login the program pauses for LOGIN_PAUSE_MINUTES before it tries again, so a wrong password
cannot lock your account by being tried every few minutes. A changed password or user ends the pause at once.
"""

import base64
import hashlib
import json
import logging
import math
import os
import re
import time

import requests

import config

SCHEME = "https"
TIMEOUT = 30                 # seconds for login and token requests
REQUEST_TIMEOUT = 60         # seconds for data requests
TOKEN_MARGIN = 60            # a token is renewed this many seconds before it expires
LOGIN_PAUSE_MINUTES = 30
PAUSE_FILE = os.path.join(config.DATA_DIR, ".untis_login_pause")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0")


class UntisLoginError(RuntimeError):
    """The login to WebUntis did not work (the message says why and is safe to show, it contains no secrets)."""


def origin():
    return f"{SCHEME}://{config.UNTIS_SERVER}"


def _jwt_claims(token):
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return claims if isinstance(claims, dict) else None
    except (IndexError, ValueError, UnicodeDecodeError):
        return None


# ----------------------------------------------------------------------------------------------------
# Pause after a failed login
# ----------------------------------------------------------------------------------------------------

def _fingerprint():
    text = f"{config.UNTIS_SERVER}\n{config.UNTIS_USER}\n{config.UNTIS_PASSWORD}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _pause_remaining():
    """Seconds until the next login attempt is allowed (0 = allowed)."""
    try:
        with open(PAUSE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("fingerprint") != _fingerprint():   # user, password or server changed: try again right away
            return 0
        return max(0.0, float(data.get("until", 0)) - time.time())
    except (OSError, ValueError, TypeError):
        return 0


def _set_pause():
    try:
        with open(PAUSE_FILE, "w", encoding="utf-8") as f:
            json.dump({"until": time.time() + LOGIN_PAUSE_MINUTES * 60, "fingerprint": _fingerprint()}, f)
    except OSError as e:
        logging.warning(f"Could not write {PAUSE_FILE}: {e}")


def _clear_pause():
    try:
        os.remove(PAUSE_FILE)
    except OSError:
        pass


# ----------------------------------------------------------------------------------------------------
# The login
# ----------------------------------------------------------------------------------------------------

class HttpAuth:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.token = None
        self.expires_at = 0.0
        self.tenant_id = ""
        self.login()

    # -- helpers --------------------------------------------------------------------------------

    @staticmethod
    def _find(pattern, text):
        match = re.search(pattern, text)
        return match.group(1) if match else None

    def _cookie(self, name):
        for cookie in self.session.cookies:
            if cookie.name.lower() == name.lower():
                return cookie.value.strip('"')
        return None

    def _school_name(self):
        if config.UNTIS_SCHOOL:
            return config.UNTIS_SCHOOL
        value = self._cookie("schoolname")      # "_" + Base64 of the school name
        if not value:
            return None
        raw = value[1:] if value.startswith("_") else value
        try:
            return base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    def _fetch_token(self):
        """Gets a new Bearer token with the current session. False if the session is not logged in."""
        r = self.session.get(f"{origin()}/WebUntis/api/token/new", headers={"Accept": "application/json"},
                             allow_redirects=False, timeout=TIMEOUT)
        if r.status_code != 200:                 # a dead session is answered with a redirect to index.do
            return False
        token = r.text.strip().strip('"')
        claims = _jwt_claims(token)
        if not claims:
            return False
        lifetime = float(claims.get("exp", 0)) - float(claims.get("iat", 0))
        self.token = token
        self.expires_at = time.time() + (lifetime if lifetime > 0 else 600)   # own clock, not the one of the server
        self.tenant_id = str(claims.get("tenant_id") or self.tenant_id or "")
        return True

    # -- interface ------------------------------------------------------------------------------

    def login(self):
        remaining = _pause_remaining()
        if remaining > 0:
            raise UntisLoginError(
                f"The WebUntis login failed before and is paused for another {math.ceil(remaining / 60)} minutes, "
                "so the account is not locked by repeated attempts. Check UNTIS_USER and UNTIS_PASSWORD in .env "
                "(a change ends the pause at once).")

        logging.info("Logging in to WebUntis (HTTP)")
        s = self.session
        s.cookies.clear()
        self.token = None

        page = s.get(f"{origin()}/WebUntis/index.do", timeout=TIMEOUT)
        if page.status_code != 200:
            raise UntisLoginError(f"WebUntis login page answered with HTTP {page.status_code}")

        csrf = self._find(r'"csrfToken"\s*:\s*"([^"]+)"', page.text)
        csrf_header = self._find(r'"csrfHeader"\s*:\s*"([^"]+)"', page.text) or "X-CSRF-TOKEN"
        tenant = self._find(r'"tenantId"\s*:\s*"?(\d+)', page.text) or self._cookie("Tenant-Id")
        school = self._school_name()
        if not school:
            raise UntisLoginError("The school name was not found on the login page. "
                                  "Set UNTIS_SCHOOL in .env (the login name of your school).")

        headers = {"Accept": "application/json, text/plain, */*", "Origin": origin(), "Referer": f"{origin()}/WebUntis/"}
        if tenant:
            headers["Tenant-Id"] = tenant
        if csrf:
            headers[csrf_header] = csrf
        form = {"school": school, "j_username": config.UNTIS_USER, "j_password": config.UNTIS_PASSWORD, "token": ""}

        r = s.post(f"{origin()}/WebUntis/j_spring_security_check", data=form, headers=headers,
                   allow_redirects=False, timeout=TIMEOUT)
        if r.status_code >= 500:
            raise UntisLoginError(f"WebUntis login answered with HTTP {r.status_code} (server problem, will retry)")

        # The answer of the form (200 JSON or a redirect) is not a reliable signal, a token is.
        if not self._fetch_token():
            _set_pause()
            raise UntisLoginError(
                "WebUntis did not accept the login. Check UNTIS_USER and UNTIS_PASSWORD (try them on the website). "
                "Schools with single sign-on are not supported. A captcha or a temporary "
                f"lockout also causes this. The next attempt is made in {LOGIN_PAUSE_MINUTES} minutes.")
        _clear_pause()

    def bearer(self):
        if self.token is None or time.time() >= self.expires_at - TOKEN_MARGIN:
            if not self._fetch_token():
                logging.info("The WebUntis session has ended, logging in again")
                self.login()
        return f"Bearer {self.token}"

    def get(self, url, params=None, headers=None):
        return self.session.get(url, params=params, headers=headers, allow_redirects=False, timeout=REQUEST_TIMEOUT)

    @staticmethod
    def session_lost(response):
        return response.status_code in (302, 401)


def create():
    """Logs in and returns the auth object."""
    return HttpAuth()
