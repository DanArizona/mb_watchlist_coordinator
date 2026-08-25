from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .adapter_state import AdapterObservedState
from .health import AdapterHealthState

@dataclass(frozen=True, slots=True)
class AdapterObservationResult:
    observed_state: AdapterObservedState
    health_state: AdapterHealthState | None = None

    def __post_init__(self) -> None:
        if (
            self.health_state is not None
            and self.health_state.adapter_id
            != self.observed_state.adapter_id
        ):
            raise ValueError(
                "Observation and health state must "
                "refer to the same adapter"
            )


class MaterializationExecutionStatus(StrEnum):
    OBSERVED = "OBSERVED"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


@dataclass(frozen=True, slots=True)
class MaterializationExecutionResult:
    transaction_id: str
    status: MaterializationExecutionStatus

    observed_state: AdapterObservedState | None = None
    reason: str | None = None
    health_state: AdapterHealthState | None = None

    def __post_init__(self) -> None:
        if self.status is MaterializationExecutionStatus.OBSERVED:
            if self.observed_state is None:
                raise ValueError(
                    "OBSERVED execution result requires "
                    "an observed_state"
                )

            if self.reason is not None:
                raise ValueError(
                    "OBSERVED execution result must not "
                    "include a failure reason"
                )

            return

        if self.observed_state is not None:
            raise ValueError(
                f"{self.status.value} execution result "
                "must not include observed_state"
            )

        if not self.reason:
            raise ValueError(
                f"{self.status.value} execution result "
                "requires a reason"
            )
