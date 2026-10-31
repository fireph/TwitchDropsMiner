"""Exercise upstream login through the WebUI adapter without Twitch credentials."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import aiohttp
import pytest
import zendriver as zd

from constants import ClientType
from exceptions import ExitRequest, ReloadRequest
from translate import _
from webui import browser_display, browser_login
from webui.adapters.login_form import LoginFormAdapter
from webui.manager import WebUIManager


async def eventually(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout=2)


@pytest.fixture
def login_context(monkeypatch, webui_auth_state):
    monkeypatch.setenv("WEBUI_TWITCH_LOGIN", "android-browser")
    display = MagicMock(display=":123", view_url="/browser-login/view/test")
    display.__aenter__ = AsyncMock(return_value=display)
    display.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(browser_display, "BrowserDisplay", lambda: display)
    manager = SimpleNamespace(
        main_panel=MagicMock(),
        status=MagicMock(),
        _twitch=SimpleNamespace(settings=SimpleNamespace(stdlog=False)),
    )
    manager.print = WebUIManager.print.__get__(manager)
    manager.coro_unless_closed = WebUIManager.coro_unless_closed.__get__(manager)
    manager.login = LoginFormAdapter(manager)
    twitch = SimpleNamespace(gui=manager, _client_type=ClientType.ANDROID_APP)
    auth = webui_auth_state(twitch)
    return SimpleNamespace(auth=auth, twitch=twitch, manager=manager, display=display)


@pytest.fixture
def fake_browser(monkeypatch):
    browsers = []

    def create(config):
        browser = SimpleNamespace(
            config=config,
            stopped=False,
            main_tab=SimpleNamespace(url="about:blank"),
            targets=[],
            start=AsyncMock(),
        )

        async def get(url):
            browser.main_tab.url = url
            return browser.main_tab

        async def stop():
            browser.stopped = True

        browser.get = AsyncMock(side_effect=get)
        browser.stop = AsyncMock(side_effect=stop)
        browser.native_stop = browser.stop
        browser.test_connection = AsyncMock(side_effect=lambda: not browser.stopped)
        browsers.append(browser)
        return browser

    monkeypatch.setattr(zd, "Config", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(zd, "Browser", create)
    return browsers


def initialize_events(context):
    context.manager._close_requested = asyncio.Event()
    context.manager._reload_requested = asyncio.Event()


async def start_attempt(context, browsers):
    previous = len(browsers)
    await eventually(
        lambda: context.manager.main_panel.update_login.called
        and context.manager.main_panel.update_login.call_args.args[0]
        == _("gui", "login", "required")
    )
    context.manager.login.confirm()
    await eventually(lambda: len(browsers) > previous and browsers[-1].get.called)
    return browsers[-1]


def messages(context):
    return "\n".join(
        line
        for call in context.manager.main_panel.push_console.call_args_list
        for line in call.args[0]
    )


def assert_clean(context, browser, native_start):
    browser.native_stop.assert_awaited_once()
    assert zd.start is native_start
    assert not context.manager.login.browser_login_active
    context.manager.main_panel.update_browser_login.assert_called_with(url="", starting=False)
    assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]


def test_upstream_android_redirect_flow(login_context, fake_browser):
    native_start = zd.start

    async def run():
        initialize_events(login_context)
        task = asyncio.create_task(login_context.auth._browser_login())
        browser = await start_attempt(login_context, fake_browser)
        url = urlsplit(browser.main_tab.url)
        assert url.scheme == "https"
        assert url.netloc == "www.twitch.tv"
        assert url.path == "/login"
        query = parse_qs(url.query)
        assert query["client_id"] == [ClientType.ANDROID_APP.CLIENT_ID]
        assert parse_qs(query["redirect_params"][0]) == {
            "client_id": [ClientType.ANDROID_APP.CLIENT_ID],
            "redirect_uri": ["https://www.twitch.tv/"],
            "response_type": ["token"],
        }
        assert "--display=:123" in browser.config.browser_args
        assert browser.config.browser_connection_max_tries == 60
        # MFA remains entirely in Twitch's page until it redirects.
        browser.main_tab.url = "https://www.twitch.tv/login?screen=two_factor"
        await asyncio.sleep(0)
        assert not task.done()
        browser.main_tab.url = "https://www.twitch.tv/#access_token=fixture_token&scope="
        assert await asyncio.wait_for(task, timeout=2) == "fixture_token"
        assert "fixture_token" not in messages(login_context)
        login_context.display.__aexit__.assert_awaited_once()
        assert_clean(login_context, browser, native_start)

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["cancel", "timeout", "task", "close", "reload"])
def test_cancellation_cleans_browser_and_all_waiters(
    monkeypatch, login_context, fake_browser, mode
):
    native_start = zd.start
    if mode == "timeout":
        monkeypatch.setattr(browser_login, "LOGIN_TIMEOUT", 0.05)

    async def run():
        initialize_events(login_context)
        task = asyncio.create_task(login_context.auth._browser_login())
        browser = await start_attempt(login_context, fake_browser)
        if mode == "cancel":
            login_context.manager.login.cancel_browser_login()
        elif mode == "task":
            task.cancel()
        elif mode == "close":
            login_context.manager._close_requested.set()
        elif mode == "reload":
            login_context.manager._reload_requested.set()
        if mode in ("cancel", "timeout"):
            await eventually(lambda: login_context.display.__aexit__.await_count == 1)
            await eventually(lambda: not login_context.manager.login.browser_login_active)
            assert "cancelled" in messages(login_context) or "timed out" in messages(login_context)
            task.cancel()
        error = {"close": ExitRequest, "reload": ReloadRequest}.get(mode, asyncio.CancelledError)
        with pytest.raises(error):
            await task
        assert_clean(login_context, browser, native_start)

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["closed", "missing", "protocol", "cancel"])
def test_failed_attempt_can_retry(monkeypatch, login_context, fake_browser, failure):
    native_start = zd.start
    native_factory = zd.Browser

    def factory(config):
        browser = native_factory(config)
        if len(fake_browser) == 1:
            if failure == "missing":
                browser.start.side_effect = FileNotFoundError("browser not installed")
            elif failure == "protocol":
                browser.get.side_effect = RuntimeError("private-token-must-not-be-logged")
        return browser

    monkeypatch.setattr(zd, "Browser", factory)

    async def run():
        initialize_events(login_context)
        task = asyncio.create_task(login_context.auth._browser_login())
        await eventually(lambda: login_context.manager.main_panel.update_login.called)
        login_context.manager.login.confirm()
        await eventually(lambda: bool(fake_browser))
        first = fake_browser[0]
        if failure in ("closed", "cancel"):
            await eventually(lambda: first.get.called)
            if failure == "closed":
                first.stopped = True
            else:
                login_context.manager.login.cancel_browser_login()
        await eventually(lambda: login_context.display.__aexit__.await_count == 1)
        await eventually(lambda: not login_context.manager.login.browser_login_active)
        first.native_stop.assert_awaited_once()
        assert zd.start is native_start
        assert "private-token-must-not-be-logged" not in messages(login_context)
        if failure == "missing":
            assert _("login", "browser", "not_found") in messages(login_context)
        browser = await start_attempt(login_context, fake_browser)
        browser.main_tab.url = "https://www.twitch.tv/#access_token=retry_token"
        assert await asyncio.wait_for(task, timeout=2) == "retry_token"
        assert login_context.display.__aexit__.await_count == 2
        assert_clean(login_context, browser, native_start)

    asyncio.run(run())


def test_cancel_during_browser_start(monkeypatch, login_context, fake_browser):
    native_start = zd.start
    native_factory = zd.Browser

    async def stalled_start():
        await asyncio.Event().wait()

    def factory(config):
        browser = native_factory(config)
        browser.start.side_effect = stalled_start
        return browser

    monkeypatch.setattr(zd, "Browser", factory)

    async def run():
        initialize_events(login_context)
        task = asyncio.create_task(login_context.auth._browser_login())
        await eventually(lambda: login_context.manager.main_panel.update_login.called)
        login_context.manager.login.confirm()
        await eventually(lambda: bool(fake_browser) and fake_browser[0].start.called)
        login_context.manager.login.cancel_browser_login()
        await eventually(lambda: login_context.display.__aexit__.await_count == 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert_clean(login_context, fake_browser[0], native_start)

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["cancel", "task", "close", "reload"])
def test_cancellation_during_browser_cleanup(login_context, fake_browser, mode):
    native_start = zd.start

    async def run():
        initialize_events(login_context)
        task = asyncio.create_task(login_context.auth._browser_login())
        browser = await start_attempt(login_context, fake_browser)
        stopping = asyncio.Event()

        async def slow_stop():
            stopping.set()
            await asyncio.sleep(0.05)
            browser.stopped = True

        browser.native_stop.side_effect = slow_stop
        browser.main_tab.url = "https://www.twitch.tv/#access_token=fixture_token"
        await asyncio.wait_for(stopping.wait(), timeout=2)
        if mode == "cancel":
            login_context.manager.login.cancel_browser_login()
            await eventually(lambda: login_context.display.__aexit__.await_count == 1)
            task.cancel()
        elif mode == "task":
            task.cancel()
        elif mode == "close":
            login_context.manager._close_requested.set()
        elif mode == "reload":
            login_context.manager._reload_requested.set()

        error = {"close": ExitRequest, "reload": ReloadRequest}.get(mode, asyncio.CancelledError)
        with pytest.raises(error):
            await task
        assert browser.stopped
        assert_clean(login_context, browser, native_start)

    asyncio.run(run())


def test_upstream_validation_and_saved_session(monkeypatch, tmp_path, login_context, fake_browser):
    import twitch

    monkeypatch.setattr(twitch, "COOKIES_PATH", tmp_path / "cookies.jar")

    async def run():
        initialize_events(login_context)
        jar = aiohttp.CookieJar()
        jar.update_cookies({"unique_id": "fixture_device"}, ClientType.ANDROID_APP.CLIENT_URL)
        jar.save = MagicMock()
        login_context.twitch.get_session = AsyncMock(return_value=SimpleNamespace(cookie_jar=jar))
        login_context.manager.help = MagicMock()
        requests = []

        @asynccontextmanager
        async def request(method, url, **kwargs):
            if url == ClientType.ANDROID_APP.CLIENT_URL:
                yield SimpleNamespace(text=AsyncMock(return_value="fixture page"))
                return
            requests.append((method, url, kwargs))
            assert url == "https://id.twitch.tv/oauth2/validate"
            assert kwargs["headers"]["Authorization"] == "OAuth fixture_token"
            yield SimpleNamespace(
                status=200,
                json=AsyncMock(return_value={"client_id": ClientType.ANDROID_APP.CLIENT_ID, "user_id": "42"}),
            )

        login_context.twitch.request = request
        task = asyncio.create_task(login_context.auth._validate())
        browser = await start_attempt(login_context, fake_browser)
        browser.main_tab.url = "https://www.twitch.tv/#access_token=fixture_token"
        await asyncio.wait_for(task, timeout=2)
        assert login_context.auth.user_id == 42
        assert login_context.auth._logged_in.is_set()
        assert jar.filter_cookies(ClientType.ANDROID_APP.CLIENT_URL)["auth-token"].value == "fixture_token"
        jar.save.assert_called_once_with(tmp_path / "cookies.jar")
        assert len(requests) == 1
        restored = type(login_context.auth)(login_context.twitch)
        await restored._validate()
        assert restored.access_token == "fixture_token"
        assert restored.user_id == 42
        assert len(fake_browser) == 1
        assert len(requests) == 2

    asyncio.run(run())


def test_legacy_device_code_selects_upstream_oauth():
    result = subprocess.run(
        [sys.executable, "-c", """
import os, sys, types
sys.argv[0] = 'main_webui.py'
os.environ['WEBUI_TWITCH_LOGIN'] = 'device-code'
sys.modules['websocket'] = types.SimpleNamespace(WebsocketPool=object)
sys.modules['gui'] = types.SimpleNamespace(GUIManager=object)
import twitch
import webui.patches
assert twitch._AuthState._browser_login is twitch._AuthState._oauth_login
from webui.adapters.login_form import LoginFormAdapter
assert not LoginFormAdapter(None).browser_login_enabled
"""],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
