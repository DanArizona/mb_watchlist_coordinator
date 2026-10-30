# Daily Hot public launch candidate — October 29

This adds the public daily launch composition around the accepted controller.
The next operator action is **72_verify_daily_hot_launch.cmd**, an offline check.
It requests no password, contacts no service, and changes no production state.
Windows 71 remains accepted: 26/26, including native read sharing and the full
CURRENT/history/fresh-CURRENT proof. Its record is included. This check does not
repeat that paced proof or the accepted recovery and full-size history drills.

The new checks cover approval before the password prompt, changed source,
dependencies, proposal bytes, catalog or dated window, secret cleanup, fixed
role dispatch, and manual resume preflight. Some dispatch assertions use trusted
Python mocks; an actual isolated process checks refusal without an owner. These
checks do not newly qualify an authenticated public launch or provider capacity.
Provide the final JSON and actual returned CMD prompt.

## Candidate operator workflow

`daily_hot.cmd` exposes `catalog`, `review`, `run`, `outer-status`, `hot-status`
and `stop`. The live entry is implemented, but live operation is **not approved**.
Only the offline verification command should be run for this delivery.

1. After that day's r0/r1 publication, acquire a separate `daily_catalog_...`
   directory with `catalog --catalog-root ABSOLUTE_PATH`. This makes at most two
   public directory requests, without broker authentication or retries. The
   saved catalog must have been acquired on the target ET date. It supplements
   the daily Uni screening evidence; it does not replace that screening.
2. Use `review` with explicit `--opening-proposal`, `--focus-proposal`, `--journal`,
   `--catalog-root`, `--state-root`, `--ecfg`, `--outer-root` and `--output` paths.
   State must be a separate `daily_hot_...` directory; each outer invocation gets
   a new `daily_outer_...` directory. Put mutable files beneath the delivery's
   `runs` directory or outside the delivered source tree. Use `fresh` for the
   first invocation. Review reads source, installed dependencies and saved
   inputs; it never reads the encrypted configuration or starts a client.
3. Review the resulting source/configuration/policy digests, explicit settings,
   paths, source-history limitations, deployment and rollback. Obtain approval
   for that concrete release and invocation after the remaining provider work.
4. Only then use `run --review PATH --approved-review-sha256 DIGEST
   --activation-approved`. It reconstructs and compares the entire review
   before prompting. It rechecks after password entry, then uses the existing
   owned controller and private pipes. The password never becomes an argument,
   environment variable, review field or file. There is no synthetic CLI mode.

The fixed controller, identity, collector and reporter entries use `-I -B`,
the delivered source inventory and the reviewed dependency digest. A review
cannot select arbitrary commands. The original backend validates private gates,
job identity, leases, source/publication state, permits and freshness. Reports
can run after a dependency change without importing a broker client.

## Settings proposed for review

| Setting | Candidate value |
|---|---|
| Source | Nasdaq CURRENT, same-day history and fresh CURRENT cutover |
| Eligible reasons / expiry | LUDP and M / regular-session close |
| Active Hot / distinct new symbols per session | 1 / 1 |
| Hot quote call ceiling | 9,360; no catch-up of past slots |
| Identity quote permit ceiling | 3, retained across resume |
| Feed requests | At most 390; 60 seconds after completion |
| Worker starts | At most 3 across the original daily state |
| Progress / authentication / replacement hold | 3 s / 8 s / 15 s |
| Cleanup / final report | 10 s / 60 s |
| Uni / Focus | Existing interleaved-v1 pollers in their own windows |

These are proposed values. Preparing a review or passing command 72 does not
adopt them or enable production Hot. The unchanged policy also retains its
stabilization rules and warnings about intermediate feed mutations and older
unknown carryovers. `READY_WITH_GAPS` describes declared source reconciliation;
it does not prove all historical halt mutations were observed.

## Status, stop, resume and rollback

`outer-status --outer-root PATH` checks the independently owned scope and result.
`hot-status --state-root PATH` reads membership, collection, source gaps and
saved incidents. `HOT_STATUS.txt` and `hot-incidents.json` remain backend status
artifacts. Quote age is not a process heartbeat.

`stop --outer-root PATH` writes a nonce/configuration-bound cooperative request.
The outer stops its own Hot/controller/source/identity processes, confirms the
owned scope is empty, and runs the separate final reporter. Keep the result and
report. The command does not stop Uni, Focus or Health or withdraw durable source
requests. Stopping Hot does not by itself demote membership.

Manual resume requires a **new review**, `--mode manual_resume`, and
`--previous-outer PATH`, plus a fresh outer directory and explicit approval of
the new digest. It retains the original complete state/catalog/proposals,
configuration, worker commands and budgets. The previous empty scope must be
confirmed and its outer/report owner released. The read-only preflight validates
the original publication ledgers and refuses exhausted starts, blocked state or
latched provider stops. The backend checks again and applies the original
15-second replacement hold. No PID discovery, adoption or kill-by-name occurs.

This delivery runs out of its own output directory. It contains no installer,
branch switch, journal deletion, budget reset or automatic rollback. Operational
rollback is to stop this Hot invocation, verify owned cleanup, and continue the
installed Uni/Focus/Health release at `6b53ab1`. Preserve all journal and Hot
state evidence. If source demand or membership must also change, that is a
separate explicit membership action; deleting evidence is not rollback.

## Remaining release work

Windows qualification of this composition, representative real-provider timing
through the public daily path, and a concrete dated deployment/settings and
activation review remain. The previous bounded live profiles and synthetic
full-size history evidence are retained within their accepted scopes. This
delivery does not claim a full session, provider throughput, overall operating
release qualification or live activation. Manual controls and the read-only
Overlay remain the next product work after controlled automatic Hot.
