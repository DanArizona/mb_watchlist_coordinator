# October 16 source-owned request lifecycle - local validation

- Local runtime: Python 3.12.14, Linux.
- Repository suite: 160 tests and 5 subtests PASS (138 existing tests + 22 new request-store/reducer tests).
- Focused non-interactive runner: all 30 tests PASS (22 request tests + 8 journal integration tests).
- Separate retained proof: PASS; request restart/replay identical, exact retries deduplicated, foreign cancellation rejected, last withdrawal eligible for demotion with retained membership.
- Actual schema-v2 audit PASS; two journal replays identical. Five request receipts, six global hierarchy revisions, eighteen channel headers, thirty-four historical member rows, zero acquisitions.
- Restart after durable request before publication reconciles the pending input. Retry after journal commit without saved acknowledgement preserves the original revision and publication receipt within the fixed future fixture schedule.
- Injected journal insert failure rolls back the complete hierarchy revision while retaining the input; subsequent retry succeeds.
- Expiry/future activation/session-end boundaries use explicit synthetic unit-test clocks; the standalone proof records real timestamps.
- Every owned SQLite connection closes explicitly, including failure-injection setup and test cleanup. No cleanup error is ignored.
- The first accepted frozen proof remains byte-identical. New proof source hashes use LF-normalized content for Windows Git compatibility.

Local request replay SHA-256: `60b26038bc86b1a546ea69b360df7a7f0d34c2aeb5fe0997387d7e14b032cf4b`.
Local journal replay SHA-256: `bf0546791f87d726262434a3b1ac4d8afbfe6aa1e22986f7840342792e7898a8`.
Full example reports are in `validation/`; their absolute paths identify the local host. Your run records its own timestamps and hashes.

Actual Windows acceptance of this increment is pending. Trusted actor ownership checks are implemented; external authentication, privileged restrictions, demotion stabilization, live publication scheduling/outbox acknowledgements, Nasdaq ingestion and Hot acquisition remain pending. Production processes and journals are independent.
