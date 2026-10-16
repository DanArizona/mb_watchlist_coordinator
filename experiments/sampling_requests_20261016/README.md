# Source-owned sampling requests

This increment adds durable source-owned requests, cancellations and clock receipts
to the Coordinator package. It leaves the older flat Coordinator API intact.

From one CMD window with `sea-green` active, call the repository root's
`01_run_sampling_requests.cmd`. It runs 30 focused tests and a separate synthetic
proof, then returns to the prompt. Python 3.12+ and America/New_York timezone data
are required. No package install, password, browser or network call is needed.
The runner accepts no external database argument. Each run writes its own request
ledger, membership journal, reports and temporary tests below this experiment's
`runs/<UTC timestamp>-<unique suffix>` directory. All owned SQLite handles close.

## Expected sequence

| Receipt | Desired Hot reasons | Published/retained Hot | Result |
| --- | --- | --- | --- |
| Baseline | none | empty | Uni AAPL/MSFT/SPY; Focus SPY |
| Manual requests MSFT | manual | MSFT | Also adds MSFT to Focus |
| Halt producer requests MSFT | manual + halts | MSFT | Both requests retained |
| Manual withdraws its request | halts | MSFT | Other source still needs Hot |
| Manual attempts to cancel the halt request | halts | MSFT | Rejected and durably recorded |
| Halt producer withdraws its request | none | MSFT | Eligible for demotion; retained pending policy |

The last row intentionally distinguishes current demand from retained membership.
This increment does not choose a demotion delay, hysteresis interval, privileged
restriction policy or authority to force removal. A subsequent policy increment
will decide when eligible members actually leave Hot/Focus. No automatic demotion
is hidden in cancellation processing.

## Code and durability

- `src/mb_watchlist_coordinator/sampling_projection.py`: existing promotion helper
  and immutable nested membership, promoted unchanged from the accepted proof.
- `sampling_requests.py`: immutable receipt/state models, pure admission checks,
  deterministic replay, active reasons, expiry and demotion eligibility.
- `sampling_request_store.py`: SQLite receipt log, serialized append transactions,
  stable source-scoped command identity, exact-retry deduplication and conflicts.
- `request_proof.py`: an explicitly experimental adapter using the real pinned
  schema-v2 journal store, audit and replay modules from the first proof.

Request IDs are scoped by producer. Two sources may use the same request ID.
Each accepted request preserves source event identity, reason, request timestamps,
immutable metadata and actual receipt time. Cancellation targets a producer and
request ID; the trusted caller identity must match that owner. Rejected cross-source
and unknown-request cancellations remain visible in the durable log. A retry with
the same identity and content keeps its original receipt; changed content conflicts.
A withdrawn request cannot be revived by retransmitting its old ID.

`actor_id` is supplied by a trusted local adapter separately from request metadata.
The API enforces that identity's ownership. It does not authenticate a network
caller or validate a self-asserted username. A future service must establish the
caller identity before invoking this API. The old flat cancellation API is not
an ownership boundary and is not used by this path.

Expiry is evaluated at recorded input/tick times, exclusive at the expiration
boundary and capped at the declared ET session end. Merely opening or reading a
ledger does not advance the replay clock. A running Coordinator will need to emit
clock checks; this proof does not start a background worker or scheduler.
Pending future requests activate on a recorded check at or after effective_from.

Every input has a sequence and a hash chained to the fixed session/baseline.
Replay rechecks admission outcomes, ordering and content. These checks detect
inconsistent history; they are not signatures or external security attestation.
Restart recovers the same state from the receipt log. Concurrent appenders are
serialized; admission and append occur in the same transaction.

## Publication proof and limits

The standalone proof plans membership revisions approximately ten minutes ahead
so the real store can assign publication times without backdating. Each logged
receipt, including rejected-input evidence, gets a complete hierarchy revision.
Five receipts produce six global revisions, eighteen channel headers and thirty-
four historical member rows. There are zero market acquisitions.

The proof demonstrates restart after durable input before publication, and retry
after a journal commit without a saved publisher acknowledgement. Its fixed future
schedule makes reconstructed proposals identical; the schema-v2 store owns the
atomic commit. Live scheduling, a runtime outbox/publication acknowledgement loop,
Super User restrictions, demotion stabilization, live Nasdaq ingestion and Hot
acquisition remain future work. A delayed retry cannot backdate a publication.

Outputs include `request_ledger.sqlite3`, `membership.sqlite3`, `proof_report.txt`,
`proof_report.json`, `test_results.txt` and `run_receipt.json`. Hashes differ between
separate runs because each run records real timestamps. Unit tests use explicitly
synthetic clocks to exercise expiry and activation boundaries without waiting.

The source manifest checks LF-normalized UTF-8 content to tolerate Windows Git
line-ending conversion. It is an accidental-change guard, not authentication.
The first accepted frozen proof and its exact-byte manifest remain unchanged.

See `VALIDATION.md` for local results. Windows acceptance of this increment is pending.
