# Validation status

This increment follows Coordinator acceptance commit
`d42ceb3df9ca41f533e84f46d26515d69a2baef4`. The first frozen experiment and staged
market-data acquisition module are unchanged. The request store/reducer and optional
Nasdaq/publication paths now bind an explicit admission configuration when enabled.
Legacy mode preserves its identity and receipt behavior.

Local checks include 40 focused admission/publication/acquisition tests and the
full regression suite. A synthetic logical Nasdaq arrival feeds the common ledger
and Hot collector, including request-commit/ACK retry and exact receipt visibility.
The separate actual-clock proof runs four processes through Uni-only admission,
Focus/Hot escalation, independent withdrawal and Uni retention, with full configured
coverage, audit and identical repeated replay. In-flight and pending-admission
checks retain prior membership and never invent earlier observations.

Compact final local/archive evidence is retained in `validation`. The runner is
checked from the extracted archive under a directory containing spaces. Windows
acceptance on MasterBot is **COMPLETE**: all 40 tests PASS in 2.405s, the bounded
proof passes and the CMD window returns to its prompt. Four independent processes
complete Uni-only admission, Focus/Hot escalation, independent withdrawals and Uni
retention. Uni records four acquisitions/seven batch calls; Focus five/five; Hot
one acquisition/one batch call and nine empty skips. Complete configured coverage,
journal audit, request/publication restart and two identical acquisition-aware
replays pass. Synthetic Nasdaq adapter delivery and Hot collection pass in the
labeled logical-clock trace. Live market acquisitions remain zero.

Structured acceptance is in `validation/masterbot_acceptance_20261017.json`.
Detailed reports/databases remain on MasterBot in `runs/20261018T042907Z-48184345`.
Accepted journal replay SHA-256:
`007ed74b9a9ac6c30d5d2eabd57807732f0dcfddb3454e9da0231641c81d96ce`.
Request replay SHA-256:
`1fcfe55669bbd0d254b383453e3b38ce53e4c72fb729dbc0f95ecdb470183809`.
Actual-clock hashes differ across runs; repeated replay of one journal must agree.
The accepted ZIP, implementation and tests remain unchanged.

The instrument catalog is synthetic. No actual listing lookup, broker symbol
resolution, live halt ingestion, authenticated quote, capacity measurement or
production change occurred. Review catalog, allowed sources, capacity and timers
are explicit test settings. Session retention is implemented for isolated review;
production installation and session policy selection remain separate work.
