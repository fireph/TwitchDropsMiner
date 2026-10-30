"""Tests for webui/themes.py - theme resolution and palette integrity.

The palettes are pure data, so these tests do not need a NiceGUI context. They
pin the two properties that matter: every theme resolves, and the dark/OLED
palettes carry no blue cast (which was the original complaint).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from webui import themes


def test_all_three_themes_registered() -> None:
    assert set(themes.THEMES) == {"light", "dark", "oled"}
    assert themes.DEFAULT_THEME in themes.THEMES


def test_dark_themes_are_marked_dark() -> None:
    assert themes.LIGHT.dark is False
    assert themes.DARK.dark is True
    assert themes.OLED.dark is True


def _channels(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


@pytest.mark.parametrize("theme", [themes.DARK, themes.OLED])
def test_dark_palettes_have_neutral_channels(theme) -> None:
    """No blue cast: R, G and B must be equal for page and surface colours."""
    for color in (theme.page, theme.surface, theme.surface_alt):
        r, g, b = _channels(color)
        assert r == g == b, f"{theme.name} {color} is tinted: R={r} G={g} B={b}"


def test_oled_page_is_pure_black() -> None:
    assert themes.OLED.page == "#000000"


def test_dark_surfaces_are_lighter_than_page() -> None:
    """Cards must stay distinguishable from the page behind them."""
    for theme in (themes.DARK, themes.OLED):
        assert _channels(theme.surface) > _channels(theme.page)


def test_resolve_prefers_explicit_theme() -> None:
    settings = SimpleNamespace(theme="oled", dark_mode=False)
    assert themes.resolve(settings) is themes.OLED


def test_resolve_falls_back_to_legacy_dark_mode() -> None:
    """Existing settings.json files have dark_mode but no theme key."""
    assert themes.resolve(SimpleNamespace(dark_mode=True)) is themes.DARK
    assert themes.resolve(SimpleNamespace(dark_mode=False)) is themes.LIGHT


def test_resolve_ignores_unknown_theme_name() -> None:
    settings = SimpleNamespace(theme="neon", dark_mode=True)
    assert themes.resolve(settings) is themes.DARK


def test_resolve_handles_settings_without_any_theme_key() -> None:
    assert themes.resolve(SimpleNamespace()) is themes.LIGHT
