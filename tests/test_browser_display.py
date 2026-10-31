"""Viewer URLs must connect to the same public origin as the WebUI."""

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webui import browser_display


@pytest.mark.parametrize(
    "origin,host,port,encrypt",
    [
        ("http://localhost:5800", "localhost", "5800", "0"),
        ("http://localhost:5801", "localhost", "5801", "0"),
        ("https://miner.example:8443", "miner.example", "8443", "1"),
        ("https://miner.example", "miner.example", "443", "1"),
        ("http://miner.example", "miner.example", "80", "0"),
        ("http://[::1]:5800", "[::1]", "5800", "0"),
    ],
)
def test_viewer_uses_public_origin(monkeypatch, origin, host, port, encrypt):
    api = FastAPI()
    monkeypatch.setattr(browser_display, "app", api)
    display = browser_display.BrowserDisplay()
    display._key = "fixture-key"

    public_url = urlsplit(origin)
    with TestClient(api, base_url=f"{public_url.scheme}://testserver:5800") as client:
        response = client.get(
            display.view_url,
            headers={"host": public_url.netloc},
            follow_redirects=False,
        )

    assert response.status_code == 307
    location = urlsplit(response.headers["location"])
    assert location.path == "/browser-login/novnc/vnc.html"
    assert not location.query
    settings = parse_qs(location.fragment, keep_blank_values=True)
    assert settings["host"] == [host]
    assert settings["port"] == [port]
    assert settings["encrypt"] == [encrypt]
    assert settings["path"] == ["browser-login/socket/fixture-key"]
    assert settings["autoconnect"] == ["1"]
    assert response.headers["cache-control"] == "no-store"
