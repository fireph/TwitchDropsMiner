"""
WebUI-only monkey-patches that extend core classes without editing them.

Imported once from ``main_webui.py`` after the core modules are loaded, so the
fork keeps its diff against upstream minimal.
"""

from __future__ import annotations

import os

import settings as _settings
import inventory as _inventory

import webui.translations  # noqa

UNLINKED_OFF = "off"
UNLINKED_PRIORITY = "priority"
UNLINKED_ALL = "all"
UNLINKED_MODES = (UNLINKED_OFF, UNLINKED_PRIORITY, UNLINKED_ALL)

# "" means no choice saved yet; Settings.__init__ below fills it in from the old checkbox.
_settings.default_settings["unlinked_mode"] = ""  # type: ignore[typeddict-unknown-key]
# Only read for that migration. Kept in the defaults so json_load doesn't drop it.
_settings.default_settings["priority_link_override"] = False  # type: ignore[typeddict-unknown-key]

_original_settings_init = _settings.Settings.__init__


def _settings_init(self, args) -> None:
    _original_settings_init(self, args)
    if self._settings["unlinked_mode"] not in UNLINKED_MODES:
        self._settings["unlinked_mode"] = (
            UNLINKED_PRIORITY
            if self._settings["priority_link_override"]
            else UNLINKED_OFF
        )


_settings.Settings.__init__ = _settings_init  # type: ignore[method-assign]


def _priority_link_override_get(self) -> bool:
    """
    True when the "Mine unlinked games" setting makes this (unlinked) campaign
    eligible: "priority" for games on the Priority List, "all" for every game
    that isn't on the Exclude list.

    This does not change Twitch's reported account-link state; Twitch may
    still refuse to award drops for a campaign the account isn't linked to.
    """
    settings = self._twitch.settings
    if self.linked or settings.unlinked_mode == UNLINKED_OFF:
        return False
    if settings.unlinked_mode == UNLINKED_ALL:
        return self.game.name not in settings.exclude
    return self.game.name in settings.priority


setattr(
    _inventory.DropsCampaign,
    "priority_link_override",
    property(_priority_link_override_get),
)


def _eligible_get(self) -> bool:
    return _original_eligible(self) or (
        not self.has_badge_or_emote and self.priority_link_override
    )


_original_eligible = _inventory.DropsCampaign.__dict__["eligible"].fget

setattr(
    _inventory.DropsCampaign,
    "eligible",
    property(_eligible_get),
)


if os.environ.get("WEBUI_TWITCH_LOGIN", "android-browser") == "android-browser":
    import twitch as _twitch

    async def _android_browser_login(self) -> str:
        return await self._twitch.gui.login.ask_browser_login()

    _twitch._AuthState._oauth_login = _android_browser_login
