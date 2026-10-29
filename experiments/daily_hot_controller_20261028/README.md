# Daily authenticated controller — offline Windows qualification

This increment connects the Windows-accepted daily publication and collection
APIs to separately owned identity and Hot processes. Credentials use the
existing `.ecfg` convention and private stdin handoff. The tests supply a
synthetic SDK and synthetic journals; they never open the actual vault or
request actual provider/feed data.

Run `62_verify_daily_hot_controller.cmd` in sea-green and supply its final JSON
and actual CMD prompt return. Expect approximately two minutes: the recovery
drill waits the full fifteen seconds, and deadline drills wait their real
elapsed bounds. Zero skips/errors/failures and both retained proofs are required.
This does not repeat the accepted command-60/61 suites or live profiles.

## Implemented and exercised

- A worker-side publication reader verifies original r0/r1, catalog, claim,
  request/admission and publication ledgers without taking the controller's
  lifetime publication lease. Both sides tolerate a brief publication-read
  collision for at most 0.2 seconds; integrity errors remain blocking.
- Separate authenticated identity/collector processes receive the manual
  session password only over a private pipe. SDK output and exception bodies
  are suppressed. Native progress must complete within three seconds of the
  worker job start; credential startup remains bounded by eight seconds.
  Successful credentials alone are not native progress.
- Every new provider dispatch checks the original binding and an active,
  fresh controller invocation with its actual OS lease. Actual controller loss
  fences both orphan roles. Missing state/registry cannot reset budgets.
- Starts are charged before process creation. Three starts are cumulative
  across controller resumes. A confirmed exit requires the full fifteen-second
  replacement hold in both wall and monotonic time. Resumed collection begins
  at a future slot and recovers a saved response without requesting it again.
- Explicit manual resume requires the original complete ledgers, remaining
  budgets, a fresh manually supplied secret and free original role leases.
  An old/unowned process is neither adopted nor PID-killed.
- Source integrity blocks stop dependent Hot operation. Ordinary feed
  unavailability preserves verified demand. Authentication/rate-limit stops
  remain durable; a new controller does not silently clear them.
- Saved Hot status and persistent warning/error incidents accompany operation.
  Read-only status inspection distinguishes a fresh active owner from a stale
  status file, lost controller, normal stop, and invalid evidence. It does not
  authenticate, request quotes or restart a process.
- Shutdown targets only owned source/identity/Hot handles. Damaged state or a
  source finalization failure does not prevent other owned cleanup or release
  the wrong owner's lease. Cleanup receipts state the measured ten-second gate.
  Native audit and two fresh replays run in a separate reporter with a sixty-
  second bound and unique per-invocation output; an earlier report cannot
  satisfy a new reporting invocation.
  The cleanup receipt is saved before reporting starts and survives an invalid
  result or reporter failure, which is recorded as `REPORT_INCOMPLETE`.

## Retained proof scope

The ordinary proof uses one synthetic HTTP CURRENT baseline and a saved dated
capture submitted through the verified daily publication API. It then exercises
the owned identity process, normal admission/publication, and native Hot
acquisition against one schema-v2 journal. Its native audit and two fresh
replays must pass. The complete paced three-HTTP source sequence is already
Windows-accepted in command 61; this short proof does not claim that sequence
or full feed reconciliation. Market time is shifted, while the process and
deadline measurements use actual elapsed time.

The separate recovery proof exits an actual owned worker after assembling a
response, retains the charged dispatch, waits fifteen seconds after confirmed
exit, and verifies one recovered acquisition plus a new future-slot acquisition.
Replacement startup deliberately crosses the launch job's first eligible slot.
The worker saves a bound, checksummed scheduling receipt after authentication
and response recovery. The launch slot is a lower bound; the first scheduled
slot is selected from the then-current clock, with the three-second startup
gate unchanged. Its raw native audit remains FAILED for the deliberate
outage and startup slots. The exact missing-slot set must match the recorded
fault through actual first scheduled slot, with zero unexplained gaps. The
first scheduled replacement slot itself must have a committed acquisition.
The short proof stops its owned producers and audits through that first fresh
replacement acquisition; it does not claim the remaining five-minute window.
The raw verdict and intentional slots are retained, without invented quotes
or retrospective fills. Two fresh replays of the resulting journal must agree.
Raw audit and gap diagnostics are saved before the gap assertion, including
when qualification fails. The original 86355fe Windows failure stays FAILED;
it is preserved with the original immutable packet and is not an acceptance.

Replay hashes are compared within each retained journal. Actual elapsed
acquisition times vary, so hashes from different runs/hosts need not agree.
Existing Uni/Focus run registrations and membership remain intact; these
synthetic checks do not claim a full session of three live poller processes.

## Remaining operating release work

Windows acceptance of this new packet, representative full-day performance
and provider capacity, independent outer operator/watchdog packaging,
deployment/rollback review and explicit settings/activation approval remain.
The proposed 390-feed/9,360-Hot ceilings are not adopted production settings.
This packet has no live launch or installer, and production Hot stays disabled.
Manual membership controls and the read-only Overlay follow closely.

`run.py status --state-root ABSOLUTE_PATH` inspects an existing saved controller
root read-only. It does not start a controller. The historical pause handoff and
original failed/interrupted development records remain in the repository;
the later delivery record supplies the current qualification status.
