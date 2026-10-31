from __future__ import annotations

import html
from typing import TYPE_CHECKING

from nicegui import app, ui

from translate import _
from webui.html_utils import close_popup_js, popup_js

if TYPE_CHECKING:
    from webui.manager import WebUIManager

_LOGIN_KEYS = ("logged_in", "logging_in", "required", "logged_out")


class LoginSection:
    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager
        self._login_state: str = ""
        self._user_str: str = "-"
        self._btn_enabled: bool = True
        self._popup_maybe_open: bool = False
        self._browser_view_url = ""
        self._browser_message = ""
        self._browser_starting = False
        self._browser_dialogs: list[ui.dialog] = []

    def update(self, status: str, user_id: int | None) -> None:
        self._login_state = self._key_for_status(status)
        self._user_str = str(user_id) if user_id is not None else "-"
        self._btn_enabled = True
        if self._popup_maybe_open and self._login_state == "logged_in":
            self._close_login_popup()
        if self._login_state == "logged_in":
            for dialog in self._browser_dialogs:
                dialog.close()

    def update_browser(
        self,
        *,
        url: str | None = None,
        message: str | None = None,
        starting: bool | None = None,
    ) -> None:
        if url is not None:
            self._browser_view_url = url
        if message is not None:
            self._browser_message = message
        if starting is not None:
            self._browser_starting = starting

    def build(self) -> None:
        browser_dialog = None
        if self._manager.login.browser_login_enabled:
            with ui.dialog().props("maximized") as browser_dialog:
                with ui.card().classes("w-full h-full flex flex-col gap-2"):
                    with ui.row().classes("w-full items-center"):
                        ui.label(_("webui", "login", "browser_title")).classes(
                            "text-lg font-bold grow"
                        )
                        ui.button(
                            _("webui", "login", "close_view"),
                            on_click=browser_dialog.close,
                        ).props("flat")
                    ui.label().bind_text_from(self, "_browser_message").classes(
                        "text-sm"
                    )
                    with ui.column().classes(
                        "w-full flex-1 items-center justify-center gap-3"
                    ).bind_visibility_from(self, "_browser_starting"):
                        ui.spinner(size="lg")
                        ui.label(_("webui", "login", "starting_browser"))
                    ui.html("", sanitize=False).classes(
                        "w-full flex-1 min-h-0"
                    ).bind_visibility_from(
                        self, "_browser_starting", backward=lambda starting: not starting
                    ).bind_content_from(
                        self,
                        "_browser_view_url",
                        backward=lambda url: (
                            '<iframe src="'
                            + html.escape(url, quote=True)
                            + '" title="Twitch login browser" referrerpolicy="no-referrer" '
                            + 'allowfullscreen '
                            + 'style="width:100%;height:100%;border:0"></iframe>'
                            if url
                            else ""
                        ),
                    )
                    with ui.row():
                        ui.button(
                            _("gui", "login", "button"),
                            on_click=self._manager.login.confirm,
                        ).bind_visibility_from(
                            self,
                            "_login_state",
                            backward=lambda s: s in ("required", "logging_in"),
                        )
                        ui.button(
                            _("webui", "login", "cancel_browser"),
                            on_click=self._manager.login.cancel_browser_login,
                        ).bind_visibility_from(
                            self, "_login_state", backward=lambda s: s == "logging_in"
                        )
            self._browser_dialogs.append(browser_dialog)
            ui.context.client.on_disconnect(
                lambda: self._browser_dialogs.remove(browser_dialog)
            )

        with (
            ui.card().props("flat bordered").classes("gap-1 grow shrink basis-[180px]")
        ):
            ui.label(_("gui", "login", "name")).classes("font-bold text-sm mb-1")
            if self._manager.login.browser_login_enabled:
                with ui.row().classes("items-center gap-2"):
                    ui.spinner(size="sm").bind_visibility_from(self, "_browser_starting")
                    ui.label(_("webui", "login", "browser_login")).classes("text-xs")
            with ui.row().classes("gap-4 items-start"):
                ui.label(_("gui", "login", "labels")).classes(
                    "text-xs whitespace-pre leading-relaxed"
                )
                ui.label().classes(
                    "text-xs whitespace-pre leading-relaxed"
                ).bind_text_from(
                    self,
                    "_login_state",
                    backward=lambda s: (
                        _("gui", "login", s) + "\n" + self._user_str
                        if s in _LOGIN_KEYS
                        else "\n-"
                    ),
                )
            ui.button(
                on_click=lambda: self._on_btn_click(browser_dialog),
            ).props("dense").classes("text-xs").bind_text_from(
                self,
                "_login_state",
                backward=lambda s: (
                    _("webui", "login", "logout")
                    if s == "logged_in"
                    else _("webui", "login", "show_browser")
                    if s == "logging_in" and self._manager.login.browser_login_enabled
                    else _("gui", "login", "button")
                ),
            ).bind_visibility_from(
                self,
                "_login_state",
                backward=lambda s: (
                    s in ("logged_in", "required")
                    or (s == "logging_in" and self._manager.login.browser_login_enabled)
                ),
            ).bind_enabled_from(self, "_btn_enabled")

    async def _open_login_popup(self) -> None:
        url = self._manager.login.page_url
        if url is not None:
            self._popup_maybe_open = True
            blocked = not await ui.run_javascript(popup_js(str(url), "twitch_login"))
            if blocked:
                self._manager.print(f"{str(url)}")
        self._manager.login.confirm()

    def _close_login_popup(self) -> None:
        self._popup_maybe_open = False
        js = close_popup_js("twitch_login")
        for client in app.clients():
            with client:
                ui.run_javascript(js)

    async def _on_btn_click(self, browser_dialog: ui.dialog | None = None) -> None:
        if self._login_state == "logged_in":
            self._btn_enabled = False
            await self._manager.logout()
        elif browser_dialog is not None:
            browser_dialog.open()
            if self._login_state == "required":
                self._manager.login.confirm()
        else:
            await self._open_login_popup()

    @staticmethod
    def _key_for_status(status: str) -> str:
        for key in _LOGIN_KEYS:
            if status == _("gui", "login", key):
                return key
        return ""
