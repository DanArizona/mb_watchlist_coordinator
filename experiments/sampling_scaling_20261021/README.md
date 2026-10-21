# Isolated Coordinator scaling qualification — October 21

This first optimization removes duplicate request replay within a single read
and memoizes the canonical-symbol predicate for at most 4,096 exact built-in
strings, each at most 64 characters. Longer strings and subclasses retain the
ordinary uncached checks. Membership nesting is checked on every construction.
There is no cache of event validity, database state or publication authority.

`SamplingRequestStore.validated_history()` reads and fully validates the current
event prefix once and returns its events and states together. Request writes
reuse this verified pre-write state, then still validate the proposed complete
post-write history before commit. Every later read rechecks configuration,
identity, event hashes and admission outcomes. The publication service consumes
that one verified read. Disk schemas and receipt/projection payloads are unchanged.

## Qualification

The focused suite covers the changed validation/read paths and affected request,
restriction, admission, publication and Nasdaq request integration: 165 checks.
It includes warm-read corruption, rehashed false admission, new receipts,
configuration mutation, cold replay, cache eviction, string subclasses and
unchanged Hot <= Focus <= Uni rejection.

The separate benchmark uses identical synthetic 531-member histories at 11,
101 and 301 events, including independent sources, rejected ownership,
outside-Uni admission, a cap, expiry, withdrawals and demotion. Additional
ticks are logical history, not elapsed market operation. Five measurements per
size compare pure replay, native state reads and native idle publication cycles
with the unchanged 0417b345 baseline in fresh Python processes. All request-state
digests, final memberships and decisions must match. Both variants must reopen
their publication evidence identically. Network access is denied.

Initial local means (milliseconds; not Windows or provider-capacity evidence):

| Events | Old idle cycle | New idle cycle | Old state read | New state read |
| ---: | ---: | ---: | ---: | ---: |
| 11 | 64.297 | 26.043 | 40.144 | 7.900 |
| 101 | 353.371 | 64.431 | 301.586 | 43.641 |
| 301 | 996.012 | 147.329 | 972.076 | 125.379 |

Timing values are observations, not pass thresholds. Correctness, validation
and replay equivalence determine qualification. Source-tree report:
`validation/local_qualification.json`.

## Windows handoff

The original package `coordinator_scaling_20261021_211638_62f0a8` stopped after
165 tests with two Windows temporary-database cleanup errors (WinError 32).
Two new corruption tests committed edits but left their SQLite handles open.
This revision explicitly closes those handles and the two benchmark setup
connections. Each verified-history test also retains and checks every opened
handle, so garbage collection cannot hide an omitted close on Unix. Corruption
rejection assertions and all Coordinator implementation files are unchanged.
The original Windows attempt remains failed; its benchmark did not run.

Use the complete uniquely named `coordinator_scaling_...zip`, extract beneath
mb_market_data/output, then run its `26_verify_coordinator_scaling.cmd` from an
idle sea-green CMD. No password, network, production journal or provider call.
The source inventory is verified before qualification. Preserve the final report
path and actual CMD prompt return. The command does not install or launch any
production or experimental live poller.

## Windows acceptance — October 21

The corrected package `coordinator_scaling_20261021_231000_b272a9.zip` is
MasterBot-accepted for this first offline scaling increment. All 165 checks
passed in 5.124s, followed by the complete paired benchmark and actual return
to the sea-green CMD prompt. The original failed attempt remains preserved.

| Events | Old idle cycle (ms) | New idle cycle (ms) | Old state read (ms) | New state read (ms) |
| ---: | ---: | ---: | ---: | ---: |
| 11 | 39.047 | 17.776 | 26.337 | 4.706 |
| 101 | 217.320 | 40.415 | 202.933 | 26.947 |
| 301 | 659.289 | 98.897 | 598.925 | 78.264 |

All three complete request-state digests, idle decisions, final 532/40/0
memberships and native cold publication reopens match between old and optimized
sources. The evidence is the operator-pasted console report, recorded in
`validation/windows_qualification.json`; the on-host report path and actual
prompt return are retained there. No unchanged qualification or live trial is
required to accept this increment. The delivered ZIP remains unchanged.

## Remaining scope

History still grows and full replay still runs. This removes measured repeated
work; it does not establish constant-cost replay, full-day real-provider capacity
or automatic startup/outage halt reconciliation. Native offline Windows
qualification is accepted for this increment. Further history-cost work and
real-provider/production qualification remain pending. Existing accepted runtime
packages and source pins remain unchanged. Production Hot stays disabled.
