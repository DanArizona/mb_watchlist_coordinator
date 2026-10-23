# Nasdaq request reuse and representative workloads

This experimental increment preserves every captured halt/update while reducing
Coordinator request history when later distinct halts concern a symbol already
covered by an active request from this same Nasdaq producer.

## Behavior

- `HaltProducerSettings(..., reuse_active_symbol_requests=True)` explicitly
  selects producer contract `nasdaq-source-requests-v2`. The default remains
  `False`, with byte-identical v1 identity/settings payloads. A v1 ledger cannot
  silently open in v2 mode or vice versa.
- Each halt retains its own stable event ID, source capture, raw hash,
  normalized row, discovery/receipt timestamps and derived command. Changed
  resumption times and reason/status fields remain in successive source receipts.
  They do not overwrite earlier observations or acquire earlier availability.
- Reuse requires a previously delivered, accepted original request from this
  producer's own source history, for the exact single symbol and Hot channel,
  active at delivery and covering the entire requested remaining lifetime.
  Membership alone, a manual/algorithmic request, an unrelated same-owner
  request, cancelled demand, a future activation or a shorter lifetime is
  insufficient. Super-user restrictions continue to cap applied membership.
- The request store holds one SQLite write transaction across fresh history
  validation, coverage selection and an append-only reuse binding. Bindings are
  separate from Coordinator request events. They retain an exact command, the
  selected original event, the verified prefix, decision time and a hash chain.
  Every binding read revalidates coverage against that original prefix.
- Source acknowledgement binds the later halt to this receipt and its original
  source-owned request. Interruption after binding but before acknowledgement
  preserves the original decision on retry, including after cancellation/expiry.
  Exact retries cannot recreate demand. New events after withdrawal still go
  through ordinary request admission when no covering request exists.
- The producer still reads/reconstructs its retained capture history. This is
  a reduction of Coordinator request-history growth, not constant-time source
  processing or a replacement for eventual producer scaling work.

## Historical workload basis

The saved study archive is `Nasdaq_halt_history_Aug24_Oct22_2026.zip`.
The included `workload_facts.json` pins the official
[Nasdaq history-search](https://www.nasdaqtrader.com/Trader.aspx?id=TradingHaltSearch)
response hash and contains the selected facts.
The study covers 43 trading days: 2,300 distinct halts, including 2,046 LUDP/M
halts. Daily LUDP/M mean/median/maximum are 47.6/42/107, and qualifying unique
symbols average 21.0 with maximum 30. Raw history has 4,645 rows; mutable rows
for the same symbol/initial halt timestamp are one halt identity.

The paired offline workloads use:

| Case | Basis | Halts | Symbols |
|---|---|---:|---:|
| Typical | September 10 event times/symbols | 42 | 21 |
| Busiest | September 16 event times/symbols | 107 | 27 |
| Margin | Explicit synthetic larger day | 160 | 40 |

Each has a synthetic 553/40/0 anchor and logical clock. Historical halt times
are remapped to a synthetic session date. Receipt times and announced resumption
fields are fabricated, labelled as such, and used to prove retention only. Each
capture contains a changed event row. This does not simulate all 390 cumulative
minute RSS snapshots or prove original announcement availability. Each variant
uses native request, source, Coordinator publication and schema-v2 journal APIs.
The source facts and every applied membership checkpoint must match across the
per-event and reuse variants. Native audit and two matching native replays,
cold source/service reconstruction and unchanged-byte idle checks are required.

The 30-cycle idle gates remain p95 <=0.5s and maximum <=1s. Passing these local
workloads does not erase the prior failed 1,000-receipt/200-publication stress
fixture, qualify all-day source replay, or establish Windows/provider capacity.

## Windows handoff

Run only the new source-pinned `32_verify_nasdaq_request_reuse.cmd`. It verifies
the affected suites, then all three paired native workload cases. Network is
denied in process. It uses owned temporary/experimental databases and needs no
API, password or production journal. Progress appears during construction.
Each fixture has a 600-second construction budget. The command returns to its
prompt and saves the detailed verification/workload reports below its own runs.

Windows correctness and workload results are PENDING until the operator supplies
the output. Source-only checkpoint publication does not install this increment,
change production polling cadence or activate production Hot.

Complete operational recovery, shared live/recovered delivery, provider/combined
load adoption and production integration remain subsequent work.

## Retained development findings

The first development matrix used an erroneous 16:30 test stop inherited from
09:30's minute component. Its idle samples occurred after the actual 16:00
producer expiry, so those samples are REJECTED for active-Hot qualification.
That run also stopped during margin-reuse construction at the existing
`Publication head changed during cycle` guard. The partial databases, original
intermediate report and explicit failed-run record are retained. The prior
cloud rich-history construction encountered the same guard before this feature.
The cause remains unresolved. A later successful memory-filesystem run does not
establish a filesystem cause or repair.

The corrected native matrix explicitly ends at 16:00 and asserts active Hot
before/after idle measurement. It reconstructs all six fixtures through native
APIs on a memory filesystem. A later read-only final-source qualification
reopens those exact saved databases after adding consistent SQLite read
transactions for source and request/binding snapshots. Construction-source
copies/inventory and final-source measurement inventory are retained. This is
fresh full validation, not a verified-prefix cache or silent reconstruction.
The final-source read-only measurement uses 100 idle samples per case and three
fresh-object source/service reopens, with all database bytes unchanged. These
are same-process object reopens, not an OS-cache flush or process memory soak.

Earlier 1,000-receipt/200-publication timing failures remain accepted historical
failures. The new workloads cover one selected Nasdaq producer without ordinary
mixed-source cancellations/restrictions during the workload. Unit tests cover
those decision boundaries, concurrency, corrupt/rehashed bindings and lost ACKs.

## Final-source local results

| Logical case | Receipts per event / reuse | Per-event idle p95 | Reuse idle p95 | Reuse maximum |
|---|---:|---:|---:|---:|
| typical | 42 / 21 | 0.126s | 0.084s | 0.139s |
| busiest | 107 / 27 | 0.277s | 0.128s | 0.144s |
| margin | 160 / 40 | 0.463s | 0.203s | 0.216s |

All final-source candidate idle gates PASS on this Linux/cloud host, 100 samples per variant. All full source facts, applied membership checkpoints and native effective membership timelines match between paired variants. Native audit and replay checks pass, complete source/service fresh-object reopens match, and every database byte remains unchanged during measurement. All three fresh-object candidate reopens per case remain below the 10s gate. These are local selected-workload results, with Windows qualification pending.

The final extracted package passes all 341 affected checks in 7.374s from a path containing spaces. Altered source is refused before tests. Windows command 32 remains PENDING.
Delivery: `nasdaq_request_reuse_20261023_004809_6660ad.zip`, 163669 bytes, 59 files, SHA-256 `a72647cfbb99f881ca9ed2aa7bdc39c097c286ad2ebf0e4eba0cf132f5ce1101`.
