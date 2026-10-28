# Daily source and native collection APIs — October 28

This increment connects the Windows-accepted daily publication backend to a
daily-paced Nasdaq feed and native Hot collection. It provides offline
verification only. There is no live launch, authentication prompt, source
installer, production activation or adopted operating policy in this packet.

## Implemented

- A distinct daily feed limits type permits an explicit ceiling of 390
  attempts, at least 60 seconds after completion and a hard per-attempt bound.
  Work cannot start before 09:30 ET or at/after 16:00 ET. Bodies crossing close
  remain unknown outcomes. The original ten-attempt/720-second limits and
  default worker are unchanged.
- The daily HTTP child has its own elapsed deadline and close fence. A parent
  crash cannot leave an unbounded HTTP thread. Every unknown attempt stays
  charged. Synthetic clocks are accepted only on explicitly synthetic jobs.
- A daily source pump carries saved feed receipts through the existing
  current-baseline/dated-recovery/later-current sequence, broker identity
  admission, shared outbox and native membership publication. Per-journal
  invocation claims and a lifetime source lease prevent competing pumps or
  recreation of a missing feed ledger to reset attempts.
- The native daily Hot poller uses the accepted dispatch/response/commit/ACK
  ledger against the existing daily journal, with a distinct daily binding.
  The isolated constructor still rejects production-format journals. Its
  explicit-slot positional API is adapted to the new base cadence field.
- Every quote checks the exact publication lineage, selected symbol, claim,
  slot, call budget and close. Empty membership is a saved skip. Saved complete
  responses recover before another provider call; unknown dispatches remain
  charged gaps, without fabricated observations or historical catch-up.
- A separate collector lifetime lease excludes duplicate collectors. HTTP
  401/403/429 stops are latched in both a receipt and the collector manifest;
  creating another collector does not silently resume provider work.
- Feed unavailability preserves verified demand. Component close operations
  own only their feed child/lease or collector client/lease, never Uni, Focus
  or independent Health.

The APIs require trusted bounded ownership and prepared clients. They are
development components, not an authenticated controller. In particular, a
source integrity BLOCKED result must stop dependent Hot operation; an ordinary
unavailable feed interval preserves verified demand. The independently owned
controller, read-only worker validation, credential/progress deadlines,
replacement hold, manual controller resume, status/alerts, final reporting and
deployment remain the next integration slice. Full-day performance and provider
capacity are not inferred from the 9,360-call review ceiling.

## Windows verification

Extract the new ZIP into the production repository's `output` directory and
run `61_verify_daily_hot_collection.cmd` in sea-green. Supply its final JSON and
actual returned CMD prompt. No password or API is used; all state is synthetic
temporary state or the printed retained proof. Existing production source,
journals, pollers and credentials are unchanged. Zero skips/errors/failures are
required. This does not repeat the accepted 138-check packet or live profiles.

The retained proof uses three synthetic RSS child attempts, one broker-identity
fixture call, native publication and four Hot acquisitions in an explicit
ten-second tail window. Two Uni and two Focus acquisitions share that journal.
It retains the native audit and two equal fresh replays. Pacing and market
timestamps are logical; HTTP-child and native-collector process-exit drills are
actual owned subprocesses. This proves component wiring/recovery, not live feed,
provider capacity, full-session Hot operation or authenticated supervision.

The original failed development assertions and fixture clock/pacing findings
are preserved alongside corrected results. The earlier Windows publication
backend acceptance remains separate and needs no unchanged rerun. Public
publication is not performed by this packet.
