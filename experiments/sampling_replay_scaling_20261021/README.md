# Coordinator replay-value scaling qualification

The first scaling increment is already accepted on MasterBot Windows. This
second increment compares against that accepted runtime (local abeeeb672,
GitHub 6ffa1cd5), rather than the much older original baseline.

## Change

Profiling a 3,001-event validated read identified repeated construction and
lexical validation of unchanged 531-member hierarchies as the dominant cost.
The reducer now copies/validates a plain immutable baseline once per nonempty
replay, then reuses an existing membership only if all three sets are identical.
Changed memberships still use the ordinary constructor and nesting checks.
Baseline or active-request string subclasses disable reuse and retain ordinary
validation. The policy reducer still evaluates every receipt and timer; it can
reuse identical output values through a private replay-local constructor callback.
An unused intermediate retained membership is no longer constructed when the
policy reducer supplies the result.

Every event hash, chain, duplicate-command check, admission outcome, request,
restriction, activation, expiry, grace and residence transition is still replayed.
There is no persistent cache of request states, event validity or database reads,
no SQLite schema/receipt payload change, and no publication/scheduling change.
The only retained predicate cache remains the already accepted bounded string LRU.

## Offline qualification

The 171 focused checks include six additional checks for early corruption and
rehashed false admission after quiet histories, future activation/expiry/residence,
mutable baseline tokens, forged nesting and isolation from a previously returned
membership object. Existing Windows-safe connection cleanup checks stay enabled.

Two logical workloads each compare 301/1,001/3,001 events against the accepted
first increment, using three measurements per size in fresh Python processes:
withdrawn Hot after source/cap/expiry/cancellation/demotion transitions; and
steady 40-symbol Hot demand following those same transitions. All complete
request-state digests, decisions, final memberships and cold publication reopens
must match. Only the changed source runs the focused suite. Network is denied.
Logical tick extension is not elapsed market operation or provider capacity.

## Local result

All 171 affected checks and both complete paired workloads PASS locally.
Three-call mean native idle cycles (milliseconds) against the Windows-accepted
first increment:

| Workload | Events | Accepted first increment | Replay-value reuse |
| --- | ---: | ---: | ---: |
| withdrawn_hot | 301 | 116.721 | 34.579 |
| withdrawn_hot | 1,001 | 329.463 | 74.719 |
| withdrawn_hot | 3,001 | 1102.109 | 176.433 |
| steady_hot | 301 | 127.151 | 46.440 |
| steady_hot | 1,001 | 432.245 | 96.054 |
| steady_hot | 3,001 | 1246.898 | 243.103 |

All six complete replay digests, decisions, memberships and cold reopens match.
The original saved live 11-request ledger also reconstructs the exact accepted
state digest e7407c99d31d7dba6f7992daea6b97752147d3700a7fbe9384e35c65d2ae4693
under both sources; original bytes are unchanged. Timings are observations,
not pass thresholds or Windows/provider-capacity claims. Records are in
validation/local_qualification.json and retained_live_requests_comparison.json.

## Windows handoff

Extract the complete uniquely named coordinator_replay_scaling ZIP beneath
mb_market_data/output and run 27_verify_coordinator_replay_scaling.cmd from
sea-green CMD. No password, API, installation, production journal or live poller.
The package verifies its inventory and pins both old and changed source.
Preserve the final saved report path and actual CMD prompt return.

Native Windows qualification of this second increment is now ACCEPTED from
the complete operator transcript: 171 checks in 5.114s, both paired workloads,
all six complete replay digests/decisions/memberships/cold reopens matching,
and actual CMD prompt return. No unchanged qualification rerun is needed.
The accepted packages and prior live trials remain unchanged. Production cadence
and Hot-disabled policy remain unchanged.

## Native Windows result

| Workload | Events | Accepted first increment (ms) | Replay-value reuse (ms) |
| --- | ---: | ---: | ---: |
| withdrawn_hot | 301 | 89.424 | 27.976 |
| withdrawn_hot | 1,001 | 266.401 | 54.219 |
| withdrawn_hot | 3,001 | 828.474 | 131.657 |
| steady_hot | 301 | 98.390 | 32.899 |
| steady_hot | 1,001 | 309.284 | 69.167 |
| steady_hot | 3,001 | 992.792 | 201.429 |

These are three-call means for synthetic logical histories, not elapsed market
operation or provider capacity. All supplied fields and the on-host report path
are retained in validation/windows_qualification.json. The original uploaded
console transcript is identified there; the saved report file itself was not
uploaded. The delivered ZIP is unchanged.

## Limits

Every read still reconstructs history; cost remains proportional to history and
active work. This removes repeated membership validation, without claiming
constant-cost processing or a durable incremental replay/checkpoint design.
Longer provider operation, startup/outage reconciliation and production adoption
remain separate work.
