"""
Skip campaigns whose drops can't finish before they end.

Port of DevilXD/TwitchDropsMiner#1202 by kdcao1, done as webui-only patches
so no core file is edited. Games with a drop that can still be completed in
time (with a 5 minute margin) are preferred; the rest are only mined when
nothing else is left. A maintenance trigger fires at the moment a drop stops
being completable, so the games get re-picked right away.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import twitch as _twitch
import inventory as _inventory
from constants import State

# a drop that is this close to being completable in time is still considered completable
FINISH_MARGIN = timedelta(minutes=5)


def _remaining_windows(self) -> list[tuple[_inventory.TimedDrop, datetime]]:
    """Earnable drops paired with the moment they (or the campaign) stop being earnable."""
    now = datetime.now(timezone.utc)
    windows: list[tuple[_inventory.TimedDrop, datetime]] = []
    for drop in self.drops:
        if not drop._base_earn_conditions():
            continue
        end = min(drop.ends_at, self.ends_at)
        if end > now:
            windows.append((drop, end))
    return windows


def _can_finish(self, margin: timedelta = FINISH_MARGIN) -> bool:
    """
    True if at least one earnable drop can still be completed before it ends,
    assuming it earns one minute per minute watched. The margin absorbs small
    inaccuracies in Twitch's reported remaining time.
    """
    now = datetime.now(timezone.utc)
    return any(
        timedelta(minutes=drop.remaining_minutes) <= (end - max(now, drop.starts_at)) + margin
        for drop, end in self._remaining_windows()
    )


def _finish_triggers(self, margin: timedelta = FINISH_MARGIN) -> set[datetime]:
    """Moments at which an earnable drop stops being completable in time."""
    now = datetime.now(timezone.utc)
    triggers: set[datetime] = set()
    for drop, end in self._remaining_windows():
        moment = end - timedelta(minutes=drop.remaining_minutes) + margin
        if moment > now:
            triggers.add(moment)
    return triggers


_inventory.DropsCampaign._remaining_windows = _remaining_windows  # type: ignore[attr-defined]
_inventory.DropsCampaign.can_finish = _can_finish  # type: ignore[attr-defined]
_inventory.DropsCampaign.finish_triggers = _finish_triggers  # type: ignore[attr-defined]


def _prefer_finishable_games(self) -> bool:
    """
    Drop unfinishable games from wanted_games when finishable ones exist.
    Returns False when games were dropped earlier and none of the kept ones can
    finish anymore, meaning the games have to be picked again from scratch.
    """
    next_hour = datetime.now(timezone.utc) + timedelta(hours=1)
    finishable = {
        campaign.game
        for campaign in self.inventory
        if campaign.can_earn_within(next_hour) and campaign.can_finish()
    }
    kept = [game for game in self.wanted_games if game in finishable]
    if kept:
        self._finishable_dropped_games = len(kept) < len(self.wanted_games)
        self.wanted_games[:] = kept
        return True
    dropped_before = getattr(self, "_finishable_dropped_games", False)
    self._finishable_dropped_games = False
    return not dropped_before or self._state is State.GAMES_UPDATE


def _change_state(self, state: State) -> None:
    # Every games pick (GAMES_UPDATE) and every maintenance trigger ends in a
    # CHANNELS_CLEANUP, so pruning here covers both the initial pick and the
    # re-pick when a drop stops being completable. Order is kept as chosen by core.
    if state is State.CHANNELS_CLEANUP and not _prefer_finishable_games(self):
        state = State.GAMES_UPDATE
    _original_change_state(self, state)


async def _fetch_inventory(self) -> None:
    await _original_fetch_inventory(self)
    # The maintenance task was just created but hasn't run yet, so the merged
    # triggers are seen on its first pass. Each one requests a channels cleanup,
    # which re-picks the games through _change_state above.
    now = datetime.now(timezone.utc)
    next_hour = now + timedelta(hours=1)
    triggers: set[datetime] = set(self._mnt_triggers)
    for campaign in self.inventory:
        if campaign.can_earn_within(next_hour):
            triggers.update(campaign.finish_triggers())
    self._mnt_triggers.clear()
    self._mnt_triggers.extend(sorted(t for t in triggers if t > now))


def _get_active_campaign(self, channel=None):
    active = _original_get_active_campaign(self, channel)
    if active is None or active.can_finish():
        return active
    watching_channel = self.watching_channel.get_with_default(channel)
    finishable = [
        campaign
        for campaign in self.inventory
        if campaign.can_earn(watching_channel) and campaign.can_finish()
    ]
    if finishable:
        return min(finishable, key=lambda c: c.remaining_minutes)
    return active


_original_change_state = _twitch.Twitch.change_state
_original_fetch_inventory = _twitch.Twitch.fetch_inventory
_original_get_active_campaign = _twitch.Twitch.get_active_campaign
_twitch.Twitch.change_state = _change_state  # type: ignore[method-assign]
_twitch.Twitch.fetch_inventory = _fetch_inventory  # type: ignore[method-assign]
_twitch.Twitch.get_active_campaign = _get_active_campaign  # type: ignore[method-assign]
