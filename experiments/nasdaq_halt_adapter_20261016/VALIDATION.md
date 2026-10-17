# October 16 evening recorded Nasdaq adapter validation

- Local Python 3.12.14 Linux: complete repository suite 232 tests and 14 subtests PASS.
- Focused noninteractive runner: 46 tests PASS in 1.615s; separate retained proof PASS.
- Uploaded evidence SHA-256: b573c55ea391c95e9193a4e8d4eb416fc7a2e532d271cce5fca7983c451b5f88.
  All 24 files match byte-level hashes. Twelve raw responses parse to 690 rows.
- Original CURRENT replay: four after-hours snapshots, first baseline suppressed,
  repeats retained and three new after-hours records observed, zero requests.
- Eight historical snapshots parse; historical input is audit-only. Older JSON
  normalization differences are retained in the compact validation record.
- Derived arrival simulation: two recorded AEHL examples receive explicitly
  hypothetical timestamps with original records/capture provenance retained.
  Five producer receipts, seven request receipts, eight hierarchy revisions,
  zero market acquisitions. Audit PASS, two replays identical, publication retry
  idempotent. A hypothetical next calendar date is not a scheduled trading session.
- Interruption after request commit/before producer acknowledgement recovers without
  moving or duplicating the request. Withdrawn requests stay withdrawn on retry.
  Pending expiry is terminally rejected. Repeated event updates cannot create a
  second request, but a later distinct halt for one symbol does.
- Manual/Nasdaq ownership and privileged-cap interaction pass. Injected channel
  write failure rolls back a complete journal revision while retaining source
  requests; restart and retry preserve input state.
- Every owned SQLite handle closes explicitly, including fault-injection tests.
  The first frozen proof and previously accepted source modules remain unchanged.

Compact local evidence is retained in validation/. Full original payloads and
local databases are not committed to Git. The private review ZIP contains the
original capture pairs; each Windows run creates its own full reports.

Local request replay SHA-256:
43223147d54b19bc7afd2640bfd4bb26a8ce0f64e28f59ae4842c5814bef9ec8

Local journal replay SHA-256:
15209f5c0fed679afcc9afbd7c72654e3e39cf1c8ca5d09016b0afa0b83f92f5

## Windows acceptance — PENDING

Run the uniquely named review package's 01_run_nasdaq_halt_adapter.cmd once.
Expect 46 tests OK, Recorded Nasdaq adapter proof: PASS, and prompt return.
No rerun of the older accepted proof bundles is required for this review.

The configured LUDP/M selection, regular_close request lifetime and 60s/120s
Coordinator settings are proof values, not adopted production defaults. The
simulated arrival sequence does not prove live halt detection, real latency,
service scheduling/publication acknowledgement, authentication or Hot acquisition.
