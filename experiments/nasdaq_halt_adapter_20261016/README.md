# Recorded Nasdaq halt adapter review

This increment connects normalized Nasdaq feed snapshots to the accepted durable
source-owned sampling request path. The library module performs no network call,
starts no scheduler, and changes no production journal or process.

## One Windows check

With sea-green active, call the root 01_run_nasdaq_halt_adapter.cmd. The window is
titled NASDAQ-COORDINATOR-REVIEW. It runs 46 focused tests (37 adapter/store tests
and 9 recorded-evidence/publication checks), followed by a separate retained proof,
and returns to the prompt. No package installation, password, browser or network
is needed. Python 3.12+ and America/New_York timezone data are required. The runner
accepts no external path or argument. Each run creates fresh outputs under runs/.

Expected final marker: Recorded Nasdaq adapter proof: PASS.

## Real evidence and simulation are separate

The user supplied nasdaq_halt_evidence_20261017_002647_d1aec5.zip containing twelve
raw.xml/normalized.json pairs: four CURRENT snapshots from August 14, five
HISTORICAL queries for August 13, and three HISTORICAL queries for September 28.
All 24 original files are byte-preserved in the review ZIP and checked against
evidence_manifest.json. The 12 XML responses parse into 690 rows. The pinned
parser is the exact Git blob from mb_market_data a082f5441126, recorded under
reference/PROVENANCE.json. Older normalized JSON predates some parser improvements;
normalization differences are reported while original files remain unchanged.

All four CURRENT snapshots were acquired after the regular close. The first three
contain the same 57 normalized events; the last has 60, including three newly
observed after-hours records. Replaying those snapshots with original receipt
values submits zero promotion requests. They are evidence for format, baseline,
repeat/update and after-hours behavior, not a new live LUDP/M promotion trial.

A separate arrival simulation selects two distinct real AEHL LUDP examples from
the August 14 feed. It explicitly maps their halt dates/times into a hypothetical
next-calendar-day session with an injected clock. That date may be a weekend; it
is not a trading-calendar recommendation. Each derived row retains its original
record and event ID, and each snapshot retains the original capture time/hash.
The original XML is never rewritten. The raw hash identifies the original source,
not a claim that the derived rows were received from Nasdaq at the mapped time.
Reports, request metadata and journal revisions label the simulation. The real
SQLite store supplies actual publication timestamps; all fixture effective times
are in the future. No live discovery latency or provider timing is established.

## Explicit review policy

| Concern | Behavior in this increment |
| --- | --- |
| Qualifying reasons | Explicit configured tuple; proof selects LUDP and M |
| Membership eligibility | Symbol must be inside the fixed Uni |
| Event/receipt window | Both must be in 09:30 <= time < 16:00 ET for the configured date |
| Startup | First CURRENT snapshot is baseline only, for all records |
| Late old records | Events before the initial capture boundary do not become new requests |
| Request lifetime | Explicit regular_close selection: expires at 16:00 ET, not on resumption |
| Event identity | Canonical symbol plus halt timestamp; reason/resumption updates retain identity |
| Repeated halts | A later distinct timestamp for the same symbol is a separate request |
| Historical input | Audit only; cannot initialize CURRENT baseline or submit requests |
| Ordinary policy | Proof retains explicit 60s grace/120s residence/immediate_cap settings |

These are review selections and supported semantics, not adopted production
policy values. Initial active-halt catch-up, any alternative request lifetime,
corrections to the provider's identity timestamp, and other eligibility policies
need a separate design before production use. The already accepted Coordinator
continues to resolve combined manual/Nasdaq demand and privileged restrictions.
Resumption and temporary feed disappearance do not cancel a regular_close request.
Withdrawing one event/source does not withdraw another event/source.

## Durability and delivery boundary

NasdaqSamplingProducer stores immutable hash-chained snapshot receipts bound to
its settings and the request ledger's session/baseline/policy identity. Replay
derives observations, stable request IDs and pending requests. Exact capture retries
keep their original receipt; conflicting IDs, clock reversal, future knowledge and
inconsistent history fail visibly. Empty valid RSS can establish a baseline;
invalid/unrelated XML is rejected by the parser boundary. Hashes are consistency
checks, not signatures or authentication of the provider or local clock.

A serialized worker delivers pending requests into SamplingRequestStore, then
records acknowledgement. If interrupted after the request commit, retry reuses the
original request receipt. It cannot revive a withdrawn request. A pending request
that expires before delivery is durably rejected rather than promoted late. The
producer acknowledges request admission, not membership publication. The running
Coordinator publication loop/outbox is still pending. External caller authentication
is outside this trusted local API boundary.

The retained simulation has five producer receipts, seven request receipts and
eight complete hierarchy revisions. It covers startup, first promotion, exact
retry after a lost acknowledgement, manual withdrawal leaving Nasdaq demand,
repeat/update suppression, a distinct second halt under a cap and reevaluation on
clear. The real schema-v2 journal audit passes and two replays agree; publication
retry is idempotent. Channel-write failure rolls back a complete revision.

## Source and evidence storage

Source, tests, pinned parser, evidence hashes and compact validation summaries are
tracked in Git. The uploaded raw/JSON capture files and generated databases/reports
are ignored. The review ZIP includes the exact evidence files in evidence/.
To reproduce from a Git checkout, extract the original uploaded evidence ZIP into
this experiment's evidence directory, preserving its capture subfolders. Full
new run reports retain their own timestamps/hashes. See VALIDATION.md.

Windows acceptance is pending. No production installation, live halt acquisition,
Hot poller or measured Hot cadence is included. Next after acceptance: the running
publication/recovery service and isolated Hot acquisition, followed by a genuinely
new live halt trial. Existing production Uni/Focus polling and candle work retain
their own scope.
