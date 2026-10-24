# Manual reopen of a bound experimental controller

This increment follows command-45 Windows acceptance. It is an explicit,
human-started reopen of a fully initialized, catalog-bound experimental runtime.
It does not initialize a partial bootstrap, change production, launch a live
profile, or supply the independently preempting outer/profile harness.

The caller provides the original configuration and runtime digests, unchanged
worker command, a new private-handoff nonce and the time of the new human
submission. Recompute the original plan from its original proposals, settings
and retained catalog; do not substitute the new submission time into that plan.
The original T0/Tstop, source identities, directory reservation, feed history,
identity selection/permits, requests/publications and native dispatch permits
remain authoritative. Missing/corrupt/partially initialized state is blocked.

Acquire the original controller lease before credential access. Inspect the
original dependencies and validate existing evidence before preparing a new
client. Credentials retain the 8s maximum and original refresh horizon. Reopen
preparation has at most 60s from this human submission, ending earlier at the
original Tstop. The synchronous API must run in an owned process; a private-pipe
entry independently enforces those preparation limits in the offline drills.
Neither limit starts a fresh acquisition window.

An append-only resume ledger binds the original runtime. Interrupted attempts
remain explicit and cannot reset another ledger. A missing ledger beside its
binding marker is not recreated. No password or SDK exception is retained.
Original bootstrap, runtime binding and stop receipts are preserved. Each new
controller's stop receipt has a distinct path; a later pass cannot erase an
earlier failure or stop.

After credential acceptance, fence a previously registered Hot generation with
its exact validated stop token and wait for its role lease. Never adopt an old
Popen handle, discover a PID or terminate an unowned PID. An orphan that does
not relinquish its role lease within the bounded preparation interval blocks
reopen. A delayed old generation remains fenced by its stop token and the new
registry. An orphan feed child must release its existing network lease before
its pending attempt is completed as interrupted; no replacement HTTP request
overlaps it. All uncertain work remains charged. The original 60s completion
spacing and attempt/deadline bounds survive reopening.

Reconstruct every component without create/initialize calls that could adopt
missing state. Validate native observations and recover a saved assembled
response/ACK before any new quote. An unassembled dispatch remains unknown and
charged, never refetched. Ordinary source delivery and publication recovery
remain idempotent. The replacement worker consumes the next original generation
permit, retains 3s first-work/3s stale and separate 8s credential gates, and
starts only at future slots. Inconsistent generation files, exhausted starts,
terminal provider/authentication evidence, or exhausted native/time bounds are
blocked rather than converted into another allowance.

Qualify unchanged fresh-runtime behavior plus affected reopen paths with
synthetic credentials/SDK/HTTP, actual owned processes, interruption boundaries,
saved native response recovery, one-symbol reuse, budgets, corruption, exclusive
ownership and redaction. Keep logical-clock and actual elapsed evidence distinct.
An operator Windows result is separate from local/extracted qualification.
Installed/live authentication, outer/profile goals/coverage, live recovery,
Overlay, production adoption and broader capacity are later gates.

## Current qualification

Source 4489d27a80a7359888d6471929785bb6b8160fe6/tree 2da67f6eacc14c9374d5f0df67134eec1de93eb7 passes 59/59 affected current-host checks in 88.99027961000002s and 59/59 source-pinned extracted checks in 87.3174064470004s, zero skips/errors/failures. All 100 mapped files match; altered/extra source is refused before tests and the original inventory restored. All 61 older runtime/reference files and original archives remain unchanged. Windows operator validation and actual prompt return are pending. A separate new manual-ready record states the added scope; original raw bootstrap/runtime labels and failure verdicts are retained. The final operator package exposes offline verification only.

## Command 46 Windows failure and corrective command 47

The complete operator console records command 46 FAILED: 58/59 passed, one PermissionError in the full-artifact secret scan after reopen assertions, zero skips/test failures, in 81.00486850005109s (runner 80.778s), run 20261024T004121Z-afff6828 and actual prompt return. The exact denied file is not named; the reported sidecar was not independently uploaded. The test still owns the resumed controller lease when it scans through separate file handles. Windows can deny access to exclusively locked bytes through another handle, consistent with this error; source establishes the lifecycle defect but not the exact original denied filename.

Command 47 closes that controller, verifies its stopped receipt, then scans every artifact including the lease file. Unreadable or disappearing files still fail with relative filenames and safe numeric/type diagnostics; no file is excluded or retry used to hide the error. Focused checks cover all five secret-scan call sites, binary marker detection, read-failure diagnostics, actual native Windows held/released lease behavior and affected redaction. All 63 runtime/native/helper files, original budgets/windows and 3s/8s gates are unchanged. The old FAILED verdict, archive and original local/extracted passes remain retained. Windows corrective confirmation is pending.
