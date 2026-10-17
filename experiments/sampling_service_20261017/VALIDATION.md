# Validation status

Implementation parent: `65d452947590a671d2e3f896db8e472ff00e25ec` on
`experiment/sampling-promotion-2026-10-16` in `DanArizona/mb_watchlist_coordinator`.
The original frozen promotion experiment and accepted request, policy and Nasdaq
implementations are preserved. Pinned market-data source remains from
`a082f544112643b4e5f459d15c67f60d0a1ef83d`.

Local verification: 28 focused tests and the bounded running-process proof PASS.
The full Coordinator suite passes 260 tests and 18 subtests. The proof exercises
real local scheduling and separate process exit/recovery, not a live Nasdaq or
brokerage acquisition. Exact test/receipt hashes and timings are retained in
`validation`. Fresh journals and full reports remain in ignored `runs` folders.

MasterBot Windows acceptance is **COMPLETE**, based on the full CMD output
supplied October 17: 28 tests PASS in 2.401s; running proof PASS; 60 actual
process cycles; five hierarchy revisions; both abrupt-exit recovery cases,
audit and two identical replays PASS; clean prompt return. Structured evidence is
in `validation/masterbot_acceptance_20261017.json`. Detailed reports and databases
remain on MasterBot under `runs/20261017T235135Z-e030daf5`.

Journal replay SHA-256:
`b8958002f09a4a16c36fbd5d7d96d11dd9a6c576a160dca2c94ac7f2c5f1e7aa`.
Publication outcomes SHA-256:
`56c0bccd087608157d2572b259a90f2aeda562f945cae4b8d112bc4c85bd2941`.
The actual clocks/receipts differ across runs; these are the accepted host-run
hashes, not values required to equal another run's hashes.

No installation, credential entry, network access, production journal write,
poller restart or Hot acquisition occurred. The accepted ZIP and implementation
remain unchanged. The next development increment is isolated measured Hot
acquisition. Live Nasdaq transport/new-event validation, external authentication
and production settings/capacity retain their separate boundaries.
