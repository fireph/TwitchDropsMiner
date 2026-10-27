"""Skip campaigns whose drops can't finish before they end (port of DevilXD#1202).

Covers ``webui/patches_finishable.py``: the per-campaign "can it still finish?"
check with its 5 minute margin, preferring finishable games with a fallback
when nothing else is left, the deadline triggers, and the active campaign pick.
"""

from __future__ import annotations

import sys
import types
import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

if "gui" not in sys.modules:
    # same stub main_webui.py installs, so importing twitch.py doesn't pull in tkinter
    from webui import WebUIManager

    _gui_stub = types.ModuleType("gui")
    _gui_stub.GUIManager = WebUIManager  # type: ignore[attr-defined]
    sys.modules["gui"] = _gui_stub

# conftest.py stubs ``websocket`` for engineio; twitch.py needs the project's real module
_ws_stub = sys.modules.pop("websocket", None)
try:
    import twitch  # noqa: E402
finally:
    if _ws_stub is not None:
        sys.modules["websocket"] = _ws_stub
import inventory  # noqa: E402
from constants import State  # noqa: E402
import webui.patches  # noqa: E402,F401
import webui.patches_finishable as pf  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fake_twitch() -> SimpleNamespace:
    return SimpleNamespace(
        settings=SimpleNamespace(
            enable_badges_emotes=False,
            priority_link_override=False,
            priority=[],
            exclude=set(),
        )
    )


def _drop(
    drop_id: str,
    *,
    required: int,
    watched: int = 0,
    ends_in: timedelta | None = None,
    starts_in: timedelta = timedelta(days=-1),
    claimed: bool = False,
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": drop_id,
        "name": drop_id,
        "benefitEdges": [{
            "benefit": {
                "id": f"b-{drop_id}",
                "name": f"reward {drop_id}",
                "distributionType": "DIRECT_ENTITLEMENT",
                "imageAssetURL": "",
            }
        }],
        "startAt": _iso(now + starts_in),
        "endAt": _iso(now + (ends_in or timedelta(days=30))),
        "requiredMinutesWatched": required,
        "preconditionDrops": None,
        "self": {
            "dropInstanceID": None,
            "isClaimed": claimed,
            "currentMinutesWatched": watched,
        },
    }


def _campaign(
    *drops: dict,
    ends_in: timedelta,
    starts_in: timedelta = timedelta(days=-1),
    game_id: int = 1,
    campaign_id: str = "c1",
    twitch_obj: SimpleNamespace | None = None,
) -> inventory.DropsCampaign:
    now = datetime.now(timezone.utc)
    data = {
        "id": campaign_id,
        "name": campaign_id,
        "game": {
            "id": str(game_id),
            "name": f"Game {game_id}",
            "boxArtURL": "https://example.invalid/box-285x380.jpg",
        },
        "self": {"isAccountConnected": True},
        "accountLinkURL": "",
        "startAt": _iso(now + starts_in),
        "endAt": _iso(now + ends_in),
        "status": "ACTIVE",
        "allow": {"channels": None},
        "timeBasedDrops": list(drops),
    }
    return inventory.DropsCampaign(twitch_obj or _fake_twitch(), data, {})


def _finishable(game_id: int, campaign_id: str | None = None) -> inventory.DropsCampaign:
    # 60 minutes left to watch, 5 hours left in the campaign
    return _campaign(
        _drop(f"d{game_id}", required=120, watched=60),
        ends_in=timedelta(hours=5),
        game_id=game_id,
        campaign_id=campaign_id or f"fin{game_id}",
    )


def _unfinishable(game_id: int, campaign_id: str | None = None) -> inventory.DropsCampaign:
    # 60 minutes left to watch, 30 minutes left in the campaign
    return _campaign(
        _drop(f"u{game_id}", required=120, watched=60),
        ends_in=timedelta(minutes=30),
        game_id=game_id,
        campaign_id=campaign_id or f"unf{game_id}",
    )


# ---------------------------------------------------------------------------
# DropsCampaign.can_finish
# ---------------------------------------------------------------------------


def test_can_finish_with_enough_time_left():
    assert _finishable(1).can_finish() is True


def test_cannot_finish_with_too_little_time_left():
    assert _unfinishable(1).can_finish() is False


@pytest.mark.parametrize(
    ("remaining", "expected"),
    [
        (60, True),   # exactly enough time
        (64, True),   # 4 minutes short, inside the 5 minute margin
        (66, False),  # 6 minutes short, outside the margin
    ],
)
def test_five_minute_margin(remaining, expected):
    campaign = _campaign(
        _drop("d", required=remaining),
        ends_in=timedelta(minutes=60, seconds=30),
    )
    assert campaign.can_finish() is expected


def test_drop_ending_before_campaign_uses_drop_end():
    campaign = _campaign(
        _drop("d", required=60, ends_in=timedelta(minutes=30)),
        ends_in=timedelta(hours=5),
    )
    assert campaign.can_finish() is False


def test_time_before_a_drop_starts_doesnt_count():
    campaign = _campaign(
        _drop("later", required=60, starts_in=timedelta(minutes=50)),
        ends_in=timedelta(minutes=70),
    )
    assert campaign.can_finish() is False


def test_one_finishable_drop_is_enough():
    campaign = _campaign(
        _drop("long", required=600),
        _drop("short", required=30),
        ends_in=timedelta(hours=2),
    )
    assert campaign.can_finish() is True


def test_claimed_drops_dont_count_as_finishable():
    campaign = _campaign(
        _drop("done", required=60, watched=60, claimed=True),
        _drop("long", required=600),
        ends_in=timedelta(hours=2),
    )
    assert campaign.can_finish() is False


def test_finish_triggers_mark_when_drop_becomes_unfinishable():
    campaign = _campaign(_drop("d", required=60), ends_in=timedelta(hours=2))
    expected = campaign.ends_at - timedelta(minutes=60) + pf.FINISH_MARGIN
    assert campaign.finish_triggers() == {expected}


def test_finish_triggers_skip_moments_already_past():
    assert _unfinishable(1).finish_triggers() == set()


# ---------------------------------------------------------------------------
# Game selection: finishable games first, the rest only as a fallback
# ---------------------------------------------------------------------------


def _fake_client(wanted: list, campaigns: list) -> SimpleNamespace:
    return SimpleNamespace(
        _state=State.GAMES_UPDATE,
        _state_change=MagicMock(),
        wanted_games=list(wanted),
        inventory=list(campaigns),
        _mnt_triggers=deque(),
    )


def test_unfinishable_games_are_dropped_when_finishable_ones_exist():
    a, b, c = _unfinishable(1), _finishable(2), _finishable(3)
    client = _fake_client([a.game, b.game, c.game], [a, b, c])
    twitch.Twitch.change_state(client, State.CHANNELS_CLEANUP)
    assert client.wanted_games == [b.game, c.game]
    assert client._state is State.CHANNELS_CLEANUP


def test_unfinishable_games_are_kept_when_nothing_else_is_left():
    a, b = _unfinishable(1), _unfinishable(2)
    client = _fake_client([a.game, b.game], [a, b])
    twitch.Twitch.change_state(client, State.CHANNELS_CLEANUP)
    assert client.wanted_games == [a.game, b.game]


def test_game_with_one_finishable_campaign_is_kept():
    a_short, a_long, b = _unfinishable(1), _finishable(1), _unfinishable(2)
    client = _fake_client([a_short.game, b.game], [a_short, a_long, b])
    twitch.Twitch.change_state(client, State.CHANNELS_CLEANUP)
    assert client.wanted_games == [a_short.game]


def test_finishable_campaign_must_be_earnable_within_the_hour():
    later = _campaign(
        _drop("later", required=60),
        ends_in=timedelta(days=5),
        starts_in=timedelta(days=2),
        game_id=1,
        campaign_id="later",
    )
    now_unf = _unfinishable(1)
    other = _unfinishable(2)
    client = _fake_client([now_unf.game, other.game], [now_unf, later, other])
    twitch.Twitch.change_state(client, State.CHANNELS_CLEANUP)
    assert client.wanted_games == [now_unf.game, other.game]


def test_games_are_repicked_when_kept_games_stop_being_finishable():
    a, b = _unfinishable(1), _finishable(2)
    client = _fake_client([a.game, b.game], [a, b])
    twitch.Twitch.change_state(client, State.CHANNELS_CLEANUP)
    assert client.wanted_games == [b.game]
    # later, B can't finish anymore either: the dropped fallback games must come back
    client.inventory = [a, _unfinishable(2)]
    client._state = State.CHANNELS_FETCH
    twitch.Twitch.change_state(client, State.CHANNELS_CLEANUP)
    assert client._state is State.GAMES_UPDATE


def test_games_pick_with_nothing_finishable_goes_on_to_cleanup():
    a, b = _unfinishable(1), _unfinishable(2)
    client = _fake_client([a.game, b.game], [a, b])
    twitch.Twitch.change_state(client, State.CHANNELS_CLEANUP)
    assert client._state is State.CHANNELS_CLEANUP
    assert client.wanted_games == [a.game, b.game]


def test_other_state_changes_leave_wanted_games_alone():
    a, b = _unfinishable(1), _finishable(2)
    client = _fake_client([a.game, b.game], [a, b])
    twitch.Twitch.change_state(client, State.INVENTORY_FETCH)
    assert client.wanted_games == [a.game, b.game]
    assert client._state is State.INVENTORY_FETCH


# ---------------------------------------------------------------------------
# Deadline triggers: a cleanup is scheduled when a drop stops being finishable
# ---------------------------------------------------------------------------


def test_fetch_inventory_schedules_finish_triggers(monkeypatch):
    soon = _campaign(_drop("d", required=60), ends_in=timedelta(hours=2), campaign_id="soon")
    upcoming = _campaign(
        _drop("u", required=60),
        ends_in=timedelta(days=5),
        starts_in=timedelta(days=2),
        game_id=2,
        campaign_id="upcoming",
    )
    existing = datetime.now(timezone.utc) + timedelta(minutes=10)

    async def fake_original(self):
        self.inventory[:] = [soon, upcoming]
        self._mnt_triggers.extend([existing])

    monkeypatch.setattr(pf, "_original_fetch_inventory", fake_original)
    client = _fake_client([], [])
    asyncio.run(twitch.Twitch.fetch_inventory(client))
    assert list(client._mnt_triggers) == sorted({existing} | soon.finish_triggers())


# ---------------------------------------------------------------------------
# Active campaign: finishable campaigns are watched first
# ---------------------------------------------------------------------------


def _active_client(campaigns: list) -> SimpleNamespace:
    channel = object()
    for campaign in campaigns:
        campaign.can_earn = lambda *args, **kwargs: True
    return SimpleNamespace(
        wanted_games=[campaigns[0].game],
        watching_channel=SimpleNamespace(get_with_default=lambda ch: ch or channel),
        inventory=list(campaigns),
    )


def test_active_campaign_prefers_finishable_over_fewer_minutes():
    unf = _campaign(
        _drop("short", required=30), ends_in=timedelta(minutes=10), campaign_id="unf"
    )
    fin = _campaign(
        _drop("long", required=100), ends_in=timedelta(hours=5), campaign_id="fin"
    )
    client = _active_client([unf, fin])
    assert twitch.Twitch.get_active_campaign(client) is fin


def test_active_campaign_falls_back_when_nothing_can_finish():
    first = _campaign(
        _drop("a", required=30), ends_in=timedelta(minutes=10), campaign_id="a"
    )
    second = _campaign(
        _drop("b", required=100), ends_in=timedelta(minutes=10), campaign_id="b"
    )
    client = _active_client([second, first])
    assert twitch.Twitch.get_active_campaign(client) is first
