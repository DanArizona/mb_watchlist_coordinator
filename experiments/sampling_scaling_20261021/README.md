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

Use the complete uniquely named `coordinator_scaling_...zip`, extract beneath
mb_market_data/output, then run its `26_verify_coordinator_scaling.cmd` from an
idle sea-green CMD. No password, network, production journal or provider call.
The source inventory is verified before qualification. Preserve the final report
path and actual CMD prompt return. The command does not install or launch any
production or experimental live poller.

## Remaining scope

History still grows and full replay still runs. This removes measured repeated
work; it does not establish constant-cost replay, full-day real-provider capacity
or automatic startup/outage halt reconciliation. Native Windows qualification
is pending for this new increment. Existing accepted runtime packages and source
pins remain unchanged. Production Hot stays disabled.
