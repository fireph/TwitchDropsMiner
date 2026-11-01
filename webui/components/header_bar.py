from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from translate import _
from webui.auth import AuthManager

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class HeaderBar:
    """
    Owns the header bar UI for each client.

    Status text is owned by manager._status_text and bound directly —
    no per-client widget tracking needed for the status label.
    """

    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager

    def build(self, initial_tab: str, on_tab_change):
        """Build the header UI for the current NiceGUI client."""
        # Colours come from webui.themes (see `apply`), which overrides the
        # Quasar primary header background per theme. The tdm-* classes are
        # only hooks; keeping the palette in one module avoids a second,
        # hardcoded blue-grey (slate) palette here.
        with ui.header().classes("tdm-header flex-col items-stretch p-0 gap-0"):
            with ui.row().classes(
                "tdm-header-row w-full items-center q-px-lg q-py-md"
            ):
                ui.image("/icons/pickaxe.ico").classes("w-8 h-8")
                ui.label("Twitch Drops Miner").classes("text-h6")
                ui.space()
                ui.label().classes(
                    "tdm-header-pill text-body1 q-px-md q-py-xs rounded-borders"
                ).bind_text_from(self._manager, "_status_text")
                if AuthManager.AUTH_ENABLED:
                    ui.button(
                        icon="logout",
                        on_click=lambda: ui.run_javascript(AuthManager.logout_js()),
                    ).props("dense flat round").classes("ml-2")

            with ui.tabs(value=initial_tab, on_change=on_tab_change).classes(
                "tdm-tabstrip w-full"
            ) as tabs:
                ui.tab("main", label=_("gui", "tabs", "main"), icon="home")
                ui.tab(
                    "inventory", label=_("gui", "tabs", "inventory"), icon="inventory"
                )
                ui.tab("settings", label=_("gui", "tabs", "settings"), icon="settings")
                ui.tab("help", label=_("gui", "tabs", "help"), icon="help")

        return tabs
