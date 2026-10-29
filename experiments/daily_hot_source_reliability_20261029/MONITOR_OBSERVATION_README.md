# Capture the first controller-monitor exception

Keep the existing daily_hot_source_reliability_20261029_2f56703_5552c5d folder.
Extract this small helper beside it under mb_market_data/output. Run
69_observe_monitor_exception.cmd in a separate sea-green CMD window. Allow
about 2.5 minutes for the one paced proof; a failure may finish earlier.
No actual password, vault, broker SDK, provider or production change is involved.

The newly supplied dump-off archive identifies a controller monitor exception,
not an overdue collector heartbeat. Terminal worker_evidence_or_supervision_failed
comes from the monitor's generic exception handler. The saved collector heartbeat
is correctly bound and was completed at 14:00:19.053323Z; its recorded exit at
19.073070Z is only .019747 seconds later. The monitor's stop leads to child
fencing/exit 124, controller STOPPING and the outer stale label. The underlying
monitor exception was discarded, so its exact type/site cannot be recovered
from the existing files. Quote cadence, diagnostic dumping and CPU saturation
are not established initiating causes.

This helper verifies the complete frozen command-67 inventory. It reuses the
unchanged dump-off control, which turns two test-only stack flags off in memory.
It additionally inserts a Python observer around the original _monitor_once in
the owned controller process. If that method raises, the observer writes the
first error type, OS/SQLite code, trusted project module/function/line frames,
and previously held status values, then re-raises the same exception. It does
not retry the monitor operation, change its handler, add native stack dumping,
alter assertions, extend deadlines, repair state or edit original source files.
Exception bodies, local variables and provider payloads are not copied.
Only diagnostic instrumentation changes inside the synthetic test process;
the result explicitly reports that wrapper separately from original file bytes.

Seven local checks passed, including actual owned controller startup/cleanup
and an injected monitor permission error captured before the original terminal
handler stopped the children. They verify original exception identity/single
call, first-record preservation, diagnostic-write failure and omission of
private exception text. The unchanged complete paced proof/capacity/recovery
drills are not repeated locally for this observer-only increment.

verification.json includes monitor_exception directly. Diagnostic result
CAPTURED can accompany an overall FAILED proof: it means the first error was
recorded, not fixed. A passing proof without an exception is also retained but
does not prove the cause is resolved. No automatic rerun occurs. The original
commands 67 and 68 remain FAILED, and their local passes retain their scope.

Active synthetic state uses private temporary storage. Only closed forensic
copies are saved under this helper's runs folder; their original path bindings
must not be adopted or resumed as runtime. Provide the final report and actual
returned CMD prompt. Production Hot, provider capacity, deployment/settings
review and activation remain pending; original I/O and ledger-change causes
are not declared resolved.
