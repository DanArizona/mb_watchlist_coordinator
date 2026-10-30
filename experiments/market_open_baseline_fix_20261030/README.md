**Windows78 ACCEPTED12/12;79/80 completed; subsequent bounded77 live trial PASSED.**
All actual CMD prompts returned. This preparation correction and its existing
qualification are complete. No repeat is due. See [Windows acceptance](WINDOWS_ACCEPTANCE.json)
and the [live closeout](../market_open_daily_check_20261029/WINDOWS_LIVE_ACCEPTANCE.json).
The instructions below are retained historical procedure.

# After-opening isolated baseline preparation

This preparation-only companion corrects command76's attempt to republish the
09:30 opening membership after09:30. It leaves the original qualified packet at
`C:\Users\danla\hot75\p75` unchanged, including its source inventory and Windows75
result. No repeat of75, provider timing, recovery or paced source qualification
is requested. The original failed attempt is retained at
`C:\Users\danla\hot75\p75\runs\market_open_daily_20261030_f3beaf98`.

There are three separate actions:

1. **78** runs12 focused offline checks on synthetic journals. These cover an
   actual read-only SQLite export, original publication times, current import
   time, refusal of tampered/reused inputs, the original native rejection of
   new backdated publication and the unchanged public launcher's review. No
   password, network, API, installation or production access.
2. **79** is a separate read-only opening-membership export from today's
   production journal. This is an additional local evidence-read step compared
   with the original plan. It opens SQLite with mode=ro and query_only, in one
   read transaction, and selects store_identity and the three membership tables
   only. It does not select quote/acquisition content, update the database,
   initialize a store or control a poller. It writes a new closed export below
   this companion's own runs folder and refuses an existing output file.
3. **80** reads that closed export and the first attempt's retained proposals and
   same-day directory. It creates a **fresh** isolated trial root under the
   original p75/runs folder, preserving both original publication timestamps
   and opening content. The new native store identity uses current time. It
   performs no new membership-publication operation or live clock override.
   It performs no new directory download or password/provider action. The old
   partial attempt remains unchanged. Native parsing/audit and the unchanged
   p75 loader must accept the result before Prepared trial is printed.

The original **77** remains the live entry, used only with the newly printed
prepared trial path after review of the preparation result. It consumes only
isolated files. Friday's existing bounded-trial approval remains in force:
180seconds, at most72 Hot plus3 identity permits,1 admitted symbol,4 paced feed
attempts, maximum3 worker starts, full15-second hold and original progress,
credential, request, cleanup and independent-report deadlines. Production Hot
remains disabled. No production source installation or data-root migration.

Extract this small companion ZIP under `C:\Users\danla\hot78`. Its top folder is
`p78`; do not place it inside p75's inventoried source files.

```cmd
powershell -NoProfile -Command "Expand-Archive -LiteralPath 'C:\Users\danla\Downloads\market_open_baseline_fix_20261030.zip' -DestinationPath 'C:\Users\danla\hot78'"
```

Run78 first and return its final JSON and CMD prompt. The two later commands are
fixed to today's observed paths; they require the matching Windows78 result and
the existing Windows75 acceptance before reading production membership.

```cmd
call "C:\Users\danla\hot78\p78\78_verify_baseline_copy.cmd"
```

```cmd
call "C:\Users\danla\hot78\p78\79_export_opening_baseline.cmd"
```

```cmd
call "C:\Users\danla\hot78\p78\80_prepare_from_baseline.cmd"
```

If a command refuses or fails, retain its files and console output. No command
resets state, overwrites an export, starts a Hot worker or retries a provider.
The Windows78 result is pending until the operator returns it. A local PASS
does not constitute Windows or live-provider qualification.
