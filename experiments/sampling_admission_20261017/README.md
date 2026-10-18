# Outside-Uni admission review

This increment extends the accepted fixed-Uni request, policy, publication and
synthetic acquisition path. It runs from bundled source without installing it.
No network, API call, password, production journal or poller is involved.

From the extracted review folder, run `01_run_sampling_admission.cmd` in a CMD
window with the `sea-green` environment already active. The command uses absolute
paths relative to itself and works from any starting directory, including paths
with spaces. It opens no extra CMD windows. Four bounded child processes exit
before the parent returns to its prompt. The test phase is quick; the actual-clock
phase takes about 25-35 seconds and reports the current scheduled wait every two
seconds. Expected final result: `Outside-Uni admission proof: PASS`.

## Request and membership behavior

An explicit `AdmissionPolicy` enables additions for a new session ledger. Without
it, the existing fixed-Uni contract and hashes are unchanged. Existing ledgers
cannot silently switch modes or change their bound catalog, source permissions,
capacity, baseline or demotion policy.

| Request target | Membership required |
| --- | --- |
| Uni | Uni |
| Focus | Uni and Focus |
| Hot | Uni, Focus and Hot |

The original opening selection stays immutable. A complete later revision contains
the opening Uni plus session additions and the resolved Focus/Hot sets. A symbol
first enters the session-addition record when a request is active at a recorded
receipt/tick. Its origin points to that original request receipt. Future requests
do not add symbols early; cancelled or entirely missed future lifetimes do not
invent earlier membership. Publication effective time and completed acquisition
receipt time remain separate from logical admission time.

Session retention is selected explicitly with `uni_retention='session'`. Once
admitted, a symbol remains in this session ledger's Uni, including its terminal
historical state. Higher-group demand still follows source ownership, expiry,
privileged caps and ordinary grace/residence. A new dated ledger starts from its
own opening baseline; nothing is automatically carried into tomorrow. Early
removal from Uni and exclusion below Uni are outside this increment. Existing Uni
and Focus caps bound the highest group; setting a cap alone never admits a symbol.

The catalog is an eligibility input for instrument identity, separate from the
opening daily screen. The review supplies a synthetic MSFT/NVDA/AMD catalog;
it does not establish broker tradability. Production directory/catalog freshness,
symbol mapping and broker resolution require integration. No morning market-cap,
price or volume filter is rerun as an admission requirement. Trusted local actor
identities are explicit, but this API does not authenticate external callers.

The review limits additions to two distinct symbols. Already admitted symbols plus
uncancelled, unexpired valid future reservations consume that limit. Multiple
sources requesting the same symbol consume one place. Cancelling/expiring a future
reservation before activation releases its place; withdrawing an already admitted
symbol does not, because Uni coverage is retained. A multi-symbol request is
accepted or rejected as a whole. Capacity/catalog/source rejection is a durable
receipt; there is no silent eviction, automatic retry of a terminal rejection or
implicit production limit. A later explicit new request can be reconsidered.

Nasdaq retains its existing startup-baseline, session-window, reason-code and
event-deduplication rules. With admission enabled, an outside-Uni eligible halt is
queued to the common request store, which records an accepted or rejected outcome.
Delivery-commit/ACK interruption retries the original source/request identity.
No live Nasdaq fetch or actual new halt is claimed.

## Proof phases

1. Forty focused tests cover source ownership, Uni-only/Focus/Hot additions,
   capacity and future reservations, cancellation/expiry, restrictions, restart,
   configuration integrity, atomic publication rollback, collection and replay.
2. A labeled logical regular-session Nasdaq trace starts with an empty feed
   baseline, records a synthetic outside-Uni halt, interrupts delivery after the
   request commit and retries its original receipt. Empty Hot slots precede the
   effective promotion; the subsequent Hot slot records its first quote.
3. Four independent actual-clock processes run Coordinator, Uni, Focus and Hot.
   Opening Uni AAPL/SPY is acquired first. A manual Uni-only request admits MSFT;
   an algorithm requests Focus; a synthetic direct halt-source request asks for
   Hot. Independent withdrawals eventually demote Focus/Hot while Uni coverage
   continues. This real-clock phase uses a direct synthetic halt-source request
   because an after-hours/weekend run cannot demonstrate a live eligible halt.

The actual-clock window is 20 seconds. Review grids are Uni every 6 seconds,
Focus every 4 seconds and Hot every 2 seconds; baseline production cadence code is
unchanged. Review policy is 0.2-second grace, 0.5-second residence, immediate cap,
0.35-second publication lead and 0.05-second local service polling. Logical tests
also exercise longer holds and explicit zero holds. Existing timers begin from
recorded logical membership decisions rather than publication acknowledgements;
an outage does not redefine that earlier contract. These are demonstration values,
not adopted production defaults or measured safe provider rates.

The final audit uses each slot's exact hierarchy, including the larger Uni batch
count. In-flight work retains its captured revision. Replays reconstruct original
and expanded membership and expose quotes only at response completion. Repeated
replay of one journal must match; actual-clock hashes differ between runs.

Reports, journals and error details are under `runs/<unique-run-id>`. Compact local
evidence is under `validation`. The first frozen promotion experiment and accepted
ZIPs remain unchanged. MasterBot accepted all 40 tests in 2.405s and the retained
four-process proof on October 17, with complete coverage and a clean prompt return.
Windows evidence is in `validation/masterbot_acceptance_20261017.json`. Next:
market-data checkout integration, bounded provider timing and production
catalog/transport decisions, then a genuinely new qualifying live halt.
