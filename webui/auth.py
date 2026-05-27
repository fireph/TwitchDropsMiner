"""WebUI access protection.

Adds a login wall in front of the NiceGUI app so the panel can be safely
exposed on the network. On first launch, when no credentials are configured
yet, the user is redirected to ``/setup`` to create them. Subsequent visits
require signing in via ``/login``. Credentials are stored hashed (PBKDF2-SHA256)
in ``config/webui_auth.json`` along with the session-cookie secret.

Auth state lives in ``app.storage.user`` (not ``request.session``) because
button clicks reach the server via the WebSocket — there is no HTTP response
in flight to write a new ``Set-Cookie`` header to. NiceGUI's ``storage_secret``
is what wires up the underlying session middleware; passing the same key we
sign the auth file with keeps the cookie stable across restarts.
"""

from __future__ import annotations

import os
import json
import hmac
import time
import secrets
import hashlib
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from nicegui import app, ui
from starlette.middleware.base import BaseHTTPMiddleware


WEBUI_AUTH_FILE = "webui_auth.json"
WEBUI_AUTH_ENV = "WEBUI_AUTH"
SESSION_KEY = "webui_authenticated"
PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16

# Rate-limit tuning. Burst threshold is the freebie attempt count; past that
# each additional failure doubles the required wait before the next try.
RL_THRESHOLD = 5
RL_MAX_COOLDOWN = 900  # 15 min
RL_WINDOW = 3600  # forget attempts older than this many seconds

# Paths the auth middleware never blocks. ``/_nicegui`` covers the JS bundle
# and the socket.io endpoint; the page handler still gates content.
_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/login",
    "/setup",
    "/logout",
    "/_nicegui",
    "/icons",
    "/favicon",
    "/robots.txt",
)

logger = logging.getLogger("TwitchDrops")


def is_auth_enabled() -> bool:
    """Whether the WebUI login wall should be active.

    Controlled by the ``WEBUI_AUTH`` environment variable. Default is on
    so a fresh deployment is never exposed unprotected by accident; opt out
    with ``WEBUI_AUTH=off`` (also accepts ``0``/``false``/``no``/``disabled``).
    """
    val = os.environ.get(WEBUI_AUTH_ENV, "on").strip().lower()
    return val not in ("off", "0", "false", "no", "disabled", "disable", "")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class _RateLimiter:
    """Per-IP login throttle with exponential backoff.

    The first ``RL_THRESHOLD`` failures are free; each subsequent failure
    doubles the cooldown (1s, 2s, 4s, …) up to ``RL_MAX_COOLDOWN``. Attempts
    older than ``RL_WINDOW`` are forgotten on each check. Successful login
    resets the counter for the offending IP.
    """

    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = defaultdict(list)

    def _prune(self, ip: str) -> None:
        cutoff = time.monotonic() - RL_WINDOW
        fresh = [t for t in self._fails[ip] if t > cutoff]
        if fresh:
            self._fails[ip] = fresh
        else:
            self._fails.pop(ip, None)

    def cooldown_remaining(self, ip: str) -> float:
        self._prune(ip)
        attempts = self._fails.get(ip, [])
        if len(attempts) < RL_THRESHOLD:
            return 0.0
        overflow = len(attempts) - RL_THRESHOLD
        cooldown = min(2**overflow, RL_MAX_COOLDOWN)
        elapsed = time.monotonic() - attempts[-1]
        return max(0.0, cooldown - elapsed)

    def record_failure(self, ip: str) -> None:
        self._prune(ip)
        self._fails[ip].append(time.monotonic())

    def reset(self, ip: str) -> None:
        self._fails.pop(ip, None)


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )


class AuthManager:
    """Owns the on-disk credential store and validates login attempts."""

    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._username: Optional[str] = None
        self._salt: Optional[bytes] = None
        self._hash: Optional[bytes] = None
        self._secret_key: str = ""
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._username = data.get("username") or None
                self._salt = (
                    bytes.fromhex(data["salt"]) if data.get("salt") else None
                )
                self._hash = (
                    bytes.fromhex(data["hash"]) if data.get("hash") else None
                )
                self._secret_key = data.get("secret_key") or ""
            except Exception as exc:
                logger.warning("WebUI auth config unreadable, regenerating: %s", exc)
                self._username = self._salt = self._hash = None
                self._secret_key = ""
        if not self._secret_key:
            self._secret_key = secrets.token_urlsafe(32)
            self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"secret_key": self._secret_key}
        if self._username and self._salt and self._hash:
            payload["username"] = self._username
            payload["salt"] = self._salt.hex()
            payload["hash"] = self._hash.hex()
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @property
    def secret_key(self) -> str:
        return self._secret_key

    def is_configured(self) -> bool:
        return bool(self._username and self._salt and self._hash)

    def setup(self, username: str, password: str) -> None:
        username = username.strip()
        if not username:
            raise ValueError("Username is required")
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters")
        self._username = username
        self._salt = secrets.token_bytes(SALT_BYTES)
        self._hash = _hash_password(password, self._salt)
        self._save()

    def verify(self, username: str, password: str) -> bool:
        if not self.is_configured():
            return False
        if username.strip() != self._username:
            return False
        expected = _hash_password(password, self._salt)  # type: ignore[arg-type]
        return hmac.compare_digest(expected, self._hash)  # type: ignore[arg-type]


class _AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth: AuthManager) -> None:
        super().__init__(app)
        self._auth = auth

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)
        if not self._auth.is_configured():
            return RedirectResponse("/setup", status_code=302)
        if not app.storage.user.get(SESSION_KEY):
            return RedirectResponse("/login", status_code=302)
        return await call_next(request)


def install_auth(auth: AuthManager) -> None:
    """Wire the auth middleware and the login/setup/logout pages into NiceGUI's FastAPI app.

    We register our middleware before ``ui.run()`` is called; NiceGUI then adds
    its own ``SessionMiddleware`` (because ``storage_secret`` is set), which
    Starlette places outermost. The session is decoded before our middleware
    runs, so ``app.storage.user`` is populated by the time we read it.
    """
    app.add_middleware(_AuthMiddleware, auth=auth)

    limiter = _RateLimiter()
    _register_login_page(auth, limiter)
    _register_setup_page(auth)
    _register_logout_page()


def _build_card(title: str):
    card = ui.card().classes("absolute-center q-pa-md").style("min-width: 320px")
    with card:
        with ui.row().classes("items-center gap-2 w-full"):
            ui.image("/icons/pickaxe.ico").classes("w-8 h-8")
            ui.label(title).classes("text-h6")
    return card


def _register_login_page(auth: AuthManager, limiter: _RateLimiter) -> None:
    @ui.page("/login")
    def login_page(request: Request):
        if not auth.is_configured():
            return RedirectResponse("/setup", status_code=302)
        if app.storage.user.get(SESSION_KEY):
            return RedirectResponse("/", status_code=302)

        ip = _client_ip(request)

        with _build_card("Sign in"):
            username = ui.input("Username").classes("w-full").props("dense outlined autofocus")
            password = (
                ui.input("Password", password=True, password_toggle_button=True)
                .classes("w-full")
                .props("dense outlined")
            )

            def do_login() -> None:
                wait = limiter.cooldown_remaining(ip)
                if wait > 0:
                    ui.notify(
                        f"Too many failed attempts. Try again in {int(wait) + 1}s.",
                        color="negative",
                    )
                    return
                if auth.verify(username.value or "", password.value or ""):
                    limiter.reset(ip)
                    # Anti-fixation: drop any pre-existing storage before flagging auth.
                    app.storage.user.clear()
                    app.storage.user[SESSION_KEY] = True
                    ui.navigate.to("/")
                else:
                    limiter.record_failure(ip)
                    logger.warning("WebUI login failed from %s", ip)
                    ui.notify("Invalid username or password", color="negative")
                    password.value = ""

            username.on("keydown.enter", do_login)
            password.on("keydown.enter", do_login)
            ui.button("Sign in", on_click=do_login).classes("w-full").props("color=primary")


def _register_setup_page(auth: AuthManager) -> None:
    @ui.page("/setup")
    def setup_page():
        if auth.is_configured():
            return RedirectResponse("/login", status_code=302)

        with _build_card("Create WebUI credentials"):
            ui.label(
                "This is the first launch. Set a username and password to "
                "protect the panel — they will be required on every visit."
            ).classes("text-xs text-gray-600 dark:text-gray-300")

            username = ui.input("Username").classes("w-full").props("dense outlined autofocus")
            password = (
                ui.input("Password", password=True, password_toggle_button=True)
                .classes("w-full")
                .props("dense outlined")
            )
            confirm = (
                ui.input("Confirm password", password=True, password_toggle_button=True)
                .classes("w-full")
                .props("dense outlined")
            )

            def do_setup() -> None:
                p = password.value or ""
                c = confirm.value or ""
                if p != c:
                    ui.notify("Passwords do not match", color="negative")
                    return
                try:
                    auth.setup(username.value or "", p)
                except ValueError as exc:
                    ui.notify(str(exc), color="negative")
                    return
                app.storage.user[SESSION_KEY] = True
                ui.notify("Credentials saved", color="positive")
                ui.navigate.to("/")

            confirm.on("keydown.enter", do_setup)
            ui.button("Create", on_click=do_setup).classes("w-full").props("color=primary")


def _register_logout_page() -> None:
    @ui.page("/logout")
    def logout_page():
        app.storage.user.pop(SESSION_KEY, None)
        return RedirectResponse("/login", status_code=302)
