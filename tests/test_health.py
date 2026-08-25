from datetime import datetime, timedelta, timezone

import pytest

from mb_watchlist_coordinator.health import (
    AdapterHealthState,
    AdapterHealthStatus,
)
from mb_watchlist_coordinator.state_store import (
    AdapterStateStore,
)


NOW = datetime(
    2026,
    8,
    25,
    19,
    0,
    tzinfo=timezone.utc,
)


def test_healthy_adapter_health_state():
    health = AdapterHealthState(
        adapter_id="tos",
        status=AdapterHealthStatus.HEALTHY,
        observed_at=NOW,
    )

    assert health.adapter_id == "tos"
    assert health.status is (
        AdapterHealthStatus.HEALTHY
    )
    assert health.reason is None


def test_degraded_health_requires_reason():
    with pytest.raises(
        ValueError,
        match="requires a reason",
    ):
        AdapterHealthState(
            adapter_id="tos",
            status=AdapterHealthStatus.DEGRADED,
            observed_at=NOW,
        )


def test_offline_health_requires_reason():
    with pytest.raises(
        ValueError,
        match="requires a reason",
    ):
        AdapterHealthState(
            adapter_id="tos",
            status=AdapterHealthStatus.OFFLINE,
            observed_at=NOW,
        )


def test_state_store_records_latest_health():
    store = AdapterStateStore()

    degraded = AdapterHealthState(
        adapter_id="tos",
        status=AdapterHealthStatus.DEGRADED,
        observed_at=NOW,
        reason="Could not restore scheduled exports",
        evidence_ref="scanner-status-T19",
    )

    store.record_health(degraded)

    assert store.latest_health(
        "tos"
    ) == degraded


def test_older_health_does_not_replace_newer_health():
    store = AdapterStateStore()

    newer = AdapterHealthState(
        adapter_id="tos",
        status=AdapterHealthStatus.HEALTHY,
        observed_at=NOW,
    )

    older = AdapterHealthState(
        adapter_id="tos",
        status=AdapterHealthStatus.DEGRADED,
        observed_at=NOW - timedelta(minutes=1),
        reason="Old transport failure",
    )

    store.record_health(newer)
    store.record_health(older)

    assert store.latest_health(
        "tos"
    ) == newer
