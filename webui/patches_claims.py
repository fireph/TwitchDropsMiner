"""
Claim each drop once per run, done as webui-only patches so no core file is edited.

For campaigns the account isn't linked to, Twitch accepts the claim but keeps
reporting ``isClaimed: false`` in the inventory. The core loop then re-sent
every such claim on each inventory fetch (hourly, on each channel switch and
on each restart) and printed "Claimed drop" every time. Here the claim IDs
Twitch accepted are remembered (per link state), and a drop with such an ID is treated as
claimed when the inventory is rebuilt.
"""

from __future__ import annotations

import inventory as _inventory

# (claim ID, account linked): linking the account later makes a new attempt worthwhile
_accepted_claims: set[tuple[str, bool]] = set()


def forget_claims() -> None:
    _accepted_claims.clear()


_original_init = _inventory.BaseDrop.__init__
_original_claim_inner = _inventory.BaseDrop._claim


def _init(self, campaign, data, claimed_benefits) -> None:
    _original_init(self, campaign, data, claimed_benefits)
    if (self.claim_id, campaign.linked) in _accepted_claims:
        self.is_claimed = True


async def _claim_inner(self) -> bool:
    result = await _original_claim_inner(self)
    if result and self.claim_id is not None:
        _accepted_claims.add((self.claim_id, self.campaign.linked))
    return result


_inventory.BaseDrop.__init__ = _init  # type: ignore[method-assign]
_inventory.BaseDrop._claim = _claim_inner  # type: ignore[method-assign]
