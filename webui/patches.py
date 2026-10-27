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
import webui.patches_finishable  # noqa

_settings.default_settings["priority_link_override"] = False  # type: ignore[typeddict-unknown-key]


def _priority_link_override_get(self) -> bool:
    """
    True when the user has enabled the advanced "priority link override"
    setting and explicitly added this (unlinked) game to the Priority List.

    This does not change Twitch's reported account-link state; Twitch may
    still refuse to award drops for a campaign the account isn't linked to.
    """
    return (
        self._twitch.settings.priority_link_override
        and not self.linked
        and self.game.name in self._twitch.settings.priority
    )


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
