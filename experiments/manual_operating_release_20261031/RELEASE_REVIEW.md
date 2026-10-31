# Proposed daily Nasdaq/manual operating release

Status: candidate, not installed or activated. Planning target for a first manual
session: November 3, subject to concrete dated review and approval. Monday,
November 2 remains assigned to the original approved p85 release. This proposal
does not change that approval or force an extra market-session delay.

Deployment: extract `@@ZIP@@` at C:\Users\danla\manual94; use p94 alongside the
existing repositories and sea-green environment. No source installation,
production checkout change or data migration is needed. The production journal
continues in the normal mb_market_data daily output path. Release-owned state,
catalogs, reviews and Hot process scopes live under this release's runs folder.

The read-only deployment review requires main/clean mb_market_data at
6b53ab1d12e4e1fdaf4deb1d70b717e13570358c and schwab_watchlists at
e2ef6f62856ba3226c41456b7779951aa8640cbf. Dependencies remain mb-tools 0.6.0,
schwabdev 4.0.0 and cryptography 49.0.0, with the original verified helper bytes.

| Setting | Proposed value |
|---|---|
| Profile / producer ownership | manual-identity-40-v1; Nasdaq source plus operator:masterbot |
| Nasdaq reasons / request lifetime | LUDP and M / regular close |
| Hot distinct/session allowance | 40 shared, nonrecycling |
| Focus additions / outside-Uni additions | 40 each, shared, nonrecycling |
| Opening Uni / Focus ceilings | 600 / 40; with additions at most 640 / 80 |
| Hot quote calls | 9,360, one batch of at most 40 symbols at each reserved slot |
| Identity lookup allowance | 120 total; 3 per symbol; 2-second spacing; 40 exact authorized symbols |
| Manual symbol admission | Opening Uni directly; other retained catalog symbols only after exact broker confirmation |
| Manual restrictions | Fixed operator may cap a symbol at Focus/Uni and clear their selected cap |
| Source retrieval | 2 directory files, at most 390 feed attempts, 60 seconds after completion |
| Publication throttle | At least 10 seconds between changed membership publications |
| Demotion grace / minimum residence | 60 / 120 seconds; restrictions cap immediately |
| Progress / credentials / replacement hold | 3 / 8 / 15 seconds |
| Cleanup / reporting | 10 / 60 seconds |
| Worker starts / owned invocations | Original maximum 3 each; retained on resume |
| Native collection | Interleaved reserved Hot slots; 0.75-second lateness bound; 300-second history periods |

Fresh startup is pre-open, around 09:20 ET; password acceptance before 09:29 ET.
The regular window is 09:30–16:00 Eastern. After the November 1 clock change,
that means EST (-05:00), 14:30–21:00 UTC. No live clock override, after-open fresh
start, catch-up or backfill is introduced.

Opening manual controls requires the active outer bound to that exact review and
the original live controller. Old windows are pinned to their invocation. Saved
manual status remains readable after stop without an owner, edit grant, provider
call or restart. Resume requires observed cleanup and original complete state;
new review/approval, original budgets/hold and future slots remain mandatory.

Rollback requests this Hot scope's cooperative stop and confirms exit/empty
scope. It preserves native membership and manual/source requests. Uni/Focus/
Health continue independently, including any already published additions.

The Windows backend qualification passed 71/71 with a forced 20/20 mixed burst,
two 40-symbol native cycles, owned collection/audit/replay and an actual GUI.
Its credentials/SDK/data were synthetic. The bounded prior real-provider daily
path and after-hours evidence retain their original scopes. Full-day and
representative sustained provider capacity are still unqualified. Source-history
gaps and the earlier unassigned I/O/ledger anomalies retain their diagnostics
and fail-closed behavior. Original failed qualification verdicts remain preserved.

Windows94 qualification and actual-computer read-only review95 are now complete:
48/48 PASS, three actual synthetic CMD cases PASS, and REVIEW_READY for the exact
inventory and policy. See WINDOWS_ACCEPTANCE.json and
WINDOWS_DEPLOYMENT_ACCEPTANCE.json. No unchanged qualification repeat is due.

The remaining operating decision is approval of this exact manual release,
settings and a concrete dated activation. The planning date in RELEASE.json is
a proposal, not permission to start. Monday's separate p85 approval remains.
Public p94 publication is explicitly approved in PUBLICATION_APPROVAL.json.
That publication approval does not authorize a manual production session.
