# October 16 source-owned request lifecycle - local and MasterBot validation

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

Windows acceptance of this increment is COMPLETE, as recorded below. Trusted actor ownership checks are implemented; external authentication, privileged restrictions, demotion stabilization, live publication scheduling/outbox acknowledgements, Nasdaq ingestion and Hot acquisition remain pending. Production processes and journals are independent.

## MasterBot Windows acceptance

The user supplied CMD output from the accepted review ZIP
`coordinator_requests_20261016_152658_33cfc3.zip`:

```text
Ran 30 tests in 0.864s
OK
Source-owned request proof: PASS
Manual withdrawal: MSFT stays Hot for halt request
Foreign withdrawal: rejected and retained in request history
Last withdrawal: MSFT eligible for demotion; membership retained pending policy
Request restart/replay: identical; publication retry: idempotent
Journal audit: PASS; two journal replays: identical
Receipts: 5; hierarchy revisions: 6; market acquisitions: 0
```

The command returned cleanly to its prompt. On-host reports:
`C:/Users/danla/Documents/github/mb_market_data/output/coordinator_requests_20261016_152658_33cfc3/experiments/sampling_requests_20261016/runs/20261016T160058Z-dc473211`.

- Request replay SHA-256: `858f2652a3dbba242689a1870301eb07054a248b065d5326d28ef5fa9b4c7ec0`.
- Journal replay SHA-256: `76cc4294fe11f6c730afff3b2ea4c475befad41f9a73467a3a65540dd13e8130`.

The evidence is user-supplied console output, retained in structured form in
`validation/masterbot_acceptance_20261016.json`. Full SQLite journals and detailed
reports remain on MasterBot. New test runs are unnecessary for this documentation-
only acceptance update. Restrictions and actual demotion stabilization remain the
next increment; this acceptance does not claim a live publication service, Nasdaq
integration or Hot acquisition.

## Subsequent optional-policy compatibility check

After adding the explicit restrictions/demotion policy, this runner's source
manifest was refreshed for the current optional-policy modules. All 30 tests and
the retained no-policy proof pass locally. Historical Windows evidence above
continues to refer to the original implementation and uniquely named accepted
ZIP. New policy behavior has a separate 43-test review; Windows acceptance of
that increment is pending.
