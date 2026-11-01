"""Opt-in Chromium/Xvfb tests with locally fulfilled Twitch pages."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TDM_BROWSER_TESTS") != "1",
    reason="Set TDM_BROWSER_TESTS=1 with Chromium, Xvfb and noVNC installed.",
)


def test_real_browser_upstream_redirect_and_mfa(monkeypatch, webui_auth_state):
    import zendriver as zd
    from fastapi import FastAPI

    from constants import ClientType
    from translate import _
    from webui import browser_display, browser_login
    from webui.adapters.login_form import LoginFormAdapter
    from webui.manager import WebUIManager

    requests = []
    login_urls = []
    native_get = zd.Browser.get
    monkeypatch.setenv("WEBUI_TWITCH_LOGIN", "android-browser")
    monkeypatch.setattr(browser_display, "app", FastAPI())
    monkeypatch.setattr(browser_login, "LOGIN_TIMEOUT", 30)

    async def fixture_get(browser, url, *args, **kwargs):
        login_urls.append(url)
        tab = await native_get(browser, "about:blank")

        async def fulfill(event):
            # Fulfill every request locally. Nothing, including fixture
            # credentials, goes to Twitch or any other external service.
            path = urlsplit(event.request.url).path
            status, content_type, body = 200, "text/html", ""
            if path == "/login":
                body = """<h1>Local login fixture</h1>
<script>
addEventListener('load', async () => {
  const payload = {username: 'fixture', password: 'fixture-password'};
  await fetch('/protected_login', {method:'POST',body:JSON.stringify(payload)});
  payload.authy_token = '123456';
  const response = await fetch('/protected_login', {method:'POST',body:JSON.stringify(payload)});
  const result = await response.json();
  location.href = '/#access_token=' + result.access_token;
});
</script>"""
            elif path == "/protected_login":
                payload = json.loads(event.request.post_data)
                requests.append(payload)
                content_type = "application/json"
                if "authy_token" in payload:
                    body = json.dumps({"access_token": "fixture_android_token"})
                else:
                    status = 400
                    body = json.dumps({"error_code": 3011})
            await tab.send(zd.cdp.fetch.fulfill_request(
                event.request_id,
                status,
                response_headers=[zd.cdp.fetch.HeaderEntry(name="Content-Type", value=content_type)],
                body=base64.b64encode(body.encode()).decode(),
            ))

        tab.add_handler(zd.cdp.fetch.RequestPaused, fulfill)
        await tab.send(zd.cdp.fetch.enable())
        return await native_get(browser, url, *args, **kwargs)

    monkeypatch.setattr(zd.Browser, "get", fixture_get)

    async def run():
        manager = SimpleNamespace(
            main_panel=MagicMock(),
            status=MagicMock(),
            _twitch=SimpleNamespace(settings=SimpleNamespace(stdlog=False)),
            _close_requested=asyncio.Event(),
            _reload_requested=asyncio.Event(),
        )
        manager.print = WebUIManager.print.__get__(manager)
        manager.coro_unless_closed = WebUIManager.coro_unless_closed.__get__(manager)
        manager.login = LoginFormAdapter(manager)

        def update(status, _user_id):
            if status == _("gui", "login", "required"):
                asyncio.get_running_loop().call_soon(manager.login.confirm)

        manager.main_panel.update_login.side_effect = update
        auth = webui_auth_state(SimpleNamespace(gui=manager, _client_type=ClientType.ANDROID_APP))
        assert await asyncio.wait_for(auth._browser_login(), timeout=40) == "fixture_android_token"
        assert not manager.login._browser_display.view_url
        assert not manager.login._browser_display._processes
        reports = str(manager.main_panel.push_console.call_args_list)
        assert "fixture-password" not in reports
        assert "fixture_android_token" not in reports

    asyncio.run(run())
    assert len(login_urls) == 1
    query = parse_qs(urlsplit(login_urls[0]).query)
    assert query["client_id"] == [ClientType.ANDROID_APP.CLIENT_ID]
    assert parse_qs(query["redirect_params"][0])["response_type"] == ["token"]
    assert requests == [
        {"username": "fixture", "password": "fixture-password"},
        {"username": "fixture", "password": "fixture-password", "authy_token": "123456"},
    ]


def test_viewer_websocket_is_scoped_to_active_attempt(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from webui import browser_display

    api = FastAPI()
    monkeypatch.setattr(browser_display, "app", api)

    async def run():
        display = browser_display.BrowserDisplay()
        with TestClient(api) as client:
            assert client.get("/browser-login/view/expired").status_code == 410
            async with display:
                view_url = display.view_url
                assert client.get(view_url).status_code == 200
                assert client.get("/browser-login/novnc/core/rfb.js").status_code == 200
                socket_url = view_url.replace("/view/", "/socket/")
                with (
                    pytest.raises(WebSocketDisconnect),
                    client.websocket_connect(
                        socket_url, headers={"origin": "https://untrusted.example"}
                    ),
                ):
                    pass
                with (
                    pytest.raises(WebSocketDisconnect),
                    client.websocket_connect(
                        "/browser-login/socket/wrong-key",
                        headers={"origin": "http://testserver"},
                    ),
                ):
                    pass
                with client.websocket_connect(
                    socket_url, headers={"origin": "http://testserver"}
                ) as socket:
                    version = socket.receive_bytes()
                    assert version.startswith(b"RFB ")
                    socket.send_bytes(version)
                    assert socket.receive_bytes()
            assert client.get(view_url).status_code == 410
            with (
                pytest.raises(WebSocketDisconnect),
                client.websocket_connect(
                    socket_url, headers={"origin": "http://testserver"}
                ),
            ):
                pass

    asyncio.run(run())


@pytest.mark.parametrize("tls_proxy", [False, True])
def test_novnc_page_connects_in_chromium(monkeypatch, tmp_path, tls_proxy):
    import socket
    import subprocess

    import uvicorn
    import zendriver as zd
    from fastapi import FastAPI

    from webui import browser_display, browser_login

    api = FastAPI()
    monkeypatch.setattr(browser_display, "app", api)
    tls_options = {}
    if tls_proxy:
        key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost",
             "-days", "1"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        tls_options = {"ssl_keyfile": str(key), "ssl_certfile": str(cert)}

        @api.middleware("http")
        async def http_backend(request, call_next):
            # Model TLS termination: the browser sees HTTPS, the app sees HTTP.
            request.scope["scheme"] = "http"
            return await call_next(request)

    async def run():
        display = browser_display.BrowserDisplay()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(api, log_level="error", **tls_options))
            server_task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                while not server.started:
                    await asyncio.sleep(0.01)
                async with display:
                    async def connect_viewer():
                        browser = await zd.start()
                        tab = await browser.get("about:blank")
                        if tls_proxy:
                            await tab.send(zd.cdp.security.set_ignore_certificate_errors(True))
                        scheme = "https" if tls_proxy else "http"
                        await tab.get(f"{scheme}://127.0.0.1:{port}{display.view_url}")
                        await tab.select("#noVNC_container", timeout=10)
                        for _ in range(100):
                            if await tab.evaluate(
                                "document.documentElement.classList.contains('noVNC_connected')"
                            ):
                                return "connected"
                            await asyncio.sleep(0.1)
                        return await tab.evaluate(
                            "document.getElementById('noVNC_status')?.textContent"
                        )

                    result = await asyncio.wait_for(
                        browser_login.browser_login(
                            connect_viewer,
                            display.display,
                            asyncio.Event(),
                            lambda _message: None,
                            on_ready=lambda _browser: None,
                        ),
                        timeout=30,
                    )
                    assert result == "connected"
            finally:
                server.should_exit = True
                await server_task

    asyncio.run(run())
