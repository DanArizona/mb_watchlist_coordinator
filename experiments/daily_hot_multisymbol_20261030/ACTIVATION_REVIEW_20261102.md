# Monday November 2: 40-symbol Hot activation proposal

Status: **APPROVED FOR MONDAY NOVEMBER 2; OPERATION NOT STARTED.**

The user explicitly approved this release/settings scope and retained-state manual
resume in this chat. [ACTIVATION_APPROVAL_20261102.json](ACTIVATION_APPROVAL_20261102.json)
records the exact approval, source/policy pins and original proposal digest.

Command86 returned REVIEW_READY on MasterBot with the actual CMD prompt. Its
source inventory, clean installed repositories, dependency versions and helper
fingerprints match the qualified release. Windows88 accepted the offline multi-40
qualification, including the reassessed owned burst and 996,300-observation
synthetic retained history. Original Windows85 and Windows87 FAILED verdicts
remain preserved. No unchanged qualification needs repeating.

## Exact release

- Run from `C:\Users\danla\hot85\p85`; p88 supplied qualification only.
- Artifact: `hot_multisymbol_20261031_e7cb9b6.zip`.
- Artifact SHA-256: `e8008e90b6ec61671b4ea029ed3168ad4b4cd55830aa7d10b075a76808076fe6`.
- Source inventory: `0c5f9d7a2dfcdd72ffc9d3d07b7ea2e4b9528139a948496e4fd921476fdf6ffe`.
- Coordinator source: `e7cb9b6fa786170455dbfe7c3226d8b18227487e`;
  included native source: `d37d2c37e3ac9cc2c860d0a2313a1526e30fd23e`.
- Profile: `multi-40-v1`; policy SHA-256:
  `e3e7d2449214928e7094735ba1f5cbed641dba37c61b0ea085b86e827f5944b6`.
- Installed clean main baselines: market data `6b53ab1d12e4e1fdaf4deb1d70b717e13570358c`,
  watchlists `e2ef6f62856ba3226c41456b7779951aa8640cbf`.
- sea-green Python 3.12.13, mb-tools 0.6.0, schwabdev 4.0.0,
  cryptography 49.0.0 and the reviewed credential-helper source.

The extracted release runs beside the installed repositories. Approval covers
its use of the existing encrypted configuration and normal shared SDK token
refresh. Installation, environment upgrades and main-branch merges are outside
this proposal.

## Operation being approved

| Item | Fixed Monday scope |
| --- | --- |
| Session | November 2, 2026, 09:30–16:00 EST (`-05:00`), end excluded; 14:30–21:00 UTC |
| Startup | Target 09:20 ET, after ordinary OV/r1 preparation and Uni/Focus/Health startup readiness; password must finish before 09:29 ET |
| Admission | Nasdaq LUDP/M events through the existing exact catalog/broker identity, admission, nesting and restriction checks |
| Hot membership | At most 40 distinct authorized symbols over the session and 40 active Hot members |
| Uni/Focus additions | At most 40 outside opening r1; add eligible Hot symbols to Uni and Focus as needed |
| Monday opening | Published r0 Uni 584, Hot empty; valid Monday Focus r1 up to 40, with the same Uni |
| Resulting bounds | Monday Uni at most 624, Focus at most 80, Hot at most 40; the general release guard permits opening Uni up to 600 |
| Cadence | Uni `:00/:30`; Focus `:10/:20/:40/:50`; Hot 24 reserved even-second slots/minute, batch size 400 |
| Call ceilings | Hot 9,360; identity 120 total and at most 3 per symbol; identity starts at least 2 seconds apart |
| Public source | Up to 2 directory retrievals for Monday and 390 feed attempts; feed starts at least 60 seconds after the preceding completion |
| Publication | Group queued additions with a ten-second minimum interval from the last acknowledged publication; pending ACK completion and reductions bypass batching |
| Deadlines | Broker request/progress 3 seconds; credentials 8; replacement hold 15; cleanup 10; final reporting 60; dispatch lateness 0.75 |
| Starts and resume | At most 3 cumulatively charged worker starts across replacements and manual resume; no automatic outer restart |
| Storage verification | All membership and active five-minute quote-period data checked during operation; all Hot stored values, native coverage and event order checked after stop |

The normal production schema-v2 journal is:
`C:\Users\danla\Documents\github\mb_market_data\output\quote_observation_journal_v2_api_opening_2026-11-02\2026-11-02.sqlite3`.
This operation publishes membership and writes Hot quote evidence there. Empty
Hot membership generates no Hot quote calls. There is no forced live roster,
fresh after-open start or catch-up of past slots. Quiet or ineligible feed
activity may produce fewer admissions than the ceiling.

The accepted opening r0 content SHA-256 is
`e19ce104dc58501310ea456abdfd9f72d0a5e21dd5b9c5c730775c207960dd47`.
Monday's actual Focus r1 path/hash and same-date catalog will be supplied during
ordinary preparation. Within this fixed release/date/settings scope, that does
not require another permission round. The launcher still binds the exact
resulting review digest and rechecks source, dependencies and inputs before and
after password entry. Changed scope or a failed check requires review.

## Startup, observation and closeout

1. Finish Monday's normal credential-status check, API overnight-volume build,
   Focus r1 publication and opening audit/replay. Use the already prepared r0.
2. Start normal Uni/Focus/Health in their independent windows. Check their startup
   readiness before starting Hot; check committed opening slots after 09:30.
3. Acquire Monday's Hot catalog with the existing `hot_daily.cmd catalog` entry,
   then generate the dated review and commands with `hot_daily.cmd prepare`.
   These bind actual inputs and produce START_HOT, STATUS, MEMBERSHIP, STOP_HOT
   and ROLLBACK_HOT commands. Preparation creates no controller or membership.
4. Start the approved review in its Hot window, aiming for 09:20 ET and completing
   the password before 09:29. Open the persistent MEMBERSHIP window. Its panels
   show the full current Hot list and current Focus/Uni additions beyond r1;
   source, collection, recovery and stale-read state remain visible.
5. Observe the opening and later admissions/collection. Review saved incidents.
   At close or an operator stop, confirm owned cleanup and final native audit,
   full Hot value integrity and event-order results. Complete the normal
   Uni/Focus session closeout separately.

The reported refresh expiry is November 6, covering Monday. Normal credential
horizon checks remain mandatory. The weekday catalog is obtained on Monday,
not from a weekend download or an older-date cache.

## Stop, rollback and manual resume

STOP_HOT and ROLLBACK_HOT address only the bound Hot owned scope. Verify
`EXIT_OBSERVED` and `scope_empty_observed=true`, then inspect final reporting.
Healthy Uni/Focus/Health continue. Preserve source/request state, membership,
journal, period ledgers and charged budgets. A stop does not withdraw requests
or restore the opening roster; admitted additions may continue in Uni/Focus.

Approval includes operator-chosen manual resume during the same Monday window,
using the original configuration, catalog, state and budgets after confirmed
cleanup and release of the previous owner/reporter. The original full
15-second replacement hold and cumulative three-start ceiling remain. A stored
provider stop stays latched. There is no reset or budget renewal.

## Evidence and limits

Accepted Windows88 evidence includes 40 paced identity confirmations, source
CURRENT/history/fresh CURRENT, concurrent Uni/Focus writers, complete 40-symbol
collection on both sides of rollover, successful owned cleanup, and 996,300
synthetic observations within the original preparation/dispatch/report gates.
The actual October 30 bounded daily path admitted ITOC and collected 60 real Hot
quotes. Existing provider, GUI, recovery and launch evidence retains its scope.

This supplies forced offline load and retained-history qualification. A full
elapsed session and representative live 40-symbol provider performance remain
to be observed during controlled operation. Intermediate feed mutations and
older unknown carryovers are not proven complete. No claim of detecting every
halt between feed snapshots is made.

CANDIDATE_NOT_ACTIVATED, PROPOSED_NOT_ADOPTED and hot_enabled=false are labels
in the frozen proposal. Trusted per-invocation approval is recorded by the public
launcher; policy source is not edited to mark approval. The inherited
provider_collector_driver_qualification_pending warning remains in the sealed
bytes; accepted bounded daily-path evidence and the remaining full-session
limits are stated separately.

## Approval granted

The user approved this frozen p85 release, the multi-40 settings and Monday's
first controlled production Hot session, including manual resume within the
same documented limits. The exact approval is recorded separately, along with
the SHA-256 of this proposal before its approval annotation.

This specific production authorization supplements the standing GitHub
publication authorization. Actual valid Monday r1/catalog preparation and bound
resume reviews within this fixed scope do not require another chat approval.
Normal source/dependency/input/ownership/budget/time checks remain mandatory.
The approved operation has not started. Later dates or wider/changed scope are
outside this approval.
