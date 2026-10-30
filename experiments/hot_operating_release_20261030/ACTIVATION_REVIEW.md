# Monday November 2 production Hot activation review

Status: **NEEDS MULTI-SYMBOL SCOPE REVISION; NOT ACTIVATED.**

The operator questioned the one-symbol limit and the risk of consuming a market
day per expansion while natural halt traffic remains sparse. The proposal below
is retained as the reviewed one-symbol candidate, not the next approval request.
See MULTISYMBOL_QUALIFICATION_PLAN.md. Qualification of the existing artifact
remains accepted within its scope; no wider capacity or activation is inferred.

Windows83 passed all 30 checks, including actual CMD execution. Command84
returned REVIEW_READY on MasterBot, with clean production repositories and
matching dependency versions and helper source. Both actual CMD prompts
returned. The evidence consists of complete operator-supplied console/JSON;
the Windows files have not been independently read. See WINDOWS_ACCEPTANCE.json
and WINDOWS_DEPLOYMENT_ACCEPTANCE.json. No unchanged qualification needs repeating.

## Exact release and reviewed deployment

- Artifact: hot_operating_release_20261030_b3205e0.zip.
- SHA256:95e0ed4799d589b0fd641cb0d1e8c5edbf49977d0add0a5814aba57386c083f6.
- Windows root: C:\Users\danla\hot83\p83.
- Inventory:5fe8a86b2fa502a4ebb6e13b49d30e9063efd4b46b477299311be9d88944c43a.
- Coordinator source:b3205e0127b0bb9c1d7b97117991a4985cf782bb.
- Included native source:5552c5db43351d1a9ae8d376196cc99ba9c7f05d.
- Installed mb_market_data remains clean main6b53ab1d12e4e1fdaf4deb1d70b717e13570358c.
- Installed schwab_watchlists remains clean main e2ef6f62856ba3226c41456b7779951aa8640cbf.
- sea-green Python3.12.13; mb-tools0.6.0, schwabdev4.0.0,
  cryptography49.0.0, exact reviewed helper source checks.

The extracted release runs beside those installed repositories. It uses the
existing encrypted configuration and SDK token store; normal SDK token refresh
can occur. No repository merge, source installation or environment upgrade is
part of this approval.

## Proposed approval scope

| Item | Proposed Monday operation |
| --- | --- |
| Date and journal | November2,2026; the normal published production r0/r1 and shared schema-v2 production journal |
| State and commands | Dated state/catalog/review folders under the frozen p83 runs directory; generated bound start, status, membership, stop and rollback commands |
| Admission | First eligible exact broker-confirmed Nasdaq LUDP or M candidate, using the accepted original admission and restriction checks |
| Membership | At most one active Hot symbol and one distinct admitted symbol for the whole session; add to Uni and Focus if needed; requests last to regular close |
| Opening capacity | Uni<=600, Focus<=40, Hot empty; up to601/41/1 after admission |
| Collection |09:30-16:00ET, end excluded; Monday uses EST(-05:00),14:30-21:00UTC |
| Fresh startup | Target09:20ET; password must finish before09:29ET; no fresh after-open startup or past-slot catch-up |
| Cadence | Independent Uni:00/:30 and Focus:10/:20/:40/:50; Hot reserved even seconds,24opportunities/minute |
| Call caps | Hot9360, identity3, directory2, feed390; feed interval>=60s after completion; no Hot quote calls for empty membership |
| Timing and recovery | Original progress/request3s, authentication8s, full replacement hold15s, cleanup10s, report60s, dispatch lateness0.75s; at most3charged worker starts |
| Manual resume | Same Monday session/window, configuration, journal, state, catalog and charged budgets; previous owned scope empty and owner/report released; provider stop remains latched |
| Status | Persistent all-Hot list and Focus/Uni additions beyond openingr1; saved source/recovery/collection status and warnings |
| Stop/rollback | Cooperatively stop only the bound Hot scope and verify empty scope/report completion; retain membership, requests, journal and budgets; healthy Uni/Focus/Health continue |

There is no normal intraday removal/demotion interface in this release. A stop
does not withdraw the source request or restore the opening roster. Admitted
symbols can therefore continue in Uni/Focus after Hot collection stops.

Approval covers the release/date/settings above and manual retained-state resume
within those original limits. It is not an automatic outer-restart permission
or approval for later dates, widened limits or changed source/dependencies.
The actual valid Monday r1 path/hash can be supplied during ordinary preparation
without another permission round; the backend still binds the exact generated
review digest at launch and rechecks the inputs before and after password entry.

## Remaining ordinary preparation and evidence

Friday production closeout is accepted:780Uni/1560Focus acquisitions,
485940quote observations, native audit and completed replay, zero missing slots
or row mismatches and no recorded health incidents. See
validation/production_20261030_closeout.json. Monday universe/r0 preparation is
also accepted,584/0/0, using Friday's qualifying same-ET-date post-close snapshot;
publication, audit and replay passed. See validation/opening_r0_20261102_acceptance.json.
Monday's morning OV build, r1 publication, opening audit and normal poller setup use actual dated
inputs, within the capacity above. Credential validity must cover the session;
the last reported refresh expiry is Saturday October31 at18:17ET, before Monday.

Actual October30 bounded daily composition passed with real Nasdaq ITOC
admission and60Hot quotes. Representative history/ownership, recovery, paced
source, Windows read-sharing, launch and membership GUI evidence remain accepted
within their scopes. Full-session/provider capacity is still unqualified; the
first controlled operating session is intended to gather that evidence, followed
by native audit/replays. A quiet feed or an ineligible/capped candidate may yield
no admission. Known source history gaps remain explicit.

The frozen proposal includes PROPOSED_NOT_ADOPTED/hot_enabled=false and
production_activation_approved=false labels. Those describe the unapproved
candidate; the accepted public launcher records per-invocation approval rather
than editing the sealed proposal. The inherited
provider_collector_driver_qualification_pending warning is retained in those
frozen policy bytes. The accepted bounded daily-composition evidence closes that
bounded observation; the warning is not a new required rerun or a full-day
capacity claim. The two source-history limitations remain applicable.

The user's standing authorization permits GitHub publication but expressly
excludes production changes. This new operation writes membership and Hot quote
evidence to the shared production journal, so explicit activation approval is
requested for this concrete scope. The earlier isolated Friday trial approval
was consumed by that completed invocation. Publication of this review does not
constitute activation approval.
