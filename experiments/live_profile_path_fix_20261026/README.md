# October 26 live Hot path correction — command 54

The original ordinary command51 run `profile_20261026T151602Z_401b615a`
remains FAILED. It reached ACTIVE, then failed publishing its first worker-job
temporary file at a 190-character parent / 269-character temporary path.
The native audit retains one missing Hot slot, zero acquisitions and zero empty
skips. Both fresh replays match. Owned controller/reporting scopes exited and
the actual CMD prompt returned. Production Uni/Focus were healthy at 11:20:40 ET.

The path length is consistent with the documented Windows MAX_PATH boundary;
the original host's registry/manifest state has not been inspected. A missing
parent has not been independently ruled out from the console alone. The original
code creates that worker parent during runtime initialization, so the path-length
explanation is strongly supported. The focused Windows check exercises native
publication and an owned synthetic worker at the recorded parent length.

Only two previously accepted runtime files change:

- `recovery_workers.py` gives the same-directory atomic temporary file its own
  UUID rather than appending a second UUID to the full target filename. At the
  recorded parent length this reduces the job temporary path from 269 to 227
  characters. Exclusive creation, flush/fsync, atomic replacement, the same
  complete value, at most 26 attempts / 0.25s Windows sharing-conflict retries,
  unrelated-error propagation and temporary cleanup remain unchanged.
- `outer_harness.py` recognizes FAILED / observed controller exit before the
  preparation timeout label. Preparation, active, cleanup and reporting time
  limits remain unchanged. Operator stop and the active deadline retain their
  existing precedence. A live unprepared controller still stops at the original
  preparation endpoint.

Command54 is OFFLINE: no password, vault, broker, feed/directory HTTP or production
journal/process. It checks the other 68 original runtime source pins, the exact
two reviewed corrections, affected path/atomic/outer tests and one affected
synthetic native quote with independent read-only audit/two replays. The native
Windows sharing check runs on Windows; its Linux skip is reported. Earlier
accepted complete suites and Windows Job drills are not repeated.

After command54 passes on MasterBot sea-green and the actual CMD prompt returns,
obtain fresh production health. Use this new folder's command51 separately for
the ordinary live profile, then review complete native audit/two replays, cleanup
and prompt return before this folder's command52 recovery profile. Each live
invocation prompts once. Its command53 / Ctrl+C requests only its own bound stop.
The original folder, original reports and original failed labels are not edited.

All original limits remain: >=60s preparation; frozen 720s window ending by
16:00 ET; 60 Hot plus three identity quote permits; two directory permits; ten
feed attempts paced >=60s after completed attempts; at most three worker starts;
3s work-progress/staleness and separate 8s credentials; 10s cleanup and 60s
reporting. Only experimental Hot collects; production Uni/Focus remain independent.
Normal SDK refresh can update the shared token database. No qualifying event is
readiness only. Ordinary requires 30 committed/acknowledged post-cutover Hot
quotes; recovery separately requires 12 before the one owned fault, the full
15-second replacement hold and 24 after verified restart. No limits are relaxed.

This remains a fresh-controller entry. No new controller-resume launcher,
production Hot activation, main merge, broader capacity verdict or completed
live-profile result is implied.

Reference: https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation
