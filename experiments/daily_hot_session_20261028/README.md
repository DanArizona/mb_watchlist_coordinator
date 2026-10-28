# Daily Hot publication backend — October 28

This increment attaches the Coordinator's source, identity and publication
ledgers to the existing daily Uni/Focus journal. The original short recovery
experiment and its guards remain unchanged. The daily Hot collector, owned
authenticated controller, feed worker, desktop alerts and live launch are
still to be connected. This packet provides offline Windows verification and
a read-only preview; it cannot start production Hot operation.

## Implemented

- Exact published r0/r1 hashes, source-file bytes, ET session, canonical paths
  and interleaved cadence are bound before application state is created.
- A journal-level lease and immutable state-location claim prevent parallel
  owners and new-folder budget resets. Partial initialization is retained;
  reopening requires every original ledger and the complete binding.
- Existing current/historical Nasdaq receipts, source-owned outbox, three
  cumulative identity permits, one selected symbol and ordinary admission
  feed native future membership publication in the existing journal.
- The daily identity adapter has a distinct regular-session contract. Its
  reservation/replay implementation is reused; the experiment still rejects
  a daily window. Daily candidate values remain proposed, not adopted.
- Publication commit/ACK recovery, unknown identity reservations, provider
  stops, changed inputs, foreign publishers and clock rollback are checked.
- Status distinguishes latest published and currently effective revisions,
  reports pending publication/source commands and retained source warnings,
  and explicitly says that collection is not running.
- Closing releases only this session's lease. It does not withdraw source
  demand, start or stop a process, or control Uni, Focus or independent Health.

## Windows verification

Extract the new ZIP beneath the market-data repository's `output` directory.
In a sea-green CMD window run its `60_verify_daily_hot_session.cmd`. It asks
for no password and uses only synthetic temporary/dedicated proof files.
Supply the final JSON and actual returned CMD prompt. There must be no
failures, errors or skips. A passing offline suite does not authorize live
operation or establish real provider/full-day capacity.

The verifier checks the source inventory before imports and after tests.
It retains a synthetic native journal and all Coordinator ledgers in the
printed run's `native-proof` folder. That proof includes four simulated
Uni/Focus acquisitions across native membership publication, a native audit
and two matching fresh replays. Other tests exercise real owned process exits
after identity reservation/native commit. Their timing is not market/provider
performance evidence. Network is denied and no vault/installed SDK is used.

## Read-only preview

From the extracted packet, run `python -I -B run.py preview OPENING_R0 FOCUS_R1
--journal JOURNAL --state-root ABSOLUTE_NEW_DAILY_HOT_DIRECTORY`, quoting all
paths. The state directory's name must start with `daily_hot_` and it must be
separate from the journal directory. Preview validates already published
proposals without authentication, API calls or application-state creation.
SQLite can create its normal WAL/SHM coordination files while reading.
The preview accepts a completed session for review; it never activates it.

## Trusted development API and remaining work

`DailySession.attach` is an internal API. Its caller must already have explicit
publication authorization, verified dependencies, a same-ET-date validated
directory catalog, successful credential checks and bounded process ownership.
Its boolean authorization parameter is a trusted caller assertion, not an
authentication or deployment mechanism. There is no attach/live CLI.

`cycle` consumes captures supplied by a trusted transport. It does not itself
prove HTTP origin, pacing, completeness, process supervision or timeouts; those
remain the feed/controller boundary. The supplied client must be bounded and
the synchronous call must run inside the independently bounded owned controller.
Do not invoke this development API against production from an ad hoc script.

Next connect the daily feed and native Hot collector to this backend, retaining
the original credential/progress deadlines, worker-start budget, replacement
hold, response-recovery rules and independent cleanup/reporting. Then qualify
the affected Windows/live paths and present a concrete daily release/settings
for approval. Current production remains Hot-disabled on the accepted
interleaved Uni/Focus cadence. Manual controls and read-only Overlay follow
closely; no unchanged accepted live-profile repeat is required.
