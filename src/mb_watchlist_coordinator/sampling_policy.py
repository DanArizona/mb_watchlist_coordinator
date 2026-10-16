"""Explicit policy settings and replay-derived ordinary demotion timers.

No production defaults are supplied. Selecting immediate_cap explicitly makes
an active privileged cap override ordinary demotion waits. Other privileged
transition modes require a later implementation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .sampling_projection import SamplingMembership


@dataclass(frozen=True, slots=True)
class SamplingPolicy:
    super_user_id: str
    demotion_grace_seconds: float
    minimum_residence_seconds: float
    restriction_timing: str

    def __post_init__(self):
        if (not isinstance(self.super_user_id, str) or not self.super_user_id.strip()
                or self.super_user_id != self.super_user_id.strip() or self.super_user_id == "__coordinator__"):
            raise ValueError("Policy requires one explicit Super User identity")
        for name in ("demotion_grace_seconds", "minimum_residence_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
            # Check datetime arithmetic bounds before accepting a configuration.
            try:
                timedelta(seconds=value)
            except OverflowError as exc:
                raise ValueError(f"{name} exceeds supported duration") from exc
            object.__setattr__(self, name, float(value))
        if self.restriction_timing != "immediate_cap":
            raise ValueError("Select restriction_timing='immediate_cap' explicitly; other modes are unsupported")

    def payload(self) -> dict:
        return {"super_user_id": self.super_user_id,
                "demotion_grace_seconds": self.demotion_grace_seconds,
                "minimum_residence_seconds": self.minimum_residence_seconds,
                "restriction_timing": self.restriction_timing}


def apply_policy(unrestricted: SamplingMembership, previous: SamplingMembership,
                 restrictions: tuple[Mapping, ...], *, at: datetime, policy: SamplingPolicy,
                 entered: dict, missing: dict):
    """Mutate replay-local timers only; receipts and policy fully reconstruct them."""
    desired = {"focus": set(unrestricted.focus), "hot": set(unrestricted.hot)}
    current = {"focus": set(previous.focus) | desired["focus"],
               "hot": set(previous.hot) | desired["hot"]}
    for restriction in restrictions:
        symbol = restriction["symbol"]
        # Restrictions are maximum permitted groups, never minimum membership.
        current["hot"].discard(symbol)
        desired["hot"].discard(symbol)
        if restriction["max_group"] == "uni":
            current["focus"].discard(symbol)
            desired["focus"].discard(symbol)
    for channel in ("hot", "focus"):
        for key in tuple(entered):
            if key[0] == channel and key[1] not in current[channel]:
                entered.pop(key, None)
                missing.pop(key, None)
        for symbol in current[channel]:
            entered.setdefault((channel, symbol), at)
    holds = []
    # Hot is resolved before Focus so a retained Hot member cannot lose Focus.
    for channel in ("hot", "focus"):
        for symbol in sorted(current[channel]):
            key = (channel, symbol)
            if symbol in desired[channel]:
                missing.pop(key, None)
                continue
            absent_since = missing.setdefault(key, at)
            grace_end = absent_since + timedelta(seconds=policy.demotion_grace_seconds)
            residence_end = entered[key] + timedelta(seconds=policy.minimum_residence_seconds)
            deadline = max(grace_end, residence_end)
            dependency = channel == "focus" and symbol in current["hot"]
            if at >= deadline and not dependency:
                current[channel].remove(symbol)
                entered.pop(key)
                missing.pop(key)
                continue
            reasons = []
            if at < grace_end:
                reasons.append("demotion_grace")
            if at < residence_end:
                reasons.append("minimum_residence")
            if dependency:
                reasons.append("hot_dependency")
            holds.append({"channel": channel, "symbol": symbol,
                          "demand_absent_since_utc": absent_since.astimezone(timezone.utc).isoformat(),
                          "entered_at_utc": entered[key].astimezone(timezone.utc).isoformat(),
                          "demotion_at_utc": deadline.astimezone(timezone.utc).isoformat(),
                          "held_by": reasons})
    capped = SamplingMembership(unrestricted.uni, frozenset(desired["focus"]), frozenset(desired["hot"]))
    applied = SamplingMembership(unrestricted.uni, frozenset(current["focus"]), frozenset(current["hot"]))
    return capped, applied, tuple(holds)
