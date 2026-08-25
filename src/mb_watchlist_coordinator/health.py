from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AdapterHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


@dataclass(frozen=True, slots=True)
class AdapterHealthState:
    adapter_id: str
    status: AdapterHealthStatus
    observed_at: datetime

    reason: str | None = None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.adapter_id:
            raise ValueError(
                "Adapter health state requires adapter_id"
            )

        if (
            self.status
            in {
                AdapterHealthStatus.DEGRADED,
                AdapterHealthStatus.OFFLINE,
            }
            and not self.reason
        ):
            raise ValueError(
                f"{self.status.value} adapter health "
                "requires a reason"
            )
