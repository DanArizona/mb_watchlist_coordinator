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
acceptance on MasterBot is **PENDING** until the user supplies its result.

The instrument catalog is synthetic. No actual listing lookup, broker symbol
resolution, live halt ingestion, authenticated quote, capacity measurement or
production change occurred. Review catalog, allowed sources, capacity and timers
are explicit test settings. Session retention is implemented for isolated review;
production installation and session policy selection remain separate work.
