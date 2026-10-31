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
