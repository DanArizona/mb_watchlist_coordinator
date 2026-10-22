# Coordinator history reconstruction follow-up

This increment follows Windows-accepted command 30. Reference local commit
`a513f64f19b39daf65a7d2fb92edc081cb783110` has the same complete tree as public
acceptance commit `d78e5ca0daa9b18bbbfb7245f751fd30cee7d93b`.

## Behavior and implementation

The Coordinator still checks the complete retained request/publication/journal
history on every read. This increment reduces construction work during those
checks without retaining a verified prefix across reads:

- Canonical JSON adapts frozen/general mapping nodes when encountered rather
  than copying the entire tree through `plain()` first. Existing key ordering,
  finite-number rejection and distinct boolean/integer/float wire values remain.
- A fresh request replay may reuse a fully checked immutable membership when
  its exact built-in string groups recur. The table dies with that replay.
  Request provenance, receipt hashes, admission decisions and all policy timers
  are still independently evaluated at every event.
- The native store adds `validated_membership_revision_payloads()`, which returns
  detached plain receipts for internal verification. Its channel counts,
  provenance and fingerprints use the same row reader as ordinary native reads.
  Both paths use one shared hierarchy validator and canonical hash calculation.
  The plain path decodes raw storage JSON directly, rejects nonmapping metadata
  and nonfinite numbers, and validates nesting, contract and publication time;
  it avoids constructing deep immutable metadata which this internal caller
  immediately converts back to plain JSON.
- Ordinary `SamplingHierarchyRevision` values remain deeply immutable and use
  the same shared validator. The Coordinator independently cross-checks native
  receipt wire hashes, with a validated immutable-value fallback for older stores.

Runtime changes: Coordinator `sampling_requests.py` and `sampling_journal.py`,
and the experimental native dependency `sampling_membership.py` and
`quote_observation_store.py`. Those native files are mirrored byte-for-byte in
the market-data checkpoint. Persisted schemas and wire contracts are unchanged.
No production/main installation, schedule adoption or Hot activation is made.

## Qualification

The offline verifier runs 281 affected unittest checks: the previous suites,
nine new Coordinator checks and eight native-reader checks. Coverage includes
exact wire/hash equivalence, numeric representation distinctions, general
mapping/container subclasses, invalid/mutable inputs, recurring membership with
new request provenance, fresh-read detachment, header/hash damage, rehashed
invalid nesting/metadata, unsupported contracts, publication times and both
new native-receipt and legacy immutable-value wire cross-checks.

The original stale-native-value test explicitly exercises the older-store
fallback; an additional test exercises the optimized native receipt guard.
One initial corruption drill was rejected by SQLite's CHECK constraint before
reading; its failed report is retained. The corrected fixture explicitly
bypasses that constraint only within the isolated corruption test, allowing
both readers' contract validation to be tested. Runtime code was not weakened.

Network is denied and production journals are not opened. These are affected
unittest checks, not a complete-project pytest run. The initial JSON-only
candidate and its 272-check result and 100-cycle report remain under
`validation/first_candidate_*`; its median gain was only about 4%.

The final comparison uses the same saved native 1,000-receipt/200-publication
fixture. Its reference is the retained 100-cycle run measured earlier in this
increment with the unchanged command-30 source. The reference report hash and
source inventory are checked before reuse, and its time is reported separately.
The final candidate receives 100 measured idle cycles and three fresh cold
reopens. Full request-state/publication-snapshot digests and all original
SQLite file hashes must match. Measurements are cloud Linux/tmpfs, not
MasterBot capacity or elapsed full-day operation.

No new full-size construction, real-clock state-changing/burst latency, memory
soak, busy-tail, provider capacity, complete recovery fault matrix or production
adoption is qualified. Shared live/recovery event identity, normal recovered
Hot request delivery, paced transport and process supervision remain pending.

## Windows affected-path verification accepted

The complete operator-supplied MasterBot Windows sea-green CMD console confirms
`31_verify_history_reconstruction.cmd`: 281 tests PASS in
10.932056899997406 seconds, network denied, production access false, and actual
CMD prompt return. The reported saved file is
`runs/verification/20261022T233910Z-e01e2436.json` relative to the handoff;
that report file was not separately uploaded. See
`validation/windows_qualification.json` for acceptance and the source pin.
No unchanged command 31 rerun is required. Earlier accepted commands and the
original ZIP/delivered README remain historical evidence. This accepts affected
correctness, not Windows timing, complete recovery, provider capacity or
production adoption.

## Results

Final numeric measurement and extracted-handoff results are appended after
qualification; complete records live under `validation/`.

Local final affected checks: 281 PASS in 5.772s.

| Same saved native fixture | Median | p95 | Maximum | Samples |
| --- | ---: | ---: | ---: | ---: |
| Accepted command-30 reference | 1.289s | 1.391s | 1.462s | 100 |
| Final candidate | 0.996s | 1.118s | 1.265s | 100 |

Candidate cold reopens: 1.424s, 1.418s, 1.432s. All PASS against 10s.
Idle gate: FAILED (p95 <= 0.5s, maximum <= 1s). Overall qualification remains INCOMPLETE.

Extracted final handoff: 281 PASS in 5.844s, with a path containing spaces; altered source refused before tests.
Delivery: `coordinator_history_reconstruction_20261022_230120_adda03.zip`, 149065 bytes, 55 files, SHA-256 `1bbdf21f1a4526972bbba1f579eaa114c763a078b5d765c93362f1ac817be720`.
Native Windows command 31 is ACCEPTED: 281 PASS in 10.932s with actual CMD prompt return; no production installation is made.
