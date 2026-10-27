# Cadence source installation and fresh-session trial — proposed October 27

Status: Windows qualification and read-only deployment review accepted. Production/main approval is still pending. Commands below are prepared for review; installation waits for that approval and the stated closeout conditions.

## Reviewed change

- Existing local production `main`: `a082f544112643b4e5f459d15c67f60d0a1ef83d`; no tracked edits; all 12 source targets match.
- Qualified candidate: `6b53ab1d12e4e1fdaf4deb1d70b717e13570358c` from `experiment/hot-operating-cleanup-fix-20261027`.
- Corrected command57 Windows: 233/233 PASS, zero skips/errors/failures and actual CMD return. Command59 confirmed `windows_qualified=true` and returned to CMD.
- Install updates local production `main` with a fast-forward. The command performs no public `origin/main` push.
- Existing journals/evidence and unrelated untracked files are retained. The install writes a receipt under `output\hot_operating_deployment`.

| Channel | Current seconds | Proposed October28 seconds | Expected full-session slots |
| --- | --- | --- | --- |
| Uni | :00, :30 | :00, :30 | 780 |
| Focus | :05, :20, :35, :50 | :10, :20, :40, :50 | 1,560 |
| Hot | Disabled | Disabled | 0 |

## Proposed approval scope

After October27 normal closeout and Health/watchdog shutdown, install the exact candidate into local production main. On October28, after the normal fresh dated hierarchy/OV/Focus preparation and verification, run both Uni/Focus pollers and current-source Health with `interleaved-v1`. Include the documented after-close source revert and next-fresh-session legacy fallback if needed. Proposed daily Hot values remain unadopted; the daily Hot driver is still separate implementation work.

The user's standing authorization covers experiment/checkpoint commits but expressly requires separate explicit approval for main-branch and production changes. No production operation has been performed by preparation or review.

## After-close installation

1. Obtain October27 final health, complete native full-session audit and replay. Preserve any diagnostic findings.
2. Stop the dated Health monitor/watchdog and confirm both exit and the actual CMD prompt. Pollers must have finished; leave healthy channels running until their normal end.
3. After 16:00 ET and explicit approval, run the following alone in sea-green. The installer rechecks Windows qualification, main/HEAD, tracked/source targets and process idleness. Unknown process inventory or an active poller/Health blocks it.

```bat
python -I -B "C:\Users\danla\Documents\github\mb_market_data\output\hot_operating_fix_20261027_6b53ab\run.py" install --market-data-root "C:\Users\danla\Documents\github\mb_market_data" --production-change-approved
```

4. Retain the complete result, deployment receipt path/content and actual CMD prompt. Receipt must show `INSTALLED`, before `a082f544112643b4e5f459d15c67f60d0a1ef83d`, after `6b53ab1d12e4e1fdaf4deb1d70b717e13570358c`, Hot false and journals unchanged. Source hashes are checked after the fast-forward.

## October28 fresh-session startup

Complete the normal fresh October27 post-close universe build/October28 r0 publication, then October28 credential preflight, full-Uni API OV after09:00 ET, fresh Focus/r1 publication, native audit and complete replay. Actual r0/r1 results determine membership counts; no tomorrow roster is inferred here. Do not change the October27 journal's cadence.

Run each poller in its normal separate sea-green CMD window after that preparation. Each command prompts for the encrypted-config password, so paste and complete it alone.

`prod-poll-uni`:

```bat
python "C:\Users\danla\Documents\github\mb_market_data\probes\probe_universe_quote_watch.py" --watchlist-kind uni --batch-size 400 --start-at "2026-10-28T09:30:00-04:00" --stop-at "2026-10-28T16:00:00-04:00" --journal-root "C:\Users\danla\Documents\github\mb_market_data\output\quote_observation_journal_v2_api_opening_2026-10-28" --journal-schema-version 2 --cadence-profile interleaved-v1 --ecfg "C:\Users\danla\MBV\secure_schwabdev.ecfg"
```

`prod-poll-focus`:

```bat
python "C:\Users\danla\Documents\github\mb_market_data\probes\probe_universe_quote_watch.py" --watchlist-kind focus --batch-size 400 --start-at "2026-10-28T09:30:00-04:00" --stop-at "2026-10-28T16:00:00-04:00" --journal-root "C:\Users\danla\Documents\github\mb_market_data\output\quote_observation_journal_v2_api_opening_2026-10-28" --journal-schema-version 2 --cadence-profile interleaved-v1 --ecfg "C:\Users\danla\MBV\secure_schwabdev.ecfg"
```

After both pollers register, start `prod-health` from the current installed source:

```bat
python "C:\Users\danla\Documents\github\mb_market_data\probes\polling_health.py" monitor --market-data-root "C:\Users\danla\Documents\github\mb_market_data" --session-date 2026-10-28 --supervise --cadence-profile interleaved-v1
```

Check fresh opening commits. At close, native audit and complete replay must account for the full Uni780/Focus1560 scheduled outcomes without unexplained missing slots or row mismatches; preserve all quote/invalid statuses as observed. There is no Hot acquisition in this trial. Use the same profile on any same-session restart and the complete current-source commands printed by Health. Old output-folder restart packets embed older Health code and must not be used for this trial.

## Documented rollback included in the proposed scope

During a running interleaved session, keep that session's profile and use its current-source same-profile recovery. Do not rewrite run metadata or switch cadence mid-session.

At the next fresh session boundary, the original commands without `--cadence-profile` select the legacy default, including Focus :05/:20/:35/:50. This fallback is available on the candidate source.

If source rollback is needed after close, after poller/Health shutdown and within the approved contingency scope, the guarded command is:

```bat
python -I -B "C:\Users\danla\Documents\github\mb_market_data\output\hot_operating_fix_20261027_6b53ab\run.py" rollback --market-data-root "C:\Users\danla\Documents\github\mb_market_data" --production-change-approved
```

This uses a new Git revert commit, preserves journals/evidence/unrelated untracked files, checks restored source hashes and writes a `ROLLED_BACK` receipt. It requires the exact installed candidate HEAD and idle Windows processes; later source changes require a newly reviewed rollback. The resulting commit is recorded for future updates. There is no reset/hard, force or history rewrite.

## Evidence and remaining implementation

- [Command59 review](../validation/command59_20261027_REVIEW_ACCEPTED.json)
- [Corrected Windows qualification](../validation/command57_20261027_WINDOWS_ACCEPTED.json)
- [Original retained Windows failure](../validation/command57_20261027_WINDOWS_FAILED.json)

Daily automatic Nasdaq/Hot source/identity/admission/collector/controller ownership, health, stop/recovery and adoption integration remains the next implementation slice. That work and manual membership may proceed alongside cadence observation. The agreed read-only Overlay remains in scope. Accepted bounded live profiles need no unchanged repeat.
