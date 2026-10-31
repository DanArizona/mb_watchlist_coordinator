# Multi-symbol development handoff

## Current status — final multi-symbol candidate

The latest paced owned development run07 PASSes:41 simultaneous candidates,
40identity calls (minimum interval2.074794s), four real paced synthetic feed children
(completion-to-start intervals61.04/61.32/61.39s),40Hot members,55Hot acquisitions,
23empty-membership skips,7concurrent Uni and13Focus acquisitions, zero missing
slots, original full native coverage audit PASS and Hot stored-value integrity
PASS. One worker, original3/8/15/10/60s gates, cleanup0.1448s, scope observed empty.
AllHot rows were quotes;16acquisitions used the complete40symbol roster. Twelve
native membership revisions include r0/r1 plus ten coalesced additions. Two fresh
native event-order digests agree (not two full observation-object projections).
The synthetic SDK/network-denied proof is not live-provider or full-session evidence.

The multi profile now explicitly binds ten-second membership publication batches
for additions. Pending native ACK completion and membership reductions bypass
that interval; a dedicated immediate-restriction case passes. Read-only final
verification can inspect an unfinished original native period after the live
fence stops, without credentials, dispatch, recovery writes or run registration.
Original raw FAILED packet/coverage verdicts remain in validation, including runs
03/04/05 whose data integrity passed but whose Hot coverage failed. Run06 was
stopped deliberately after a focused batching assertion showed the wrong persisted
time anchor; the corrected publisher uses original publication ACK outcome time.
No run has been promoted to Windows or production acceptance.

Final local regression batch:107tests PASS in129.847s. Fifteen focused batching,
restriction, EST partition and period/final-report cases also PASS in5.181s; these
include two new cases added after the larger batch. The new packet discovers the
entire current set, not a hardcoded earlier count. New GUI/provider/unchanged
15second supervisor drills are not repeated. The full-size final-policy history
probe is running; collect its result before freezing delivery. Do not repeat the
unchanged paced run solely to copy the exact same source bytes into a ZIP.

Local native source d37d2c37e3ac9cc2c860d0a2313a1526e30fd23e is published as
37c22983bc92055dd322085f191b054921d896d2 on native experiment/daily-hot-multi-
capacity-20261030 with identical tree38e33f634de94693b7b67b89d15418df82cd4d73.
Coordinator prior checkpoint6f60680 matches public d497c63ee6ae7f6fa43c6ef8ce14fb0a5a71c8f7;
subsequent files still need final commit/publication. Public coordinator branch
remains experiment/daily-hot-source-reliability-20261029. No main branch or
installed production source/environment was changed. Production activation and
concrete revised settings approval remain pending.

Windows packet scaffold: p85,85_verify_multisymbol.cmd,86_review_multisymbol.cmd.
Allow about10minutes/up to12; it retains about1.1GB synthetic proof data under runs.
Do not deliver until final source, focused verification and history evidence are
frozen. Fresh Hot startup remains pre-open. MondayNov2r0 is584/0/0, published and
audited; actual morningOV/r1/poller startup still due. Reported refresh expiry
Nov6covers Monday; no OAuth response was stored in these records.

---

## Historical checkpoints (preserved)

# Multi-symbol development checkpoint — not a qualified release

Operator goal: one practical multi-symbol envelope, forced market-closed bursts
and races; no market day per capacity increment. Friday production closeout,
Monday584/0/0 r0 and credential renewal are accepted in the operating-release
records. Production Hot activation remains unapproved. Original p83 and prior
accepted ZIPs are unchanged; this working source is not a replacement to run.

Implemented a separate sealed multi-40-v1 profile, preserving single-v1 defaults.
It proposes40authorized/active symbols and40outside-opening admissions,120
cumulative identity permits, at most3lookups per symbol, durable2-second spacing
and one pending command per pump cycle. Gate/normal admission/publication/native
collection/worker reconstruction and fixed public reviews carry the profile.
Identity child/client limits now derive from the bound policy. No live action.

Local observations so far:
-107affected existing operating/session/admission/launch/operator/review checks
  passed in7.102s before the preview-parser reuse change.
-The first new module run passed51checks in18.763s, including40unintentionally
  discovered imported legacy checks and11new identity cases. Import discovery
  was corrected; do not repeat the unrelated class in the packet.
-Three new native cases passed in186.654s:600opening Uni/40Focus grows to
  640/80/40, exact native batches/audit/replays, over-limit refusal, and an actual
  process exit after a40-row assembled response recovers without a second call.
  These use logical test time, not an elapsed capacity qualification.
-Profiling found DailySettings.preview discarded the native membership parser
  on each read. A process-local parser reuse was added, preserving fresh read
  transactions and complete persisted header/member comparisons.
-The next native run passed the first3cases but reported one fixture ERROR:
  tampering was correctly rejected with QuoteObservationStoreError rather than
  the test's expected ValueError. The test now expects the actual store error.
  That run took157.291s. Avoid repeated full600-row fixtures for unrelated cases.
-An uninstrumented advancing-clock40-symbol tick after all admissions, with
  no large acquisition prefix, MISSED the unchanged0.75s dispatch gate:
  total1.656318404s, state preparation0.952497307s, lateness1.705980s.
  Therefore40is not qualified. The cProfile diagnostic also missed but is
  instrumentation-inflated and is not capacity evidence. No gate was relaxed.

Current next work: reduce redundant full publication/membership parsing using
complete-value-checked derived data, then repeat the actual elapsed tick before
attempting representative retained-history and full owned burst/cleanup drills.
Do not treat logical correctness as timing qualification. Preserve rejection,
unknown-outcome handling, provider-stop latches, original3/8/15/10/60s gates and
old qualification scopes. New tests also cover cumulative120permits/per-symbol
caps; their current run result must be collected before reporting acceptance.

Uncommitted/next work may exist after this checkpoint. No new delivery ZIP,
Windows qualification, provider trial or revised production approval exists.


## Continued local development — October31 UTC

The prior parser-only checkpoint is superseded by additional uncommitted work.
The sealed multi profile now explicitly proposes five-minute active collection
periods, with complete retained quote/membership history in the same schema-v2
journal. Active heartbeats check active-period payloads and all membership data;
closed quote payloads are independently compared after stop. This is an explicit
integrity-scope change for review, not unchanged single-profile qualification.
The three native changes are in ../native_multi_capacity on experiment/daily-hot-
multi-capacity-20261030, based on5552c5d. Old accepted sources remain unchanged.

Unbounded full-history preparation FAILED:25.142s cold against3s and a missed
unchanged0.75s dispatch gate. Preserve that result. Periodized full-size fixture
with40Hot and concurrent-sized Uni/Focus history PASSED locally:996300rows,
9312Hot acquisitions/372480Hot rows; cold0.6010s; tail0.5822/0.6556s;
coverage audit and stored-value receipts passed; two fresh native-order event-ID
digests matched; final verification10.395s. Seeded history is not an elapsed day
or live-provider performance. The native-order digest is not full object replay.

The first actual paced owned41-candidate burst FAILED at123.7s after26admissions.
The source returned 'Authority already owned'. The common supervisor catches a
nested ServiceBusy as that same ownership message. New multi-only source logic
separates authority lease entry from inner publication contention and yields the
latter without retrying an operation. Three forced contention cases pass,
including a durable identity response followed by contention: no second quote.
No watchdog/cadence/15second hold/provider cap was extended. The paced run must
be repeated and pass before any release/Windows packet is described as ready.

A shutdown-only read checks native content without requiring a live acquisition
fence after stop. It cannot dispatch, recover, write a ledger or register runs.
Verified period receipts bind SQLite stored values; original writer JSON hashes
cannot be recomputed from SQLite rows because numeric affinity changes int/float
representations. A native coverage audit by itself does not detect arbitrary
quote-price edits. Final reports preserve that audit separately from the added
Hot stored-value integrity check and from event-order digest equality.

Outstanding: collect current focused-suite result; finish retained-period/resume
preflight and negative tests; repeat the corrected actual paced concurrent burst;
freeze/commit both sources; prepare exact-source Windows qualification packet;
review revised40symbol settings and integrity scope after Windows acceptance.
No new Windows ZIP, deployment, settings adoption or production activation yet.
