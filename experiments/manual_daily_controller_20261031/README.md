# Nasdaq and manual requests in one daily controller — development candidate

This increment connects the existing manual interface to the daily controller
through an explicit `manual-40-v1` profile. It is a separate candidate alongside
Monday's approved p85 `multi-40-v1` release. Existing single/multi policy values
and hashes are unchanged. No production installation or activation is included.

## Combined behavior

- Nasdaq remains its source-owned daily producer and uses the original catalog,
  broker identity gate, 120 identity permits, three attempts per symbol and
  two-second spacing. Manual promotions are restricted to the verified opening
  Uni in this increment and make no identity/provider call.
- Both sources enter the same request ledger and atomic publication service.
  The ledger's write transaction enforces **40 distinct Hot symbols** and **40
  distinct Focus additions beyond opening r1** across both sources. Existing
  outside-Uni admission retains its 40-symbol ceiling. With a 40-symbol opening
  Focus, effective Focus cannot exceed 80. Hot remains nested in Focus and Uni.
- Accepted distinct symbols remain charged after withdrawal, expiry or
  restriction. This prevents a second allowance or budget recycling, including
  while demotion grace/minimum residence retain earlier membership. Duplicate
  demand for one symbol consumes one symbol slot, regardless of source.
- Only the original controller publishes membership. Manual controls record
  durable actions and reconstruct requested/pending/effective/blocked feedback
  from verified ledgers and native effective times. Shared allowance usage is
  visible. Manual withdrawal does not cancel Nasdaq demand; privileged caps use
  the original restriction policy and can override both ordinary sources.
- The controls attach read-only to the existing daily configuration before
  writing only their bound manual receipts/requests. They pin the actor,
  configuration and controller invocation. Missing, stopped, stale, changed or
  replaced ownership disables writes. An old window cannot attach itself to a
  resumed invocation. The original requests, membership, budgets and manual
  receipts survive manual controller resume; the original 15-second hold remains.
- Collection and final verification use the existing multi-symbol/native period
  path. Hot quote limits, cadence, dispatch lateness and all 3/8/15/10/60-second
  progress/authentication/replacement/cleanup/reporting limits are unchanged.

## Windows qualification

Download `@@ZIP@@` and extract separately in the sea-green CMD window:

```cmd
powershell -NoProfile -Command "Expand-Archive -LiteralPath 'C:\Users\danla\Downloads\@@ZIP@@' -DestinationPath 'C:\Users\danla\manual92'"
```

Run this command alone:

```cmd
call "C:\Users\danla\manual92\p92\92_verify_shared_manual_controller.cmd"
```

Allow about 90 seconds. The packet runs 45 focused checks, including real owned
processes with synthetic credentials/SDK, shared SQLite ledgers, native quote
collection and final audit/content/event-order verification. A synthetic Tk
preview exercises the display and holds its completed view for 15 seconds.
Network is denied in the verifier and owned test children. No actual vault,
broker library, production journal or production process is accessed.

Paste the final JSON and actual returned CMD prompt. The long accepted capacity,
120-second paced-source and recovery drills are not repeated.

## Scope and next work

This is step 1: an integrated Nasdaq/manual daily composition for opening-Uni
manual symbols. Manual outside-Uni promotions are durably blocked at the common
request boundary, including attempts that bypass the GUI. Step 2 will connect
them to the shared broker-identity path; catalog presence is not confirmation.

The original p89 Windows 54/54/actual GUI acceptance remains retained. This
candidate includes the later steady-button fix and affected local/UI checks.
The original failed development cleanup assertion inspected a process handle
after the controller had cleared it; the corrected check retains the actual
handle and verifies its exit. No cleanup/runtime gate was relaxed.

The packet exposes no production start, installation or activation command.
The trusted controls API/CLI supports only an already owned manual-enabled
session with its exact configuration digest; p85 cannot be rebound to this
profile or enabled by changing a file. Production delivery/review and activation
remain separate. Full-day and representative provider capacity remain unqualified.
