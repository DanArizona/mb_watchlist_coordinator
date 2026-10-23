# Subsequent-halt fixture and failure evidence — command 45

Command 44 **FAILED on Windows**: 292/293 passed, one first-acquisition
timeout before child fault injection. Its original archive, console evidence,
local/extracted PASS and Windows FAILED records remain intact. The original
Windows cause is **unknown**, because that run did not retain the temporary
runtime/source/worker state.

An independent controlled boundary reproduces a fixture defect: if a synthetic
observation follows the startup baseline by 5ms, the old arbitrary 10ms
backdating puts its halt before startup. The accepted producer correctly records
`predates_startup` and queues no request. This reproduction does not establish
the original Windows failure's cause.

The corrected fixture waits for a clock strictly later than the retained
baseline, records the halt at that observation, then checks `request_queued`
before waiting for a native acquisition. It does not invent future knowledge,
compress the 60s HTTP cadence, or change any production/source semantics.
Boundary checks include 1 microsecond, 5 milliseconds and a refused same/earlier
tick. The process proof still uses a separately identified external synthetic
observation, not an additional public RSS request.

Failures/errors in the process fixture now save allowlisted phase, controller,
source disposition, identity permit, worker/startup/heartbeat/exit and native
acquisition facts under the run's `failure_evidence/` folder **before** cleanup.
No arbitrary configuration, SDK exception, stderr or pipe contents are copied.
Missing diagnostics do not hide or relabel a failure. A controller stop fails
the outstanding acquisition wait promptly, with its phase identified.

Only the affected fixture/evidence, runtime-pump and first-work checks run here.
Unchanged previously accepted suites are not repeated. All 61 command-44 runtime,
native and public helper source files are hash checked unchanged. The original
3s startup, 3s staleness, separate 8s credentials, 750ms dispatch gate, one-symbol
fence, 3 identity/60 Hot permits, three worker starts and frozen 720s window
remain intact. The verifier's separate 240s process ceiling is not a runtime
profile or provider qualification.

Run `45_verify_integrated_runtime_fixture.cmd` in sea-green and retain final JSON
plus the actual CMD prompt return. This is offline, with synthetic encrypted
configuration/SDK/HTTP and owned processes only. No password, real vault,
installed SDK, public feed/directory/broker request or production access is used.
There is no live controller command. Full manual resume, the independently
preempting outer controller/profile harness, live acquisition/recovery profiles,
Overlay, production adoption and broader capacity remain pending.

Local, extracted-package and Windows operator results are separate records.
The original command-44 FAILED verdict cannot be overwritten by a later PASS.

Current-host affected qualification: **52/52 PASS**, zero skips/failures/errors,
38.96151868299967 seconds (runner 38.865s). All 61 runtime/reference hashes
match command 44. This is local evidence; source-pinned extraction and Windows
operator validation are separate gates.
