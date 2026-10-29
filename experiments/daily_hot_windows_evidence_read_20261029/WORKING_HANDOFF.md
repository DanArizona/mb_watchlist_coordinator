# Windows evidence-read correction — October 29

User supplied command 70 complete console/final JSON and actual returned CMD
prompt, run 20261029T220557Z_278c0ba5. FAILED 1/1, paced 36.937s/report 37.265s.
CAPTURED PermissionError errno 13, winerror null on the owned heartbeat file
inside recovery_workers._heartbeat line178, through ensure/monitor_once.
Previous worker was RUNNING generation1 PID66064; prior bound heartbeat check
valid at age .120609s with original 3s limit. Monitor observation at simulated
14:00:36.191828Z precedes outer stale stop at 36.726323Z. Driver live age0.
No outer exception captured. Thus this run's initiating failure is runtime
file access, outside the test stop callback; a stale label is downstream.
Windows Job cleanup .047s, no force, empty scope, controller0. Audit PASS and
equal two-event replays cover opening history only; source cutover empty.
Full review JSON and primary-source URLs are recorded here. The exact sharing
actor and relationship to older SQLite I/O/ledger/native-crash events remain
unproven. Do not attribute this to Defender, CPU or quote-cadence overload.

Candidate adds read_process_text in recovery_workers: only Windows read
PermissionError winerror5/32/33 or bare EACCES, max .25s/26 attempts. It reopens
complete values; no cached heartbeat, timestamp reset, JSON/identity bypass,
provider/state replay or deadline extension. Permanent/unrelated errors still
raise. Recovery job/heartbeat reads, common daily read_json and the two dynamic
daily publication-status readers use it. Exactly four runtime files differ
from frozen2f56703. Native5552c5d and installed production6b53ab1 unchanged.

Local 22 component tests PASS1.208s: nine read/freshness cases and thirteen
existing ownership/fence cases. One original actual paced proof PASS126.571565s
separately against development4193c9b, treef20f03b0380da1115d02c79da8b8d58079e8e15c.
Three valid attempts at60.702353/60.803616s intervals, READY_WITH_GAPS,26 native
acquisitions/two after cutover,1 identity permit/1 worker start. Audit PASS,
equal29-event replays SHA3729aa65008c192f82f836d5dc42352be6a2ff96d42200affe4b855bc55fe0be;
POSIX owned scope empty without force in .060843s, original Uni/Focus poll
runs retained. No monitor/outer exception. This Linux regression does not
qualify native Windows sharing; the new Windows branch is unit-injected here.

Self-contained command71 packet selects26 Windows checks:22 component cases,
3 real native Windows sharing cases and1 original paced proof. Native fixture
holds a known DELETE-access handle, proves old CRT Path.read_text fails, then
releases and verifies read recovery. Persistent conflict still fails bounded;
four readers inspect64 actual atomic publications. This proves a controlled
mechanism when passed, not the exact original actor. Two original test-only
stack flags OFF in memory; original assertions/pacing unchanged. Owner/monitor
observers remain for a new error. No accepted full-size/recovery drill repeat.

No actual provider/vault/SDK, production installation/settings or Hot activation.
Original Windows67/68/69/70 FAILED remain. Full Oct29 production closeout not
supplied. Next: one Windows71 result and actual returned CMD prompt, then act
on that concrete outcome. Live provider capacity and concrete deployment/
rollback/settings/activation review remain. Manual controls and read-only
Overlay follow; overnight-volume alternative remains deferred.
