# Daily Nasdaq + manual operating release — candidate

This delivery wraps the accepted p93 manual/Nasdaq controller in dated review,
startup, GUI/status, stop and resume commands. It is extracted alongside the
installed production repositories. It does not install code or activate Hot.
Monday's approved p85 release and all p85/p92/p93 packet bytes remain unchanged.
Only daily_operator.py changes at runtime; controller, identity, membership,
collector, GUI, cadence and recovery implementations are retained.

## October 31 Windows acceptance

Commands 94 and 95 are complete. The operator supplied the full console, final
reports and actual returned CMD prompts. Windows94 passed 48/48 in 27.969 seconds
(28.250 seconds overall), with zero failures, errors or skips. All three actual
synthetic CMD cases passed: controls, manual-status and resume, preserving their
exact arguments. Windows95 returned REVIEW_READY against the matching inventory,
clean production main baselines and verified dependency versions/helper bytes.

See WINDOWS_ACCEPTANCE.json, WINDOWS_DEPLOYMENT_ACCEPTANCE.json and
WINDOWS_CONSOLE.txt. The original Windows files were not independently accessed.
No delivered source, settings, provider/GUI/controller behavior or frozen packet
changed for acceptance. No qualification repeat is due.

The concrete manual release is ready for dated activation review; no manual
production session is approved or inferred. Monday p85 keeps its existing
approval. The operator explicitly approved publication of p94 source, tests,
documentation, proposed settings and acceptance records to the existing
experiment/manual-membership-20261031 branch. See PUBLICATION_APPROVAL.json;
GitHub confirmation is recorded separately after publication.

## Qualify and review on Windows

Download `@@ZIP@@` and extract in the sea-green CMD window:

```cmd
powershell -NoProfile -Command "Expand-Archive -LiteralPath 'C:\Users\danla\Downloads\@@ZIP@@' -DestinationPath 'C:\Users\danla\manual94'"
```

Run separately:

```cmd
call "C:\Users\danla\manual94\p94\94_verify_manual_operating_release.cmd"
```

This runs 48 focused checks against synthetic journals/repositories/credentials.
Windows additionally executes controls/status/resume command files against a
private argument-printing entry. No GUI, provider, password or production access
is used. Allow about 30 seconds. Existing long source/history/recovery proofs
and the accepted GUI preview are not repeated. Paste the final JSON and returned
CMD prompt.

After that passes, the next command performs the actual computer's read-only
deployment review, with no password, vault, provider call or production change:

```cmd
call "C:\Users\danla\manual94\p94\95_review_manual_operating_release.cmd"
```

It checks the exact installed main commits, tracked-clean repositories, dependency
versions/helper bytes, delivered source and matching Windows marker. Read the
result with RELEASE_REVIEW.md before approving the concrete release/settings and
a dated manual session. The provisional planning target is November 3; this is
not a schedule or authorization, and does not replace Monday's p85 approval.

## Daily run sheet after concrete activation approval

For the preparation verbs below, use the full entry prefix
`call "C:\Users\danla\manual94\p94\manual_daily.cmd"` followed by the listed verb
and its reviewed arguments. Generated review-folder commands are already bound
to their exact paths and do not need that prefix.

1. Complete ordinary daily universe, API overnight volume and Focus selection;
   publish/audit opening r0/r1 in the normal production schema-v2 journal. Keep
   Uni, Focus and Health managed in their existing independent windows.
2. On the selected trading date, use `manual_daily.cmd catalog --session-date
   YYYY-MM-DD` to retain the date's two public directory files. The original
   durable two-download charge remains; a partial attempt cannot be reset/retried.
3. Before 09:29 ET, use `manual_daily.cmd prepare --opening-proposal ...
   --focus-proposal ... --journal ... --ecfg ...` with the exact dated inputs.
   Preparation writes only a review folder and commands, not opening membership,
   a controller or a password prompt. Review operating-summary.json and the
   dated digest. Late fresh preparation/start is refused; no backfill is added.
4. Start the generated START_HOT.cmd around 09:20 ET, supplying its approved
   review digest and explicit activation argument. The encrypted-config password
   is entered only in that command's own window and must be accepted before
   09:29 ET. Do not paste later commands into a pending password prompt.
5. After the controller initializes, open MEMBERSHIP.cmd for the persistent
   lists and MANUAL_CONTROLS.cmd for edits. Submit manual requests during the
   regular 09:30–16:00 ET session. Pre-open membership is waiting; pre-open
   manual submissions are blocked rather than silently scheduled.
6. Use STATUS.cmd to inspect the selected outer/controller and MANUAL_STATUS.cmd
   for durable request/effective feedback. The latter remains read-only after
   stop and reports collection/controller status separately from retained Hot
   membership. A missing/corrupt read is unavailable, not verified empty.
7. STOP_HOT.cmd and ROLLBACK_HOT.cmd request only this owned outer's cooperative
   stop. Keep checking STATUS until cleanup is EXIT_OBSERVED and the owned scope
   is empty. Uni/Focus/Health continue; original memberships, manual receipts,
   budgets, journals and diagnostics are retained.

All paths passed to preparation must be ordinary CMD-safe paths. The generated
commands pin the current Python, delivered entry and exact review, including
spaces/parentheses; no conda change, git update or extra environment is required.

## Manual actions and feedback

- Opening-Uni Focus/Hot requests need no extra broker lookup. Other retained
  catalog symbols queue for exact shared broker confirmation before admission.
  The GUI performs no provider call and never publishes membership directly.
- Requested/pending/effective/blocked/withdrawn feedback is durable. An accepted
  request can wait for the original ten-second publication throttle or policy
  timers; requested membership and current effective membership remain separate.
- Withdraw a selected own pending request to cancel before admission. A lookup
  already in flight stays charged; cancellation prevents later admission. To
  lower an admitted own Hot request, use Demote own to Focus/Uni. Nasdaq demand
  can keep membership higher; a privileged cap explicitly overrides ordinary
  sources. Clearing a cap can restore existing demand.
- The shared 40-symbol/session allowances do not recycle on withdrawal or
  restriction. Identity permits, exact-symbol reuse, per-symbol limits, unknown
  outcomes and provider stops remain the accepted p93 behavior.
- Close controls stops only its window/executor. It does not stop the daily
  controller or withdraw demand. Stop the controller with its generated stop
  command. Once stopped/stale/replaced, the old window cannot submit changes.

## Manual controller resume

Use PREPARE_RESUME.cmd from the current review only after the old outer and owned
roles have actually exited and reporting has released ownership. It checks the
original complete state, catalog, memberships, native periods, manual receipts,
provider-stop latch and remaining invocation/worker budgets. It writes a new
review folder and commands; it never resets state or starts anything.

Start that newly approved resume review using its own digest. The original
configuration, identity charges, distinct-symbol allowances and worker starts
remain. The original full 15-second replacement hold applies, followed by future
slots only. Reopen MANUAL_CONTROLS from the new folder; the old window stays
fenced and an ended outer's controls command cannot attach to a new outer.

If a provider stop is latched, original evidence is missing/corrupt, budgets are
exhausted or the session has ended, resume is refused. Preserve the files for
review; do not reset, copy over or reuse a partial state root.

## Scope

The p93 71/71 Windows identity/controller/native/GUI qualification and prior
public-launch/ownership/recovery evidence are retained. This release's new
qualification covers operating composition and commands. It does not claim new
real-provider, 40-symbol sustained or full-day capacity evidence. The two known
source-history gaps remain explicit. Manual production activation requires its
own concrete reviewed release/settings/date; no such activation occurs here.
