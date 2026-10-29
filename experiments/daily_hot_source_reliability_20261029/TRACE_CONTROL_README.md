# Periodic stack-dump control

Keep the existing daily_hot_source_reliability_20261029_2f56703_5552c5d folder.
Extract this separate small helper under the same mb_market_data/output folder
and run 68_control_periodic_stack_dumps.cmd in a separate sea-green CMD window.
Allow about 2.5 minutes. No password, real SDK, provider or production operation
is involved. This is one diagnostic control, not a repeat of fifty checks.

The helper verifies the complete original command-67 source inventory before
import and after execution. It changes exactly two test-only trace_stacks flags
to false in memory and runs the original paced test, retaining its assertions,
real sixty-second feed intervals, watchdogs, ownership, budgets and deadlines.
It edits no original source/test file and installs or activates nothing.
Active synthetic state uses private temporary storage; closed forensic evidence
and verification.json are copied under this helper's own runs directory.

The supplied Windows archive establishes that the first collector exited with
3221225477 (0xC0000005, an access violation), not the normal watchdog exit 124.
Its last saved heartbeat was less than two seconds old at observed exit. The
identity process's diagnostic log ends partway through its first stack dump.
Both CURRENT and historical RSS responses are valid. The identity request then
fails immediately, before any synthetic quote was logged; the identity gate
records provider_stop_required, which leads to IdentityStopRequired and the
controller stop. The outer stale label follows that stop.

The native crash and truncated diagnostic log make periodic native stack
dumping a strong suspect. They do not identify the exact faulting module or
prove a particular CPython bug. Relevant upstream reports and Microsoft's
status-code definition are recorded in the analysis. A separate local metadata
churn micro-reproducer did not reproduce a crash in two short tracing-on and
two tracing-off runs; this inconclusive result is retained.

The same full paced proof with periodic stack dumps off passed locally in
126.538 seconds: three valid attempts, reconciled declared source scope,
26 Hot acquisitions including two after reconciliation, one worker start,
native audit and matching 29-event replays, successful scoped cleanup. This
does not establish the result on Windows or prove precise crash causality.

Original command 67 remains FAILED 49/50. Passing this control alone does not
turn it into a full operating-release, live provider or full-day qualification.
The old I/O and publication-ledger-change causes are not declared resolved.
No production Python upgrade, timeout change, runtime edit, live launch or
activation is included. Provide verification.json and the returned CMD prompt.
