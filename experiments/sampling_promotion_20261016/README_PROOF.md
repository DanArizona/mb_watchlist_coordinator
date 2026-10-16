# Coordinator promotion proof

This is an isolated first implementation of the Coordinator's request-to-sampling-hierarchy bridge.
It accepts one active promotion request, produces a complete Uni/Focus/Hot revision, and publishes it
through the existing schema-v2 journal store. The actual audit and replay code check the result.

See `WINDOWS_FIX.md` for the explicit test-connection closure correction following the first Windows run.

## Run on MasterBot

Extract the ZIP once into a new folder. In one CMD window with `sea-green` active, call the extracted
`01_run_offline_proof.cmd`. The command requires no password or browser, finishes in seconds, and
returns to the prompt. It runs 18 focused tests and a separate retained proof.

Everything needed for the proof is bundled as pinned source. It does not install packages, change
repositories, access Schwab or Nasdaq, or open a production journal. Python 3.12 or newer and the
existing environment's America/New_York timezone data are required. The CMD file selects the active
environment's Python and uses isolated imports; no editable installation is needed.

Expected result:

| Revision | Uni | Focus | Hot |
| --- | --- | --- | --- |
| r0 | AAPL, MSFT, SPY | SPY | empty |
| r1 | AAPL, MSFT, SPY | MSFT, SPY | MSFT |

The request is synthetic: `synthetic_halt_producer` requests MSFT in Hot. This proves the same
request format can carry a future halt producer's evidence; it is not a captured Nasdaq halt.
The symbol is also added to Focus because Hot must be a subset of Focus, and Focus a subset of Uni.

The final text should say `Coordinator promotion proof: PASS`, with audit PASS, identical replays,
and an idempotent retry. There are two global revisions, six channel revisions, ten historical member
rows, and zero acquisitions. Ten member rows count both complete snapshots; there are three unique
symbols. Each run creates a new `runs/<UTC timestamp>-<unique suffix>` directory containing:

- `synthetic_membership.sqlite3`: the experimental journal, retained for review.
- `proof_report.txt` and `proof_report.json`: memberships, actual publication times, request evidence,
  source and reason, content hashes, audit counts, and replay sequence.
- `test_results.txt` and `run_receipt.json`: focused test results and source provenance.

The membership effective times are deliberately scheduled roughly ten minutes into the future.
The store records real publication times and rejects backdated publication. Immediate full replay
can reconstruct the scheduled revisions without waiting. This checks publication and reconstruction;
it does not measure live promotion latency or what a poller would have acquired.

## What is implemented

`coordinator/src/mb_watchlist_coordinator/sampling_projection.py` is a pure promotion projection.
It reuses the existing `ProducerIntent` and active-intent selection. Only `ENSURE_PRESENT` requests
targeting `focus` or `hot`, inside a fixed Uni, are accepted. An existing Hot member is preserved by a
Focus request. A request must already be active at decision time and still valid at scheduled effect.

`bridge/sampling_journal_bridge.py` translates that decision to `SamplingHierarchyRevision`, keeping
the request ID, producer, external event ID, reason, request timestamps, decision timestamp, session,
and baseline hash. The journal assigns the actual commit timestamp and atomically writes all three
channels. Request metadata is copied into the revision's immutable JSON evidence.

The focused tests include an injected failure during a channel insert. The complete r1 transaction
must roll back, leaving only r0. Conflicting duplicate revisions are refused; identical retries add no rows.

## Scope and next increment

This is a function-level proof, not a deployed Coordinator service or durable request inbox. Source
IDs provide attribution; authentication and cancellation ownership enforcement are not implemented
here. The existing flat Coordinator remains intact. Its older cancellation API must not be treated as
an ownership boundary.

The proof does not implement multi-source arbitration, withdrawal, expiry-driven demotion, Super
User restrictions, hysteresis, the active-request display, live Nasdaq ingestion, or a Hot poller.
Demotions, force operations, Uni changes, and supersession requests are explicitly rejected by this
bridge. These functions must not be wired into production until the request lifecycle and serialized
publication path are extended and tested. The accepted direction remains fast promotions and slower,
stabilized ordinary demotions; exact time settings remain to be chosen.

Next: make source-owned active requests and cancellations reduce to one complete hierarchy, then
add restrictions and demotion stabilization. After that, feed recorded halt events through the same
path before enabling live halt-triggered promotion and Hot acquisition in an isolated trial.

## Source pins and validation

Coordinator source is pinned to `DanArizona/mb_watchlist_coordinator` commit
`3e31fefd67bdac38ac805ed70dd49ad249e0f0dd`. The production journal, membership, polling type,
SQLite retry, audit, replay, and state projector modules are pinned to
`DanArizona/mb_market_data` commit prefix `a082f5441126`. Bundled market-data modules are unmodified
reference source. All original files were verified against their Git blob IDs before materialization.

`bundle_manifest.json` lists exact payload SHA-256 hashes, original source pins, and new files.
The launcher refuses missing or changed payload files. This is an accidental-change guard, not a
signature or producer authentication system. See `VALIDATION.md` for local results. Windows acceptance
is pending execution on MasterBot.
