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

MasterBot Windows review is **pending**. The CMD runner verifies source hashes,
runs the same 28 tests and independent bounded proof, reports PASS, and returns
to its prompt. Return that console output to record acceptance. No installation,
credential entry, network access, production journal write, or poller restart is
part of this review.
