# November 2 first production Hot failure investigation

The frozen p85 first production interval failed. At its saved cutoff10:57:19.858960EST,
Hot had2016acquisitions,16290quote observations,11request_error observations,
52empty-membership skips and28missing slots out of2096configured slots. Stored
Hot values and matching event-order replays passed; native coverage audit failed.
The final failed batch was local, not eleven failed HTTP requests. Healthy
Uni/Focus continued with592/50members and zero missing slots after grace at11:14.
The complete scoped operator findings are retained in
../credential_feedback_20261102/PRODUCTION_FAILURE_OBSERVATION.json.

Actual quote request timing does not overlap the final failed Hot slot with Uni
or Focus. Their acquisition completions were10:57:00.720 and10:57:10.202EST;
recorded write durations were62ms and reported0.0s respectively. Previous Hot
acquisition completed10:57:16.423, its native journal write took3.76ms, and its
acknowledgement event was timestamped10:57:16.514. No long acquisition-journal
write appears in these excerpts. This does not exclude unmeasured disk/CPU/
scheduling/lock work elsewhere. CSV durations are rounded/timer-limited and the
ack timestamp precedes that acknowledgement's own sidecar commit.

The failed native dispatch timestamp was655.506ms after its slot, wrapper entry
748.125ms, and the local refusal was assembled751.973ms after the slot. The
750ms final dispatch deadline is strongly indicated, but the combined exception
does not retain which predicate failed. The extra earlier delay is unmeasured.

An offline logical-clock reproduction now uses the actual DailyHotCollector
quote callback, batch normalizer and collector tick. It demonstrates that3ms of
local final-check work after entry at748.125ms is sufficient to produce this
same error, eleven per-symbol request_error outcomes, a blocked tick and zero
provider calls. The within-limit case succeeds. True41-symbol and121-call
violations also block. Publication/ledger preparation and native sampling are
synthetic trusted seams: this is not a new owned/native/provider/Windows or
capacity qualification, or proof of the original Windows delay's cause.

```bash
PYTHONPATH=src:../native_multi_capacity/src python -B experiments/daily_hot_failure_20261102/reproduce_dispatch_refusal.py
```

The native first/second lateness checks return a missed slot. The final collector
check instead uses the same fatal latch as real roster/budget violations. That
inconsistency is a concrete correction target while retaining the750ms ceiling,
no catch-up requests and immutable budgets. A later operating delivery must be
reviewed before any changed behavior is used in production. No runtime fix is
applied by this reproduction.

The outer stale label also conflates a non-RUNNING state with an aged heartbeat.
Saved STOPPING evidence was only16.152ms old at the outer stop. This strongly
indicates shutdown misclassification; the exact snapshot the outer read was not
retained, so no three-second freeze is established by that label alone.

Next retained-evidence check: match all28missing slot IDs to ledger missed,
abandoned and write_failed records, distinguishing explicitly refused slots from
slots the scheduler advanced past. New instrumentation must separate wake-up,
initial validation/lock time and later pre-provider work; it cannot reconstruct
the unrecorded split in this historical interval.

Keep p85's terminal block, original journals/ledgers and failed verdict intact.
Its current terminal fails the approved manual-resume preflight. No state reset,
after-open fresh start, deadline expansion, live requalification or production
change is performed here. Uni, Focus and Health remain independently managed.

## Retained Windows gap classification supplied next

The operator's read-only query accounts for 22 of 28 missing slots: 18 native
before-dispatch deadline misses and 4 abandonments after durable dispatch but
before the API. Their recorded lateness spans 0.810966 to 1.307910 seconds, above
the unchanged 0.750 second ceiling. No write_failed event matches these 28 slots.
The other 6 have no matching missed/abandoned/write_failed event in that query;
this alone does not establish absence of every possible event. Complete
operator data is retained in PRODUCTION_SLOT_GAPS.json. The final 10:57:18
request-error acquisition is separate from these 28 missing acquisitions.

The original collector chooses the next future slot after the current cycle
finishes. A second offline reproduction now uses actual native persistence,
coverage audit and two native replays. Without a clock fault, its tail-window
coverage passes. Advancing a logical clock 3 seconds after a synthetic response
causes a successful :54 cycle to select :58 next, leaving :56 missing with no ledger
event. Coverage correctly fails while replays still match. This demonstrates
an existing way to produce the empty-event shape, not the actual cause of
the 6 Windows gaps. It does not change the runtime or repair the original audit.

```bash
PYTHONPATH=src:../native_multi_capacity/src python -B experiments/daily_hot_failure_20261102/reproduce_scheduler_advance.py
```

Next retained read: metadata for neighboring slots around the 6 unmatched gaps,
and nearest feed-completion times around the 22 recorded deadline
misses. Correlation cannot itself attribute CPU, disk or lock delay. A focused
correction must also make skipped-slot reasons durable, preserve their coverage
failure, distinguish final deadline refusal from fatal policy violations, and
persist stage timing. Improving the final stop behavior alone cannot recover
missing observations or establish reliable cadence. No unchanged long proof
or new provider trial is needed for these read-only/controlled investigations.

## Actual neighbor chronology and source correlation

The next operator attachment explains all six previously unmatched slots at
the operation level. In each case the preceding Hot cycle was still saving its
response when the next slot arrived. Its acknowledgement was timestamped
77 to 458 ms after that next slot. The original future-only scheduler then
selected the following slot. The collector phase took 1.905 to 2.294 seconds;
the native acquisition-journal writes took 2.07 to 2.47 ms. These are not isolated
measurements of provider latency. Actual metadata and derived comparisons are
retained in PRODUCTION_TIMING_CORRELATION.json.

All 22 explicit deadline misses follow a nearest feed completion by 1.241 to
10.047 seconds; 17 are within four seconds. This identifies source/publication
processing as a leading area to profile. It does not directly identify which
Windows lock, thread or validation stage consumed a particular delay.

## Separate source-history optimization candidate

The offline profile reconstructs source/request/publication ledgers with an
opening 600-symbol Uni and 40-symbol Focus, eleven authorized synthetic Hot
symbols and repeated CURRENT captures of 150 rows. A logical 60-second interval
generates history without waiting through a market day. No HTTP transport,
credentials, actual provider or production process is used.

Before this change, a changed-source collector publication read at 91 retained
captures took 773.882 ms on this Linux machine, versus 26.666 ms when unchanged.
Call attribution located repeated full Nasdaq receipt reduction in the changed
path. Pure input-value memoization first reduced the changed read to 445.527 ms.
Reusing the verified receipt prefix reduced it to 172.510 ms in the same workload.

The source reader still reads and compares every old SQLite sequence, capture ID
and payload value exactly. Only after those comparisons match does it reuse an
immutable prior reduction and run the original receipt semantics on the new
tail. Current request and delivery checks still run. A new reader starts with
full replay. The cache is local to the reader, never persisted, and cannot adopt
modified/deleted/rehashed old rows. Pure dated-time and event-ID caches contain
no authorization or policy result. Shared public reads are serialized before
establishing their SQLite snapshot.

A further 390-capture history with 150 rows per repeated capture completed through
a logical 15:59:50 EST. At the final sample its changed read took 537.940 ms,
unchanged read 29.657 ms and fresh publication-reader construction, including
cleared pure value caches, 2496.853 ms. This is a source-reader component
measurement, not an end-to-end worker progress or Windows/provider qualification.
Copying full frozen source views remains a growing cost and a cold reader still
needs meaningful startup margin. Measurement provenance and the first small
profile's profiler overhead are explicit in PROFILE_NOTES.json.

Local validation passed 196 checks: 13 new focused cache/prefix checks plus
source/recovery/delivery regressions in a 99-check run, followed by 97 affected
multi-symbol/publication/native/source/manual integration checks. Both runs have
zero failures and errors. LOCAL_SOURCE_VALIDATION.json binds the current changed
source and tests by SHA-256. The original dispatch and scheduler reproductions
remain reproductions of behavior that this source-history change does not fix.

The complete operating correction is still pending: classify a final local
deadline expiration separately from a fatal policy violation; retain durable
reasons for skipped slots without inventing quotes or empty skips; persist phase
timing and report shutdown state accurately. Then package and qualify the exact
changed operating candidate on Windows. Frozen p85, its failed interval and
terminal state remain unchanged. No production resume, reset or activation is
performed or implied by this development result.
