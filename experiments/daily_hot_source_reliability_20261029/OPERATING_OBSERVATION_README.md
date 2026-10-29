# Capture outer-owner and controller-monitor failures

Keep the existing daily_hot_source_reliability_20261029_2f56703_5552c5d folder.
Extract this small helper beside it under mb_market_data/output. Run
70_observe_operating_exception.cmd once in a separate sea-green CMD window.
Allow about 2.5 minutes; a failure may finish earlier. This is synthetic offline
work with no password, actual vault/broker SDK/provider or production change.

Windows command 69 FAILED after 18.234 seconds of paced execution. It records
outer stop operating_evidence_or_launch_failed and failure_type PermissionError,
with no controller-monitor exception captured. Cleanup observed the Windows Job
scope empty in .094 seconds without force. Audit and equal two-event replays
cover opening history; they do not qualify source reconciliation or collection.
The complete supplied report and returned CMD prompt are accepted as evidence.

That outer handler discarded the error's filename, Windows code and frames.
PermissionError does not distinguish access denial from a file-sharing conflict,
nor identify a Windows Security action, CPU problem or cadence overload. The
original test's stop callback also reads status files. Its failure would enter
the same outer handler, so this instance may originate in test observation code.
The exact operation and any relationship to earlier failures remain unproven.

The existing monitor observer remains unchanged. A second observer inserts one
guarded capture into the original outer _run exception handler in memory, after
the exception has already occurred. Removing that capture recovers the exact
original complete function AST; original source-file bytes and original handler,
stop, cleanup, assertions, budgets and watchdog deadlines remain unchanged.
There is no new active-loop check, trace hook, native stack dump or I/O retry.

The first owner receipt records error type, errno/winerror/SQLite code, filename
and filename2, trusted runtime/test/pathlib frame names and lines, and the phase
from the owner's last check. Frozen test callback frames are retained to identify
a testing artifact if one occurs. No exception bodies, arbitrary locals, secrets
or provider payloads are copied. Recording failure cannot replace the primary
error or skip its original cleanup. An existing first record is never replaced.

Eight distinct local checks passed, including real owned process startup/stop
and a callback PermissionError captured before original cleanup. They also
verify unchanged successful handling, same primary error/single operation,
diagnostic-write failure, first-record retention, cause codes, original runtime
locations and final-report inclusion. An earlier development assertion assumed
the owner refreshed its phase before the callback; the original order is the
reverse. That failed local test is retained, and the synthetic injection now
waits until the original owner has observed ACTIVE. No runtime fix was made.

The final verification.json includes both operating_exception and monitor_exception.
FAILED with diagnostic_result CAPTURED is useful: it captures the failure and
does not claim a correction. A PASS without an exception also does not resolve
earlier intermittent failures. No automatic rerun occurs. Commands 67, 68 and
69 keep their original FAILED verdicts; accepted component evidence is retained.

Provide the final JSON and actual returned CMD prompt. Closed forensic copies
retain temporary path bindings and must not be adopted as running state.
Production Hot activation, provider capacity and deployment/settings review
remain pending. The earlier I/O and ledger-change causes remain unassigned.
