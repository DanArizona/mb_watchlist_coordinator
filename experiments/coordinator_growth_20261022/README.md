# Native rich-history measurement and recovery receipts

**Historical baseline:** The retained results and original unchanged ZIP below
refer to the source pins recorded for that increment. This branch now also has
a [history-cost follow-up](../coordinator_history_cost_20261022/README.md), which
changes shared request/publication code and the experimental metadata dependency.
Its Windows command 30 remains pending; command 28 acceptance applies to its
original pinned delivery.

This increment implements the first workload in
[the scaling/recovery specification](../../docs/design/scaling_recovery_qualification_20261022.md).
It is isolated experimental source. No provider access, credentials, production
journal or main-branch installation is involved.

## Rich-history builder

`qualify.py` constructs the 1,000-receipt / 200-publication profile through the
native request and publication APIs. Fifty deterministic rounds exercise
independent manual, algorithmic and Nasdaq requests, overlapping demand,
outside-Uni admissions retained in Uni, restrictions/expiry, future requests,
demotion timers, rejected commands, identical retries and conflicting ID reuse.
Each round checks four complete hand-specified hierarchies, with Hot counts
40, 41, 40 and 0. Of the inserted receipts, 95% are non-tick commands. The
543/40 opening fixture has a 64-identity additional catalog; 50 are admitted
over the full workload. Synthetic date November 2 is fixed; it is not a claim
that a real session has run.

Fixture construction uses logical time. Measurements use monotonic elapsed
time, 100 idle cycles and three fresh-process cold reopens. The full request
state and publication snapshot are checked again, and fixture database bytes
must remain unchanged. Earlier quiet-history fixtures are not being rerun.
All 25 existing Coordinator runtime files remain byte-identical to the
Windows-accepted second scaling increment. The new recovery module does not
participate in this benchmark.

The report labels real-clock state-changing performance, burst drain,
10-minute memory soak, separate growth axes, busy/stress profiles, the full
recovery fault matrix, native Windows and provider qualification NOT_RUN.
Even a passing idle measurement therefore remains INCOMPLETE qualification.
A performance-gate failure returns exit code 2 while retaining its report;
construction/integrity failures retain a FAILED report and propagate the error.

Example source-tree invocation, in an isolated output location:

```text
python -I -B experiments/coordinator_growth_20261022/qualify.py --output <new-absolute-folder>
```

Do not use an existing or production folder. A smaller `--rounds 1..49` run is
only a smoke fixture, not the ordinary profile. `--repeats` can reduce a local
diagnostic sample; the full ordinary idle measurement uses 100.

## Explicit recovery receipt stage

`nasdaq_recovery.py` adds the separate contract
`nasdaq-halt-recovery-receipts-v1`. It binds a dated-query manifest and explicit
late-start/resume mode to an existing validated request identity. Each receipt
retains a supplied HISTORICAL snapshot, query ID, capture time, recovery receipt
time, original halt time, hash/provenance and a checked hash chain.

First-stage behavior:

* Retain same-day selected halt candidates, including already-resumed examples.
* Deduplicate stable event IDs; retain updates and distinguish repeated halts.
* Keep ambiguous original reasons and prior-day/off-hours context explicit.
* Distinguish completed query scope from missing intermediate trace/carryovers.
* Reject a changed identity, unavailable future evidence, conflicting capture,
  backward clock and receipt outside 09:30–16:00 ET.
* Serialize identical capture retries and close all owned SQLite handles.
* Refuse to recreate a missing ledger on normal reopen. New experiment creation
  is explicit and exclusive.

It deliberately does **not** deliver requests, authenticate/resolve symbols,
fetch or parse raw HTTP bodies, orchestrate restart, publish membership or mark
the complete system READY. Its snapshot says `RECEIPTS_ONLY`, `RECOVERING`,
`delivery=NOT_IMPLEMENTED` and `publication=NOT_ATTEMPTED`. The existing live
producer's CURRENT baseline-only and HISTORICAL audit-only meanings are intact.
Transport pacing/failure receipts, live-producer pending-command reconciliation,
normal admission delivery, the shared event registry and process supervision
are subsequent implementation work.

## Validation

The affected local suite covers the new stage/harness plus the existing Nasdaq
adapter and publication service. Complete run results and measurement findings
are recorded in `validation/`. The changed-path suite is now accepted on
MasterBot Windows: 87 checks passed in 8.311 seconds, with actual CMD prompt
return. See [the Windows record](validation/windows_qualification.json) and
[the supplied console](validation/windows_operator_console.txt). This accepts
command 28 only; complete recovery and native Windows capacity remain pending.

### First complete cloud result

The controlled tmpfs run completed all 1,000 native receipts and 200 changed
publications (201 journal revisions including the anchor). Every complete
hand-specified hierarchy matched. Of 1,000 receipts, 700 were accepted and 300
rejected with the expected reasons; 50 identical transport retries and 50
conflicting ID submissions did not insert additional receipts. Construction
took 2,045.074 seconds (34.1 minutes), including native validation and the
separately recorded read-only diagnostic profiles. It is not elapsed session
capacity.

| Measurement | Observed seconds | Experimental gate | Result |
| --- | ---: | ---: | --- |
| 100 idle cycles, median | 4.356894 | descriptive | measured |
| 100 idle cycles, p95 | 4.951636 | at most 0.5 | FAILED |
| 100 idle cycles, maximum | 5.156493 | at most 1 | FAILED |
| Three fresh cold reopens | 4.494455 / 4.839739 / 4.614606 | each at most 10 | PASS |

Complete request states and publication snapshots matched after measurement,
and fixture database hashes remained unchanged. Native membership audit PASS;
two fresh-process native replays each yielded 201 membership events with
sequence digest `633ae24f080102d507986f6dae41d210ff14059cabed1f40190e46d0a4902289`.
There are zero quote acquisitions/observations, so this is membership evidence.

**Correctness PASS; measured idle performance FAILED; overall qualification
INCOMPLETE.** This is cloud tmpfs evidence, not MasterBot disk/provider capacity.
The first workspace-backed construction stopped after reported progress of
120 receipts/24 publications with `Publication head changed during cycle`.
Its retained request tail is 125 and publication head is 47 (a pending plan
with one journal commit awaiting ACK). The failed run is preserved unchanged;
the successful controlled run does not establish its cause or reclassify it.

The read-only profiles identify request timestamp/replay work and repeated
membership/metadata reconstruction in the journal bridge. They ran during
construction and are diagnostic, not isolated capacity timings. Further
optimization must preserve every identity/hash/admission/clock/publication
check. Ordinary idle gates must pass before moving to the busy profile or an
updated longer integration trial.

### Windows handoff

The uniquely named `coordinator_growth_20261022_194538_a2fc56.zip` has SHA-256
`fd6e9795608a23a88c0c8895d972b6d9a0c110b80e3b7744f98e7d26f002802a`.
Its extracted source passes all 87 affected checks in 9.972 seconds locally,
including a path with spaces; altered inventory is rejected before tests.
The source-tree run passed those 87 checks in 8.285 seconds.

`28_verify_growth_recovery.cmd` is COMPLETE on MasterBot Windows: 87 tests
passed in 8.311 seconds, network denied, no production access, and the actual
CMD prompt returned. The operator supplied the complete console; the reported
JSON file itself was not uploaded. No unchanged repeat is needed.

`29_measure_coordinator_growth.cmd` is the separate long measurement entry
point. Do not run it unchanged now: the complete cloud fixture has already
identified a failed idle timing gate. Optimize the measured costs first. This
Windows verification does not reclassify that failure or qualify complete
recovery, provider capacity or production adoption.
The delivered ZIP remains unchanged. Source and delivery/validation records
are committed on the experimental Coordinator branch; production is unchanged.
