"""Browser lifecycle support for upstream's Twitch login flow."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from pathlib import Path
from typing import Any, TYPE_CHECKING, TypeVar

from exceptions import ExitRequest, ReloadRequest

if TYPE_CHECKING:
    from zendriver import Browser

LOGIN_TIMEOUT = 600
_T = TypeVar("_T")


class BrowserLoginError(Exception):
    pass


class BrowserLoginRetry(Exception):
    """Return upstream's retry prompt to the WebUI's Login button."""


def browser_executable() -> str | None:
    if configured := os.environ.get("WEBUI_BROWSER_PATH"):
        return configured
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        if installed := shutil.which(name):
            return installed
    cache = Path(
        os.environ.get(
            "PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache/ms-playwright")
        )
    )
    candidates = list(cache.glob("chromium-*/chrome-linux*/chrome"))
    return str(max(candidates, key=lambda p: p.stat().st_mtime)) if candidates else None


async def first_to_complete(coros: Iterable[Coroutine[Any, Any, _T]]) -> _T:
    # Upstream's helper leaves its children running when the caller is cancelled.
    # WebUI login can be cancelled or timed out while those children await a click.
    tasks = [asyncio.create_task(coro) for coro in coros]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        return await next(iter(done))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def browser_login(
    login: Callable[[], Awaitable[str]],
    display: str,
    cancel: asyncio.Event,
    report: Callable[[str], None],
    *,
    on_ready: Callable[[Browser], None],
) -> str:
    import zendriver as zd

    # CDP debug messages include tokens and complete login requests.
    logging.getLogger("zendriver").setLevel(logging.WARNING)
    browser = None
    native_start = zd.start

    async def start_browser():
        nonlocal browser
        config = zd.Config(
            browser_executable_path=browser_executable(),
            headless=False,
            # Zendriver's 2.5-second default is too short for a busy NAS.
            browser_connection_timeout=0.25,
            browser_connection_max_tries=60,
            browser_args=[
                f"--display={display}",
                "--ozone-platform=x11",
                "--window-size=1280,900",
            ],
        )
        current = browser = zd.Browser(config)
        native_stop = current.stop
        stop_task: asyncio.Task[None] | None = None

        async def cleanup_browser():
            # Zendriver 0.17 leaves Popen pipes open and cancels listeners
            # without awaiting them. Drain both before the next attempt.
            process = getattr(current, "_process", None)
            connections = [getattr(current, "connection", None), *current.targets]
            listeners = [
                connection.listener.task
                for connection in connections
                if connection is not None
                and connection.listener is not None
                and connection.listener.task is not None
            ]
            try:
                await native_stop()
            except Exception as exc:  # noqa: BLE001 -- Protocol errors may contain tokens.
                report(f"Browser cleanup failed ({type(exc).__name__}).")
            finally:
                for listener in listeners:
                    if not listener.done():
                        listener.cancel()
                await asyncio.gather(*listeners, return_exceptions=True)
                if process is not None:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()

        async def stop_browser():
            nonlocal stop_task
            if stop_task is None:
                stop_task = asyncio.create_task(cleanup_browser())
            # Cancellation can arrive during upstream's finally block. Let
            # cleanup finish; our outer finally awaits the same task again.
            await asyncio.shield(stop_task)

        current.stop = stop_browser
        await current.start()
        on_ready(current)
        return current

    async def cancelled() -> str:
        try:
            await asyncio.wait_for(cancel.wait(), timeout=LOGIN_TIMEOUT)
        except asyncio.TimeoutError:
            raise BrowserLoginError(
                "Browser login timed out after 10 minutes. Click Login to try again."
            ) from None
        raise BrowserLoginError("Browser login cancelled.")

    # AuthState serializes login attempts. Only replace the launcher while the
    # upstream flow runs; it owns the login URL, token extraction and retries.
    zd.start = start_browser
    try:
        return await first_to_complete([login(), cancelled()])
    except (BrowserLoginError, BrowserLoginRetry, ExitRequest, ReloadRequest):
        raise
    except Exception as exc:  # noqa: BLE001 -- Do not expose browser protocol payloads.
        raise BrowserLoginError(
            f"Browser login could not run ({type(exc).__name__}). Check WEBUI_BROWSER_PATH and browser dependencies."
        ) from None
    finally:
        try:
            if browser is not None:
                await browser.stop()
        finally:
            zd.start = native_start
