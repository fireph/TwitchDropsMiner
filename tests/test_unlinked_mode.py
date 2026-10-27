"""Tests for the 3-choice "Mine unlinked games" setting (webui/patches.py).

Covers which unlinked campaigns count as eligible in each mode, and that an
old settings.json with the boolean ``priority_link_override`` still loads.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

# the login patch at the bottom of patches.py would import the tkinter GUI
os.environ["WEBUI_TWITCH_LOGIN"] = "device-code"

import settings as settings_module
import webui.patches  # noqa: E402,F401  (side effects: patches DropsCampaign and Settings)
from inventory import DropsCampaign
from translate import _
from webui.components.settings.general_section import GeneralSection


def _campaign(
    mode: str,
    *,
    linked: bool = False,
    game: str = "Some Game",
    priority: tuple[str, ...] = (),
    exclude: tuple[str, ...] = (),
    badge: bool = False,
    enable_badges_emotes: bool = False,
) -> DropsCampaign:
    campaign = object.__new__(DropsCampaign)
    campaign._twitch = SimpleNamespace(
        settings=SimpleNamespace(
            unlinked_mode=mode,
            priority=list(priority),
            exclude=set(exclude),
            enable_badges_emotes=enable_badges_emotes,
        )
    )
    campaign.linked = linked
    campaign.game = SimpleNamespace(name=game)
    campaign.__dict__["has_badge_or_emote"] = badge
    return campaign


# ---------------------------------------------------------------------------
# Eligibility per mode
# ---------------------------------------------------------------------------


def test_off_keeps_upstream_behaviour():
    assert not _campaign("off", priority=("Some Game",)).eligible
    assert _campaign("off", linked=True).eligible


def test_priority_mode_only_covers_unlinked_games_on_the_list():
    assert _campaign("priority", priority=("Some Game",)).eligible
    assert not _campaign("priority").eligible
    assert not _campaign("priority", priority=("Other Game",)).eligible


def test_priority_mode_ignores_the_exclude_list_like_before():
    assert _campaign("priority", priority=("Some Game",), exclude=("Some Game",)).eligible


def test_all_mode_covers_unlinked_games_not_on_the_list():
    assert _campaign("all").eligible
    assert _campaign("all", priority=("Some Game",)).eligible


def test_all_mode_still_skips_excluded_games():
    assert not _campaign("all", exclude=("Some Game",)).eligible


def test_linked_campaigns_are_eligible_in_every_mode():
    for mode in ("off", "priority", "all"):
        assert _campaign(mode, linked=True).eligible


@pytest.mark.parametrize("mode", ["off", "priority", "all"])
def test_badge_campaigns_follow_the_badge_setting_only(mode: str):
    assert not _campaign(mode, badge=True, priority=("Some Game",)).eligible
    assert _campaign(mode, badge=True, enable_badges_emotes=True).eligible


# ---------------------------------------------------------------------------
# Loading settings.json (old boolean -> new choice)
# ---------------------------------------------------------------------------


@pytest.fixture
def load_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "CONFIG_PATH", tmp_path)
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", tmp_path / "settings.json")

    def load(contents: dict | None = None):
        path = tmp_path / "settings.json"
        if contents is not None:
            path.write_text(json.dumps(contents), encoding="utf-8")
        return settings_module.Settings(SimpleNamespace())

    return load


def test_old_true_loads_as_priority_list_only(load_settings):
    assert load_settings({"priority_link_override": True}).unlinked_mode == "priority"


def test_old_false_loads_as_off(load_settings):
    assert load_settings({"priority_link_override": False}).unlinked_mode == "off"


def test_fresh_install_defaults_to_off(load_settings):
    assert load_settings().unlinked_mode == "off"


def test_chosen_mode_wins_over_the_old_boolean(load_settings):
    loaded = load_settings({"priority_link_override": False, "unlinked_mode": "all"})
    assert loaded.unlinked_mode == "all"


def test_garbage_mode_falls_back_to_the_old_boolean(load_settings):
    loaded = load_settings({"priority_link_override": True, "unlinked_mode": "bogus"})
    assert loaded.unlinked_mode == "priority"


def test_choice_survives_save_and_reload(load_settings):
    first = load_settings()
    first.unlinked_mode = "all"
    first.save(force=True)
    assert load_settings().unlinked_mode == "all"


# ---------------------------------------------------------------------------
# Dropdown
# ---------------------------------------------------------------------------


def test_dropdown_offers_the_three_choices():
    options = GeneralSection._unlinked_mode_options()
    assert list(options) == ["off", "priority", "all"]
    assert all(label and label != key for key, label in options.items())
    assert options["all"] == _("webui", "settings", "advanced", "unlinked_modes", "all")
