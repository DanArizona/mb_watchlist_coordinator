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
