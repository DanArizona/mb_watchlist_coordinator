# October 16, 2026: accepted Coordinator promotion proof

## Accepted scope

A synthetic, source-attributed MSFT-to-Hot request preserves Uni AAPL/MSFT/SPY,
adds MSFT to Focus and Hot, and publishes the complete r1 hierarchy atomically.
Request/event IDs, producer, reason, actual request/decision/publication times,
session, baseline hash and immutable metadata are retained.

This is a function-level isolated promotion/publication/audit/replay milestone.
The runtime's current flat Coordinator remains unchanged. Durable request admission,
authenticated cancellation ownership, multi-source arbitration, restrictions,
hysteresis, expiry-driven demotion, live Nasdaq ingestion and Hot acquisition
remain future work. Producer identity provides attribution, not authentication.

## Source and packaging provenance

- Coordinator reference commit: `3e31fefd67bdac38ac805ed70dd49ad249e0f0dd`.
- Market-data reference commit prefix: `a082f5441126`.
- Accepted review bundle: `coordinator_promotion_20261016_141902_winclose_e4fa82.zip`.
- ZIP SHA-256: `c0100ae689cd4e3583796ecb563bca09c91842ae9bf847a1b36173c6e21cc2ab`.
- All 59 payload files are preserved unchanged under the experiment directory.
  Its original `bundle_id` and hash manifest are retained intentionally; the
  parent repository path is not part of that content identity.
- The 44 pinned original reference files were checked against Git blob IDs.
  Pinned dependency copies are deliberate frozen fixtures, not vendored production
  changes. Preserve their source pins when preparing future proof revisions.

## MasterBot acceptance

On October 16, the user executed the corrected bundle in Windows CMD with
`sea-green` active:

```text
Ran 18 tests in 0.146s
OK
Coordinator promotion proof: PASS
Synthetic request: MSFT -> Hot
r0: Uni=AAPL MSFT SPY; Focus=SPY; Hot=empty
r1: Uni=AAPL MSFT SPY; Focus=MSFT SPY; Hot=MSFT
Audit: PASS; two replays identical; retry idempotent
```

The command returned cleanly to its prompt. Actual report directory:
`C:/Users/danla/Documents/github/mb_market_data/output/coordinator_promotion_20261016_141902_winclose_e4fa82/runs/20261016T142643Z-e63fff32`.

On-host replay sequence SHA-256:
`a58771549278d6dbb6412ee6dcbf7a7b9c054d8e56fcde91bee598af3e74e482`.
Each run records real timestamps, so hashes differ between separate runs.
There are two global revisions, six channel revisions and ten historical member
rows, with zero acquisitions or observations. Effective times are scheduled
roughly ten minutes ahead; this verifies publication/reconstruction, not live
promotion latency or acquisition.

## Cleanup correction and test coverage

The first bundle failed on Windows during temporary-directory cleanup because
the rollback test's SQLite context manager did not close its connection.
The accepted correction uses `contextlib.closing` and explicitly verifies the
closed handle. The old connection pattern fails this new regression assertion
also on Linux. No cleanup error is suppressed or force-deleted.

Tests cover atomic rollback on an injected channel insert failure, complete
snapshot reconstruction, idempotent retry, conflicting retry rejection, immutable
request provenance, nested membership, fixed-Uni eligibility, active/expiry/time
boundaries, and rejection of unsupported demotion/force/supersession requests.
All 138 existing Coordinator tests also passed locally on Python 3.12.14 before
this test-only cleanup correction. The accepted 18-test proof and reference code
are preserved unchanged here.
