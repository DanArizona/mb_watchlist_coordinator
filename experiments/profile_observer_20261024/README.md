# Read-only profile progress observation — command 49

Command 48 remains **FAILED on MasterBot Windows**: 41/42 passed, no skips,
one coupled native integration failure, 30.369659999967553s (runner 30.055s),
run 20261024T061524Z-65760ca2 and actual CMD prompt return. Both named native
Windows Job Object cases completed without a skip. The overall raw verdict
and its windows_job_object_qualified=false field remain unchanged. Its saved
report/sidecar were not independently uploaded; the supplied console and fixed
inline failure evidence are retained separately. Do not repeat command 48.

The console reports worker_credentials_rejected, but that broad runtime label
also covers failures in the native startup path before/after credential
acceptance. The worker's actual auth status code and underlying exception were
not included. The exact original Windows cause is therefore UNKNOWN.

A controlled synthetic test establishes a concrete observer defect: the old
progress reader takes the acquisition writer's exclusive lease. Holding that
lease while the worker starts makes its required pre-credential native read
raise AcquisitionBusy; the child exits 70, saves startup_failed and the parent
reports worker_credentials_rejected before the synthetic client is constructed.
This reproduces the generic stop without proving the original Windows error.

The new active observer takes no acquisition writer lease. It captures a
read-only native event prefix, verifies its identity/hash sequence and checks
acknowledged journal receipts, headers and normalized rows through the original
native receipt reader. Journal work newer than that prefix waits for a later
observation. A committed response without ACK cannot count; empty membership
stays a skip; missing/invalid provider statuses remain unchanged. Only SQLite
BUSY is deferred to a later bounded observer turn, with no read retry loop,
provider-call retry or deadline extension. Other integrity/SQLite errors fail.

These are active progress observations, not a replacement final verdict. After
owned work stops, the original strict native snapshot, exact full ledger/journal
matching, raw audit and two fresh replays still determine the final result.
All 63 original runtime/native/helper references and 68 other command-48 runtime
files are hash checked unchanged. The original 3s startup/staleness, separate
8s credentials, frozen window and cumulative budgets are not relaxed.

A new test-owned worker entry adds only safe failure diagnostics: fixed auth
code, exception type, numeric error codes and stack file/function/line. It does
not copy messages, locals, SDK stdout/stderr, configuration or token contents.
The original shared worker fixture and runtime sources remain unchanged.

Current-host qualification: **25/25 PASS**, zero skips/errors/failures,
7.2422951329999705s (runner 7.109s), network denied and synthetic credentials,
SDK, native journals and owned children only. The focused packet covers active
observation, controlled old contention, successful original-bound worker startup,
affected profile policy and one native synthetic quote/read-only reporter path.
Previously passed Windows Job drills and unchanged full-profile workloads are
not repeated. Local, extracted and operator Windows results are separate gates.

Run only `49_verify_profile_observer.cmd` in sea-green and retain final JSON
plus actual CMD prompt return. No password, actual vault, public feed/directory/
broker request or production journal/process access is used. Windows correction
acceptance is pending. Existing command-48 archives/results remain intact.

This is not installed/live authentication, an attribution of the original
Windows exception, a completed elapsed/live profile, provider capacity or
production adoption. Credential-bound live entry/launchers and their affected
qualification, separate live profiles and the read-only Overlay adapter remain
later gates.
