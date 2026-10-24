# Explicit manual controller resume — command 46

This offline increment follows command-45 Windows acceptance. It adds
`controller_resume.py` and `resume_entry.py`; all 61 earlier accepted Coordinator,
native and public helper source files remain hash checked unchanged. No live
controller command, real vault, installed SDK, public directory/feed/broker
request or production access is used by this qualification.

## Reopen behavior

An explicit caller supplies the original configuration/runtime digests and
unchanged worker command, a new human-submission time and a new private-handoff
nonce. Reconstruct the original plan from its original proposals, dependency
inventory and saved catalog. The new submission time never replaces the
original T0/Tstop. A missing/corrupt/partial original bootstrap, source, native,
identity or publication ledger is blocked; none is adopted or recreated.

The original controller lease precedes credential access. A new client must
pass the original pre/post refresh horizon through Tstop plus 75m30s. A separate
append-only resume ledger retains requested/authenticated/ready/stopped or
failed/abandoned attempts. Its binding marker prevents recreation of a missing
ledger. Original bootstrap, runtime binding and stop receipts remain intact;
each resumed controller has a distinct stop receipt. Old scope labels in those
receipts are not rewritten; the new manual-ready record describes this slice.

After credential acceptance, the registered old Hot generation is fenced using
its exact validated stop token. Reopen waits for its role lease without PID
discovery, adopting a Popen handle or terminating an unowned PID. A delayed old
generation remains fenced. A busy unowned role blocks reopening within the
existing deadline. An orphan feed attempt must relinquish its network lease
before its unknown result is finalized; no new HTTP attempt overlaps it.

Saved native assembled responses and acknowledgements recover without another
quote. Unassembled dispatches remain unknown and charged. Existing request
delivery and publication ACK recovery stay idempotent. The same selected
symbol, directory/feed/identity/Hot budgets and worker-generation history remain
authoritative. The next worker consumes the next original start permit and
acquires only future slots. Terminal evidence and exhausted bounds remain
blocked, rather than gaining a fresh allowance.

Preparation has at most 60s from this human submission, ending earlier at the
original Tstop. Its private-pipe entry independently enforces the separate 8s
credential maximum. The original worker 3s first-completed-work, 3s staleness,
8s credentials, 750ms dispatch gate, one symbol, 60 Hot + 3 identity permits,
three starts, two directory permits, ten paced feed attempts and frozen 720s
window remain intact. Read-lease retries recognize Coordinator ServiceBusy and
native AcquisitionBusy within those existing bounds; they repeat no provider
work or deadline. No password/SDK exception is retained in argv, environment,
reports, files or inherited SDK output.

## Qualification and limits

The affected checks use fabricated encrypted configuration, pinned public
mb_tools interfaces, synthetic SDK/HTTP and actual owned child processes.
They cover controller exits before/after reopen, orphan generation fencing and
generation-2 work, three-start exhaustion across human reopens, saved native
response recovery across worker/controller exits, live role-lease contention,
independent credential/preparation deadlines and output redaction. The native
59 unknown dispatches + one remaining quote check uses a logical clock; it is
not elapsed market activity or a provider-capacity measurement.

The suite also retains selected original fresh-only ownership and 3s/8s worker
regressions. It does not rerun unchanged earlier command packets. Failures in
the new native/process fixtures save allowlisted phase/source/worker and manual
controller traces before temporary cleanup. Arbitrary SDK messages and private
configuration/pipe contents are excluded; diagnostic failure cannot hide the
original result. All development failures and independent controlled findings
remain under `validation/`.

Run `46_verify_manual_controller_resume.cmd` in sea-green; retain the final JSON
and actual CMD prompt return. No password or open market is required. The
verifier's separate 300s process ceiling is not a controller/profile deadline.
Installed/live authentication, the independently preempting outer/profile
goals/shutdown/coverage/audit harness, separately invoked live profiles, Overlay,
production adoption and broader capacity remain pending.

Current-host affected qualification: **59/59 PASS**, zero skips/failures/errors,
88.99027961000002 seconds (runner 88.664s). All 61 accepted runtime/reference
hashes match. Source-pinned extraction and Windows operator acceptance are
separate gates. Earlier command-44 and development failures retain their
original verdicts and scope.
