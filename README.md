# mb_watchlist_coordinator

Authoritative Watchlist coordination and adapter-reconciliation logic for the MasterBot project.

> **Development status:** Work in progress / proof of concept.
> The core coordination, lifecycle, reconciliation, transaction, verification, and ThinkOrSwim planning models are implemented and tested. Live ThinkOrSwim execution currently lives outside this package, primarily in `schwab_watchlists`.

## Purpose

`mb_watchlist_coordinator` provides a source-neutral and adapter-neutral model for deciding:

* which symbols should currently belong to the MasterBot Watchlist;
* why those symbols are present or absent;
* how multiple independent producers affect the desired Watchlist;
* how downstream adapters compare their observed state with that desired state;
* which reconciliation operation is required;
* whether a downstream materialization was actually verified.

The coordinator treats the MasterBot canonical Watchlist as authoritative.

ThinkOrSwim, Schwab, or any future downstream platform is an adapter to that state rather than the owner of it.

## Architecture

The intended data flow is:

```text
Producer 1 ─┐
Producer 2 ─┼──> ProducerIntent
Producer 3 ─┘          |
                       v
              WatchlistCoordinator
                       |
                       v
               CanonicalWatchlist
                       |
          +------------+------------+
          |            |            |
          v            v            v
      ToS adapter   Schwab API   future adapter
```

Producers describe intent.

The coordinator resolves effective intents into an immutable canonical revision.

Each adapter independently observes its downstream state and reconciles toward the canonical target.

## Core concepts

### ProducerIntent

A `ProducerIntent` describes what one producer wants to contribute to the Watchlist.

Current intent types are:

| Intent type      | Meaning                                           |
| ---------------- | ------------------------------------------------- |
| `BASE_SET`       | Contribute symbols to the baseline Watchlist      |
| `ENSURE_PRESENT` | Ensure these symbols are present                  |
| `ENSURE_ABSENT`  | Ensure these symbols are absent                   |
| `FORCE_PRESENT`  | Force these symbols present after ordinary policy |
| `FORCE_ABSENT`   | Force these symbols absent after ordinary policy  |

Producer intents may also contain:

* `source_event_id`
* `effective_from`
* `expires_at`
* `supersession_key`
* `reason`
* arbitrary metadata

This allows producers to express not only membership but lifecycle and provenance.

### CanonicalWatchlist

A `CanonicalWatchlist` is an immutable desired-state revision containing:

* revision number;
* symbol set;
* creation time;
* contributing intent IDs;
* policy version.

The coordinator creates a new revision only when the effective desired state or its contributing intent set changes.

## Policy v1

The current policy is intentionally simple.

Conceptually:

```text
canonical =
    BASE_SET
    + ENSURE_PRESENT
    - ENSURE_ABSENT
    + FORCE_PRESENT
    - FORCE_ABSENT
```

All active intents of a given type currently contribute set membership.

More sophisticated source priority, Watchlist-size limits, ranking policy, and conflict policy are intentionally deferred until the proof-of-concept architecture has been validated.

## Intent lifecycle

Intent lifecycle supports:

* future effective times;
* expiration;
* explicit cancellation;
* supersession.

If intents share a `supersession_key`, the newest eligible intent wins for that group.

This is intended for producers that periodically publish replacement state, such as an Overnight Volume producer publishing a new daily baseline.

## Adapter state

The coordinator distinguishes several forms of downstream state.

### Target state

`AdapterTarget` is the canonical revision and symbol set that an adapter should eventually materialize.

### Observed state

`AdapterObservedState` records what an adapter was actually observed to contain.

Observed state may include an evidence reference, such as a CSV export.

### Confirmed state

`AdapterConfirmedState` records a canonical revision that has been successfully materialized and fully verified.

Observed and confirmed state are deliberately different concepts.

A downstream observation does not change canonical truth.

## Reconciliation

The generic reconciliation layer compares the adapter target with trusted observed state and returns one of:

* `OBSERVATION_REQUIRED`
* `CURRENT`
* `RECONCILIATION_REQUIRED`

The current ThinkOrSwim planner converts that assessment into one of four operations:

| Operation | Meaning                                                      |
| --------- | ------------------------------------------------------------ |
| `OBSERVE` | No trusted observation exists; observe first                 |
| `NO_OP`   | Observed state already equals the target                     |
| `ADD`     | Only symbols are missing; add those symbols                  |
| `REPLACE` | Unexpected symbols are present; replace with the full target |

This makes the choice between ADD and REPLACE a reconciliation decision rather than a producer decision.

## Materialization transactions

Adapter mutations are represented as `MaterializationTransaction` objects.

Transaction states are:

```text
CREATED
   |
   v
ACTIVE
   |
   +--> SUCCESS
   |
   +--> FAILED
   |
   +--> INTERRUPTED_OUTCOME_UNKNOWN
```

`INTERRUPTED_OUTCOME_UNKNOWN` is intentionally distinct from ordinary failure.

It represents cases where a mutation may have occurred but the system cannot safely prove the result.

That distinction prevents blindly repeating a downstream mutation when its outcome is uncertain.

## Full-target verification

A materialization is successful only when the complete observed target matches the transaction target.

Verification checks both:

```text
missing symbols
unexpected symbols
```

Any mismatch fails verification.

This is stricter than merely verifying that the requested ADD or REPLACE command was accepted.

## Adapter health

Adapters may separately report:

* `HEALTHY`
* `DEGRADED`
* `OFFLINE`

Health state is independent of canonical Watchlist state.

For example, an adapter may successfully observe its Watchlist while still reporting degraded health because a secondary cleanup or transport action failed.

## ThinkOrSwim runtime

The package includes ThinkOrSwim planning and runtime orchestration abstractions.

`run_tos_reconciliation_step()` performs one reconciliation step using a supplied executor:

```text
canonical target
      |
      v
plan operation
      |
      +--> OBSERVE --> record observation
      |
      +--> NO_OP
      |
      +--> ADD / REPLACE
               |
               v
          transaction
               |
               v
          executor
               |
               v
          verification
```

The actual Windows/ThinkOrSwim GUI execution is intentionally outside this package.

In the current MasterBot proof of concept, `schwab_watchlists` supplies the live ToS executor and transport machinery.

## Current proof-of-concept use

The current MasterBot Watchlist POC uses two producers:

```text
Overnight Volume
    |
    +--> BASE_SET
              |
              v
       CanonicalWatchlist
              ^
              |
    +--> ENSURE_PRESENT
    |
Nasdaq LUDP/M halts
```

The resulting canonical Watchlist is reconciled into ThinkOrSwim.

This demonstrates the primary architectural goal: independent producers can express intent without directly manipulating the downstream Watchlist.

## Example

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from mb_watchlist_coordinator.coordinator import WatchlistCoordinator
from mb_watchlist_coordinator.models import IntentType, ProducerIntent

ET = ZoneInfo("America/New_York")

coordinator = WatchlistCoordinator()

now = datetime.now(ET)

baseline = ProducerIntent(
    intent_id="ov-001",
    producer_id="overnight-volume",
    intent_type=IntentType.BASE_SET,
    symbols=frozenset(
        {
            "AAPL",
            "NVDA",
            "MSFT",
        }
    ),
    created_at=now,
    reason="Opening Overnight Volume selection",
)

coordinator.accept_intent(
    baseline,
    at=now,
)

halt = ProducerIntent(
    intent_id="ludp-001",
    producer_id="nasdaq-ludp",
    intent_type=IntentType.ENSURE_PRESENT,
    symbols=frozenset(
        {
            "TEMC",
        }
    ),
    created_at=now,
    reason="Nasdaq volatility halt",
)

canonical = coordinator.accept_intent(
    halt,
    at=now,
)

print(canonical.revision)
print(sorted(canonical.symbols))
```

The producer does not decide whether the downstream adapter should ADD or REPLACE.

That decision belongs to adapter reconciliation.

## Repository layout

```text
mb_watchlist_coordinator/
├── src/
│   └── mb_watchlist_coordinator/
│       ├── adapters/
│       │   ├── tos.py
│       │   └── tos_runtime.py
│       ├── adapter_state.py
│       ├── coordinator.py
│       ├── execution.py
│       ├── health.py
│       ├── lifecycle.py
│       ├── models.py
│       ├── orchestration.py
│       ├── policy.py
│       ├── reconciliation.py
│       ├── session.py
│       ├── state_store.py
│       ├── transactions.py
│       └── verification.py
├── tests/
├── README.md
└── pyproject.toml
```

## Installation

Python 3.12 or newer is required.

Editable development install:

```cmd
python -m pip install -e .
```

Install with development dependencies:

```cmd
python -m pip install -e ".[dev]"
```

## Tests

Run:

```cmd
pytest -q
```

The package is designed so that coordinator policy and reconciliation behavior can be tested without ThinkOrSwim, Schwab, network access, or GUI automation.

## Design principles

The current design follows several important rules:

1. **Canonical state is authoritative.**
   Downstream observations never rewrite the canonical Watchlist.

2. **Producer intent is separate from adapter mechanics.**
   Producers say what they want; adapters decide how to materialize it.

3. **Adapters reconcile independently.**
   Failure or delay in one adapter should not conceptually roll back canonical state or block another adapter.

4. **Observation is not confirmation.**
   Confirmed state requires successful full-target verification.

5. **Unknown outcomes remain unknown.**
   The coordinator does not pretend that an uncertain downstream mutation failed or succeeded.

6. **Revisions are immutable.**
   New desired state produces a new canonical revision rather than mutating historical state.

## Experimental nested sampling promotion

The accepted October 16 proof is preserved as source under
[`experiments/sampling_promotion_20261016`](experiments/sampling_promotion_20261016/README_PROOF.md).
It projects one active promotion request into a complete Uni/Focus/Hot hierarchy,
atomically publishes a fresh experimental journal, and verifies it with the real
journal audit and two replays. MasterBot passed all 18 focused tests and the
retained proof. See the [validation record](docs/validation/sampling_promotion_20261016.md).

This directory is the exact, self-contained accepted proof, including its pinned
Coordinator and market-data reference source. Its runner deliberately imports
those bundled references. It preserves a reproducible milestone; it does not
install or change this package's current flat Coordinator. Further lifecycle and
production integration belong to subsequent increments.

From a CMD window with the `sea-green` environment active:

```cmd
call "experiments\sampling_promotion_20261016\01_run_offline_proof.cmd"
```

The proof needs no password, API, browser or production journal. Each run creates
only a new `runs` directory below the experiment. Git attributes preserve the
accepted bytes so the proof's manifest checks also work with Windows Git settings.

## Source-owned sampling request lifecycle

The next increment adds `sampling_requests.py` and `sampling_request_store.py`
under `src/mb_watchlist_coordinator`. Requests are scoped by producer, carry
immutable provenance and actual receipt times, and are recorded in a SQLite log.
Cancellation checks the trusted caller identity against the request owner.
Exact retries keep their original receipt; conflicting identities are refused.
Restart and replay recover the same active reasons and nested membership.

With policy omitted, the reducer reports demotion eligibility and retains
promoted membership after the last request ends. The explicit policy increment
below adds restrictions and stabilized demotion. External caller authentication
and a live Coordinator scheduler remain pending. The existing flat Coordinator API remains intact.

See [the request proof](experiments/sampling_requests_20261016/README.md) and its
[validation record](experiments/sampling_requests_20261016/VALIDATION.md).
From one CMD window with `sea-green` active, run:

```cmd
call "01_run_sampling_requests.cmd"
```

This uses the repository's new request modules and the earlier pinned market-data
reference. It runs 30 focused tests and a fresh synthetic publication/replay proof,
with no API or production journal. MasterBot acceptance is complete: all 30
focused tests and the retained proof passed on October 16, with clean prompt return.

## Explicit restrictions and stabilized demotion

The optional `SamplingPolicy` now adds one trusted Super User authority,
session-bounded Focus/Uni caps and replay-derived ordinary demotion timers.
Promotion remains immediate; ordinary demotion waits for both configured grace
and minimum residence. Restrictions preserve underlying requests. Clear/expiry
reevaluates current demand, and replacement expiry never revives an older cap.
The earlier flat Coordinator API and unconfigured request-ledger behavior remain
intact.

All settings are mandatory. The offline proof selects 60-second grace,
120-second residence and immediate privileged caps explicitly as review values,
not production defaults. The retained proof uses a labeled synthetic policy clock;
it makes no live timing or acquisition claim.

See the [policy proof](experiments/sampling_policy_20261016/README.md) and
[validation](experiments/sampling_policy_20261016/VALIDATION.md). From one CMD
window with `sea-green` active:

```cmd
call "01_run_sampling_policy.cmd"
```

It runs 43 focused checks and a retained real-journal audit/replay proof with
21 receipts and 22 revisions, then returns to its prompt. Local repository tests:
195 tests plus 14 subtests PASS. Windows acceptance of this increment is pending.
Recorded/live Nasdaq ingestion, a production publication service/outbox and Hot
acquisition remain subsequent work.

## Current limitations / post-POC work

The following are intentionally not complete yet:

* persistent coordinator state across process restart;
* production restart recovery for in-flight transactions;
* maximum Watchlist-size policy;
* richer producer priority and conflict policy;
* user-facing audit/journal reporting;
* full trading-day orchestration;
* concurrent production adapter workers;
* direct Schwab downstream adapter;
* additional downstream platforms.

These are post-proof-of-concept hardening and extension tasks.

## Related projects

* `schwab_watchlists` — current MasterBot Watchlist producers, live ThinkOrSwim executor, OV selection, Nasdaq halt integration, and evidence transport/recovery.
* `mb_market_data` — reusable market-data acquisition and future historical Overnight Volume infrastructure.
* `ToS_scanner` — ThinkOrSwim GUI automation and Watchlist/scanner export mechanics on the El-Cheapo host.
* `mb_tools` — shared MasterBot utilities, secure Schwab configuration, and scanner-control CLI tools.

## Scope

`mb_watchlist_coordinator` coordinates Watchlist state.

It does not place trades or submit orders.
