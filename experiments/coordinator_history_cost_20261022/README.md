# Coordinator history-cost optimization

This experimental increment follows the Windows-accepted command 28 record at
3588cf8090279bd014417e9560d10e37c75a6dac. It changes read/replay implementation;
production main, schedules, Hot activation and the recovery delivery contract
are unchanged.

## What changes

* Parse each accepted request activation/expiry window once within each fresh
  replay, and use it for that replay's reservation and activity decisions.
* Reuse only freshly reconstructed journal values when a publication plan is
  identical in canonical JSON to its corresponding native receipt; uncommitted or different
  plans still use full native proposal validation.
* Cross-check reconstructed journal wire hashes without constructing the same
  native hierarchy a second time. The existing native store still validates
  every channel header, member count, fingerprint, provenance and hierarchy hash.
* Reuse request-state payloads/digests only within one publication read.
* Reduce JSON scalar traversal overhead while preserving finite numbers,
  string-only metadata keys, generic mappings and detached immutable values.

No verified database prefix, admission decision or replay state persists between
reads. Every read still checks request configuration/identity, the complete
request hash chain, every admission result, timers, publication outcomes and
the full journal binding. The wire contracts and persisted database format do
not change.

The experimental market-data dependency
`experiments/sampling_promotion_20261016/market_data/src/mb_market_data/sampling_membership.py`
changes in this increment; the identical source change is checkpointed in the
market-data repository. That dependency is qualified here with its native
metadata/hierarchy/store tests. Earlier source pins and ZIPs remain historical
accepted evidence; their acceptance does not automatically qualify this code.

## Verification and measurement

`verify.py` runs 264 affected unittest checks with network access denied,
including new corruption, replacement timing, native hash equivalence and
interrupted-publication cases. Ten unrelated pytest-based suites were outside
this run; initial overbroad discovery could not import pytest in the cloud
runtime. This is affected-path qualification, not a complete-project pytest run.

`compare.py` runs fresh source processes against the exact same saved,
native-generated 1,000-receipt/200-publication fixture. It verifies the complete
request-state and publication snapshot digests and original database bytes,
measures 100 candidate idle cycles and three fresh cold reopens, and retains
a FAILED timing gate separately from correctness. A three-cycle reference
sample is diagnostic; the earlier 100-cycle baseline report remains retained.
No new full-size construction, state-changing timing, memory soak, recovery
fault matrix, Windows capacity or provider qualification is claimed.

## Windows operator step

The new unique handoff contains only `30_verify_history_cost.cmd`, the short
offline affected-suite verification. It asks for no password and accesses no
API or production journal. Run it from the existing sea-green CMD environment,
then retain its report, complete console and actual prompt return. Native
Windows qualification of this increment remains pending until that evidence
is supplied. Do not repeat commands 26, 27 or 28 unchanged. Command 29 is not
requested for this increment. Complete operational recovery remains unfinished.

The final candidate also distinguishes boolean, integer and floating-point wire
values before reusing native validation; two dedicated regression checks reject
rehashed True/1 and 1.0/1 substitutions. The earlier candidate was rejected in
code review before delivery, and its diagnostic records are retained separately.
Local final affected verification: 264 PASS in 7.307 seconds. Timing evidence is
recorded separately and must not be inferred from this verification result.

## Final retained measurement — October 22

Local final affected checks: 264 PASS in 7.307s. Extracted final
handoff: 264 PASS in 8.683s, path with spaces, altered source rejected
before tests. Native Windows command 30 and actual prompt return remain pending.

| Same saved native fixture | Median | p95 | Maximum | Samples |
| --- | ---: | ---: | ---: | ---: |
| Reference diagnostic | 3.812s | 3.928s | 3.928s | 3 |
| Final candidate idle | 1.416s | 1.530s | 1.608s | 100 |

The earlier 100-cycle baseline p95 of 4.952s remains historical evidence,
separate from this three-cycle reference diagnostic. Final cold reopens:
1.879s, 2.022s, 1.842s, each PASS against 10s. Idle p95 still
FAILS 0.5s and maximum still FAILS 1s. Correctness PASS, performance FAILED,
overall qualification INCOMPLETE. Complete request states and publication
snapshots match the saved fixture; all database bytes remain unchanged.

No new full-size construction, current full native audit/replay, real-clock
state-changing performance, memory/busy-tail, provider or complete recovery
qualification is claimed. Earlier audit/replay results remain historical.
The initial type-equality candidate and its diagnostics are explicitly rejected
before delivery and retained under pre_type_guard records; the final two
representation regressions pass.

Final delivery: `coordinator_history_cost_20261022_205839_ce0f7b.zip`, 140,951 bytes, 53 files,
SHA-256 `18f971331dfe50f27e0a4b1a5c572be1d84236beed07061d2d536d170fd30541`.
Remaining work: full reconstruction cost, Windows affected checks and the
remaining performance/fault envelope, common live/recovery event-request
identity, normal recovery delivery, paced transport and process supervision.
