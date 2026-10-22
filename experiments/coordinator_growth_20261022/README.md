# Native rich-history measurement and recovery receipts

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
are recorded in `validation/`. Native Windows qualification is pending.
