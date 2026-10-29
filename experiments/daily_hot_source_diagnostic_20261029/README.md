# Read-only saved source diagnostic

Extract this folder beside the original failed command-64 packet, under
mb_market_data/output. Run 65_diagnose_saved_hot_source.cmd in sea-green.
No password, API, qualification rerun, installation or production changes.

The default target is the exact saved owner proof from command-64 run
20261029T082857Z_49b9595b. The script accepts only the original synthetic
owner/daily_hot_test configuration and its sibling journal directory.
All SQLite databases are opened with mode=ro. It queries journal modes, checks
current integrity, compares database bytes before/after reading and retrieves
recent source/feed receipts. It never opens the credential configuration or
creates, replaces, checkpoints, repairs or writes a source database. A new
diagnostic JSON is saved only beneath this diagnostic folder.

The recorded primary failure is OperationalError: disk I/O error at
2026-10-30T14:00:04.458440Z, followed by controller stop at 04.481773 and outer
stop at 04.504387. The original handler did not retain the database, SQL
operation, traceback or extended SQLite code. This utility can identify
currently reproducible database faults and retained feed dispositions. Clean
current reads do not recover or explain a past transient error and are not
qualification or proof that the issue is fixed. They do not establish or rule
out a hardware fault. All earlier FAILED verdicts remain unchanged. The
separate Windows lease/exit recovery proof remains PASS, 15.029873-second hold.

Please provide the printed diagnostic output. Keep the failed original run.
