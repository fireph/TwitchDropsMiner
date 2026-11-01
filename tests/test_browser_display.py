"""Viewer URLs must connect to the same public origin as the WebUI."""

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webui import browser_display


@pytest.mark.parametrize(
    "origin,backend_scheme,host,port",
    [
        ("http://localhost:5800", "http", "localhost", "5800"),
        ("http://localhost:5801", "http", "localhost", "5801"),
        ("https://miner.example:8443", "https", "miner.example", "8443"),
        ("https://miner.example", "https", "miner.example", ""),
        ("http://miner.example", "http", "miner.example", ""),
        ("http://[::1]:5800", "http", "[::1]", "5800"),
        ("https://miner.example", "http", "miner.example", ""),
        ("https://miner.example:8443", "http", "miner.example", "8443"),
    ],
)
def test_viewer_uses_public_origin(monkeypatch, origin, backend_scheme, host, port):
    api = FastAPI()
    monkeypatch.setattr(browser_display, "app", api)
    display = browser_display.BrowserDisplay()
    display._key = "fixture-key"

    public_url = urlsplit(origin)
    with TestClient(api, base_url=f"{backend_scheme}://testserver:5800") as client:
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
    assert "encrypt" not in settings
    assert settings["path"] == ["browser-login/socket/fixture-key"]
    assert settings["autoconnect"] == ["1"]
    assert response.headers["cache-control"] == "no-store"
