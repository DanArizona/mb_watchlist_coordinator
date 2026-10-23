# Shared live/recovered Nasdaq request delivery

This experimental increment queues eligible recovered halts through normal
sampling request admission and native Coordinator publication. It has no HTTP
transport, broker calls, poller launch, process restart or READY transition.

## Explicit components

- A fresh `HaltProducerSettings(..., delivery_mode='external')` selects the
  separate `nasdaq-source-observations-v3` source ledger. Its CURRENT startup
  baseline and HISTORICAL audit-only meanings remain unchanged. Calling its
  direct `deliver_pending()` is refused. Default direct v1/v2 settings payloads
  and identities remain unchanged; existing producer ledgers are not migrated.
- The accepted `nasdaq-halt-recovery-receipts-v1` ledger remains receipts-only.
  It retains every supplied observation, source/receipt time, raw capture hash,
  dated-query manifest and known trace gaps. This new adapter reads it without
  changing that contract.
- `NasdaqRecoveryDelivery` owns a new ledger and distinct reserved Nasdaq source
  ID for both live and recovered demand. This ID must be included in normal
  admission permissions where required; it is a trusted local configuration,
  not caller authentication. Observation-only and shared-delivery owner IDs
  must differ. Manual and algorithmic source owners remain independent.

The source observer's derived commands remain observational candidates, not
delivered requests. Only the shared outbox submits demand in this explicit mode.
It rejects direct request activity under the observation owner's identity and
refuses to adopt unbound requests under the shared owner. This is a fresh
experimental path, not an implicit takeover of an existing live producer.

## Delivery and recovery semantics

1. Feed acquisition/receipt recording remains outside this adapter. Supply
   validated live snapshots and explicit dated recovery receipts as before.
2. `reconcile()` validates current source histories and queues eligible events.
   Recovered events wait for every declared query to have a valid receipt. Live
   candidates may continue while recovery queries are incomplete. Prior-day,
   off-hours and unresolved-original-reason facts remain context, not admission.
3. Live and recovery use the same symbol plus initial halt timestamp event ID.
   The first queued command is immutable. A later overlapping source, changed
   resumption field or retried reconciliation cannot replace its payload. Live
   provenance is preferred when both sources are already known in one read.
4. Each command is created at reconciliation time and expires at target-session
   regular close. Original halt time and observed/received knowledge time remain
   separate metadata. A previously released symbol can still qualify for the
   existing until-close request policy. No earlier membership or quote coverage
   is fabricated, and announced release times do not prove executed trading.
5. `deliver_pending()` invokes normal catalog, source, capacity, restriction and
   lifetime rules. Distinct later halts may reuse only this outbox's accepted,
   active original demand covering the remaining lifetime. Manual/algorithmic
   demand and unrelated same-owner requests cannot substitute.
6. Request/binding commit precedes the outbox acknowledgement. An interruption
   leaves a durable pending command; exact retry retrieves the original receipt
   even after cancellation or expiry. An already reconciled halt cannot undo a
   cancellation. A genuinely new halt without covering demand goes through
   normal admission. Rejections are acknowledged as durable decisions.
7. A separate normal `SamplingPublicationService.cycle()` publishes admitted
   membership. The adapter reports publication as `EXTERNAL_NOT_VERIFIED` and
   status as `RECOVERING` even after delivery. It does not claim to orchestrate
   publication, polling, full trace restoration or process readiness.

Every outbox read validates its full hash chain, original source prefix proofs,
derived commands, current request history, alias origins and acknowledgements.
SQLite read transactions keep an outbox read coherent; write transactions
serialize queueing and acknowledgement batches. Source capture ledgers remain
independently append-only and are fully revalidated on each read. There is no
persistent verified-prefix cache or constant-time/capacity claim. A missing
ledger fails; normal reopen never silently creates a replacement.

## Offline Windows qualification

Run only the new inventory-pinned `33_verify_nasdaq_recovery_delivery.cmd` from
its extracted handoff. It runs affected source/store/admission/publication/native
integration tests, including the new recovery-delivery boundaries. Network is
denied, with no password, API or production journal. It does not repeat the
three unchanged command-32 performance workloads or a live provider trial.

The new checks cover both overlap orders, recovery-first before a subsequent live
command, incomplete queries with continuing live demand, lost request/alias ACKs,
whole-batch interruption, cancellation, expiry, catalog/capacity rejection,
restrictions, independent manual demand, concurrent workers, source rehashing,
ACK/binding corruption, missing files and exact reopen. Native integration proves
recovered outside-Uni request -> Coordinator publication -> effective Hot
membership, native audit and matching replays, with effective time at/after
recovery. It uses synthetic inputs and makes no live Hot acquisition claim.

Windows qualification for these changed bytes remains pending until the
operator supplies the completed new command-33 console. Earlier accepted
commands, including 32, require no unchanged rerun.

## Remaining work

Paced dated HTTP query transport, non-feed/failure handling and durable query
retry scheduling remain separate. An explicit recover/reconcile/ready supervisor,
broker identity resolution integration, old-producer migration policy,
same-process observer health, full cumulative source-history/mixed-source/soak
and provider capacity remain unqualified. Prior stress timing and cloud
publication-head failures are retained. Production cadence and Hot stay unchanged.
