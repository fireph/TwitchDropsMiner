"""Tests for claiming each drop once per run (webui/patches_claims.py).

For campaigns the account isn't linked to, Twitch answers the claim with
success but keeps reporting ``isClaimed: false`` in the inventory. Without a
memory of what was already claimed, the miner re-sent every such claim on
every inventory fetch (each hour, each channel switch, each restart).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import webui.patches_claims as claims  # importing it patches the drop classes
from inventory import TimedDrop


def _twitch(responses: list[dict]):
    calls: list[dict] = []

    async def gql_request(query):
        calls.append(query)
        return responses.pop(0) if len(responses) > 1 else responses[0]

    printed: list[str] = []
    return SimpleNamespace(
        gql_request=gql_request,
        print=printed.append,
        gui=SimpleNamespace(
            tray=SimpleNamespace(notify=lambda *_, **__: None),
            inv=SimpleNamespace(update_drop=lambda _drop: None),
        ),
        calls=calls,
        printed=printed,
    )


def _drop(
    twitch,
    drop_id: str = "d1",
    claim_id: str = "u#c#d1",
    claimed: bool = False,
    linked: bool = False,
):
    now = datetime.now(timezone.utc)
    stamp = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    campaign = SimpleNamespace(
        _twitch=twitch,
        linked=linked,
        ends_at=now + timedelta(days=2),
        game=SimpleNamespace(name="Some Game"),
        claimed_drops=1,
        total_drops=1,
    )
    data = {
        "id": drop_id,
        "name": drop_id,
        "benefitEdges": [],
        "startAt": stamp(now - timedelta(days=1)),
        "endAt": stamp(now + timedelta(days=2)),
        "preconditionDrops": [],
        "requiredMinutesWatched": 60,
        "self": {
            "dropInstanceID": claim_id,
            "isClaimed": claimed,
            "currentMinutesWatched": 60,
        },
    }
    return TimedDrop(campaign, data, {})


OK = {"data": {"claimDropRewards": {"status": "ELIGIBLE_FOR_ALL"}}}
FAILED = {"data": {"errors": [{"message": "nope"}]}}


def setup_function(_):
    claims.forget_claims()


def test_drop_claimed_this_run_is_not_claimable_after_the_next_inventory_fetch():
    twitch = _twitch([OK])
    assert asyncio.run(_drop(twitch).claim()) is True
    assert len(twitch.calls) == 1

    # next fetch: Twitch still reports the same drop as not claimed
    refetched = _drop(twitch)
    assert refetched.is_claimed
    assert not refetched.can_claim
    assert len(twitch.printed) == 1  # "Claimed drop" was announced once


def test_failed_claim_is_retried_on_the_next_fetch():
    twitch = _twitch([FAILED])
    assert asyncio.run(_drop(twitch).claim()) is False

    refetched = _drop(twitch)
    assert not refetched.is_claimed
    assert refetched.can_claim


def test_claim_is_retried_once_the_account_gets_linked():
    twitch = _twitch([OK])
    asyncio.run(_drop(twitch).claim())

    after_linking = _drop(twitch, linked=True)
    assert not after_linking.is_claimed
    assert after_linking.can_claim


def test_other_drops_are_not_affected():
    twitch = _twitch([OK])
    asyncio.run(_drop(twitch, "d1", "u#c#d1").claim())

    other = _drop(twitch, "d2", "u#c#d2")
    assert not other.is_claimed
    assert other.can_claim


def test_drop_without_claim_id_is_left_alone():
    twitch = _twitch([OK])
    drop = _drop(twitch)
    drop.claim_id = None
    assert not drop.can_claim
    assert asyncio.run(drop.claim()) is False
    assert twitch.calls == []
