# Daily Hot operating candidate

This release runs from its own short directory. Uni, Focus and independent
Health continue from installed main6b53ab1; watchlists stays on main e2ef6f6.
There is no source installer, branch switch or environment/package upgrade.
The source-pinned native Hot runtime and the accepted daily launcher/controller
are included, together with the Windows-qualified persistent membership window.

The new work generates dated operating reviews and separate start/status/window/
stop/rollback commands around those existing APIs. Resume retains the original
journal, state, catalog, configuration and charged budgets. The small backend
review-text change identifies remaining packaging/approval work accurately and
keeps full-session/provider capacity explicitly unqualified.

## Current acceptance and next action

Windows83 is accepted: all30 checks passed on Windows/Python3.12.13, including
actual synthetic CMD execution, and the CMD prompt returned. See
WINDOWS_ACCEPTANCE.json. Command84 has also returned REVIEW_READY on the actual
production computer, with exact clean baselines and matching dependencies; see
WINDOWS_DEPLOYMENT_ACCEPTANCE.json and WORKING_HANDOFF.md. The delivered
ZIP/source and original local result remain unchanged. The concrete Monday
one-symbol scope in ACTIVATION_REVIEW.md now needs a multi-symbol revision;
ACTIVATION_APPROVAL.json records NEEDS_MULTISYMBOL_SCOPE_REVISION. See
MULTISYMBOL_QUALIFICATION_PLAN.md. No unchanged
qualification or read-only review needs repeating solely for this acceptance.

## Delivered Windows qualification instructions

```cmd
powershell -NoProfile -Command "Expand-Archive -LiteralPath 'C:\Users\danla\Downloads\@@ZIP@@' -DestinationPath 'C:\Users\danla\hot83'"
```

```cmd
call "C:\Users\danla\hot83\p83\83_verify_operating_release.cmd"
```

83 runs30 focused offline checks and, on Windows, an actual synthetic CMD file
with spaces/parentheses in its paths. No password, provider, production journal,
source installation or live controller is used. It does not repeat the accepted
provider, pacing, recovery, capacity or GUI drills. Keep the final JSON and
actual returned CMD prompt. The original failed component-packet verdicts stay
preserved in the evidence; passing components are reused within their scopes.

After acceptance,84 reads installed Git baselines and dependency source/version
metadata. It changes no production source, journal, token or process:

```cmd
call "C:\Users\danla\hot83\p83\84_review_operating_release.cmd"
```

Do83 first and return its result. Review the concrete settings and activation
scope in RELEASE_REVIEW.md before a separate production activation approval.
Preparing this release or running83/84 does not activate Hot.

## Dated workflow after release/settings approval

Complete the ordinary daily r0/r1 publication and start Uni/Focus/Health in their
normal windows. Prepare and start Hot before the opening slot. This first
release requires fresh Hot password entry to finish before09:29:00 ET; aim for
09:20 rather than the boundary. The Nasdaq/collection window is09:30-16:00 ET,
end excluded. A fresh after-open Hot start is refused rather than backfilling
earlier slots. Manual resume of an already started daily session is separate.

The next commands describe the reviewed workflow; run them only for the actual
target date and after release approval. The Focus proposal path comes from that
morning's completed OV Focus build, not a guessed timestamp.

1. `hot_daily.cmd catalog --session-date YYYY-MM-DD` retrieves the two public
   Nasdaq directory inputs and saves them under `runs/daily_catalog_YYYYMMDD`.
   A durable receipt charges that two-download allowance before network work;
   a complete saved catalog is reused. An incomplete attempt is preserved and
   refused, not silently retried. This step uses no broker credential.
2. `hot_daily.cmd prepare --opening-proposal ABS --focus-proposal ABS --journal
   ABS --ecfg ABS` reads the already published production r0/r1 and creates a
   new `runs/review_YYYYMMDD_NN` directory. It never republishes opening history.
   The journal must be the installed market-data root's dated output journal.
   It prints the review SHA, explicit window/limits and the eventual start line.
3. Inspect `operating-summary.json` and `launch-review.json`. The prepared folder
   has START_HOT.cmd, MEMBERSHIP.cmd, STATUS.cmd, STOP_HOT.cmd and ROLLBACK_HOT.cmd.
   START_HOT requires the exact `--approved-review-sha256` and explicit
   `--activation-approved` arguments; it does not supply approval itself.
4. Run only the start line covered by the release/date/settings approval, in its
   own CMD window. Paste that password-prompting command by itself. The accepted
   private prompt/owned pipes are reused, with a recheck after typing. The new
   wrapper also refuses a fresh start whose pre-open boundary passed while typing.
5. Open MEMBERSHIP.cmd in its own window. It shows all Hot members and only
   Focus/Uni additions beyond opening r1. It is read-only; closing it stops only
   the display. STATUS.cmd reads outer cleanup/reporting and saved Hot health.

Reviews are immutable drafts. A revised unused preparation gets another draft
number; it does not reset any state or budget. If actual controller/native state
already exists, fresh preparation is refused. Preserve partial state for review.

## Stop, manual resume and rollback

STOP_HOT.cmd and ROLLBACK_HOT.cmd submit the same nonce/configuration-bound
cooperative stop to this invocation. Use STATUS.cmd to verify `EXIT_OBSERVED`
and `scope_empty_observed=true`; inspect the independent final report as well.
Healthy Uni/Focus/Health remain running. Stopping Hot preserves admitted
membership, source demand, the native journal, permits and original ledgers.
It does not restore an earlier roster. There is no automatic membership removal
or journal deletion in rollback. This matches the current additive phase.

For manual resume, use `hot_daily.cmd resume --review ABSOLUTE_OLD_REVIEW_PATH`.
The existing backend requires complete original ledgers, observed empty owned
scope, released previous owner/reporting, an unblocked provider and remaining
budgets. A new review/outer location is produced, with the exact original
configuration. Run its start only within the existing authorization or after
approval of a changed scope. The original three charged worker starts and
15-second replacement hold remain. No new catalog download, reset, PID adoption,
kill-by-name or automatic outer restart is added. The original session's16:00
stop remains; a new review does not extend it.

At close retain the independent owner report, native audit/replays and the usual
production closeout. Full-day capacity is evidence to collect during controlled
operation; this packet does not claim it from offline tests or the bounded trial.

## Monday preparation

Monday November2 uses EST(-05:00):09:30ET=14:30UTC and16:00ET=21:00UTC. The
offline check exercises those exact date/window conversions. Use the actual
Monday r0/r1, not Friday's trial copies. Friday's production closeout and
Monday's daily universe/r0 preparation remain separate operational work.

The last reported refresh token expires Saturday October31 at18:17ET, before
Monday. Check/renew authorization before the Monday startup; the existing
credential-horizon gate still applies. This status command prompts for the
encrypted-config password and must be pasted by itself:

```cmd
mb-schwab-auth --status
```
