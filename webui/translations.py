"""
Fork-specific translations for the WebUI.

Imported for its side effects: merges fork strings into the Translator and
wraps ``set_language`` so ``webui/lang/<language>.json`` overrides are applied
on language switch.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import translate as _translate
from constants import DEFAULT_LANG, IS_PACKAGED, _resource_path
from utils import json_save

# Source of truth for fork-specific strings.  In dev mode this is written to
# webui/lang/English.json so translators can copy it as a template.  At runtime
# it is deep-merged into the Translator so individual upstream keys (e.g.
# gui.*) can be overridden without wiping out siblings.  For other languages,
# set_language's json_load fills missing keys from the patched default
# translation (English fallback); we wrap set_language so
# webui/lang/<language>.json overrides are applied on top.
default_webui_translation: dict[str, Any] = {
    "webui": {
        "settings": {
            "advanced": {
                "unlinked_mode": "Mine unlinked games: ",
                "unlinked_modes": {
                    "off": "Off",
                    "priority": "Only my priority list",
                    "all": "All games",
                },
            },
            "general": {"language": "Language: ", "invalid_proxy": "Invalid proxy URL"},
        },
        "help": {
            "about": "About",
            "created_by": "Application created by:",
            "repository": "Repository:",
            "version": "Version:",
            "donate": "Donate:",
            "donate_text": "If you like the application and found it useful, please consider donating to DevilXD to support them!",
        },
        "auth": {
            "create_account": "Create an admin account",
            "username": "Username",
            "password": "Password",
            "confirm_password": "Confirm password",
            "username_required": "Username Required",
            "password_required": "Password Required",
            "password_mismatch": "Password Mismatch",
            "register": "Register",
            "sign_in": "Sign in",
        },
        "login": {
            "logout": "Logout",
            "browser_title": "Twitch login",
            "browser_login": "Browser login",
            "starting_browser": "Starting browser…",
            "show_browser": "Show login browser",
            "close_view": "Close view",
            "cancel_browser": "Cancel login",
        },
        "inventory": {"no_campaigns": "No campaigns match the current filters."},
        "game_list": {
            "no_campaigns": '"{name}" has no active drop campaigns.',
            "add_anyway": "Add it anyway?",
            "cancel": "Cancel",
            "add": "Add",
        },
        "status": {"name": "Status:"},
    }
}

_WEBUI_LANG_DIR = _resource_path("webui/lang")


def _deep_merge_into(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge_into(dst[k], v)
        else:
            dst[k] = v


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Non-destructive deep merge; *src* wins. Returns a new dict."""
    result = copy.deepcopy(dst)
    _deep_merge_into(result, src)
    return result


# In dev mode, write the English template so translators can copy it.
if not IS_PACKAGED:
    _WEBUI_LANG_DIR.mkdir(parents=True, exist_ok=True)
    json_save(
        _WEBUI_LANG_DIR / f"{DEFAULT_LANG}.json", default_webui_translation, sort=True
    )

# Merge fork strings into the live Translator and default_translation.
_deep_merge_into(_translate.default_translation, default_webui_translation)  # type: ignore[arg-type]
_deep_merge_into(_translate._._translation, default_webui_translation)  # type: ignore[arg-type]

_original_set_language = _translate.Translator.set_language


def _set_language(self: Any, language: str) -> None:
    _original_set_language(self, language)
    _lang_path = _WEBUI_LANG_DIR / f"{language}.json"
    if _lang_path.exists():
        with _lang_path.open(encoding="utf-8") as _f:
            # Non-destructive merge: json_load's merge_json copies references from
            # default_translation into self._translation, so an in-place merge
            # would corrupt default_translation. _deep_merge returns a new dict.
            self._translation = _deep_merge(  # type: ignore[assignment, arg-type]
                self._translation, json.load(_f)
            )


setattr(_translate.Translator, "set_language", _set_language)
