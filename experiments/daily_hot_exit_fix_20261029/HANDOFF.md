# Command 64 next — owned exit / role-lease correction

**Superseded:** supplied Windows command 64 is FAILED 14/15. The lease/exit
recovery component passed (15.029873s hold). The owner smoke proof stopped on a
recorded OperationalError: disk I/O error in the source pipeline before its
first quote slot. See `../daily_hot_source_diagnostic_20261029/README.md` and
its supplied-result review for read-only command 65. Historical results below
are unchanged; no automatic qualification retry or I/O repair is authorized here.

Original Windows command 63 remains FAILED: 133/134, zero errors/skips, actual
CMD return, run 20261029T080211Z_72278a8f. Original Windows files were not
independently read; the supplied console/final JSON is the basis of the review.
The Windows Job Object owner component passed cleanup (.218s), native audit and
two fresh replays. The representative history component passed 11,703 events,
11,700 acquisitions/542,099 quote observations, cold owned startup 2.17647s,
pre-API gates .408932/.381419s and matching fresh replays. Whole-packet failure
and top-level false qualification fields are preserved, not rewritten.

The reported race was reproduced with an actual released OS role lease and
the owned collector still alive, then deliberately exiting with code 75 after
the lease probe. Original code failed identically: missing-lease terminal,
one charged start and no recorded exit/hold. One reproduction failed in 10.843s.
The corrected path waits at most .05s for the exact owned handle, sends no
signal during confirmation, and only confirmed exit starts the full original
15-second wall and elapsed hold. A genuinely live child without the role lease
still blocks. An additional regression covers exit between the outer/inner
polls: the inner helper cannot launch any replacement while the entry child is
being inspected/reaped. The exit token must match the original reserved job.
Native code, authentication/progress gates, budgets and all other runtime code
are unchanged. The builder enforces the exact one-file runtime diff and native
commit before permitting reuse of the supplied Windows component evidence.

New immutable ZIP: daily_hot_exit_fix_20261029_7cce5c0_5552c5d.zip, 827,507 bytes,
SHA-256 37d9f83afe0c78baa1bcba402317a49bcd19617959933473c490c24997fe437d.
Coordinator source 7cce5c014ecdf654546cd74784706343fa346a44, public-equivalent
d9da1c613a358eda61a08e1c7416dbda4f7956bd, full tree
a7a0c3ee96518a60e13b7c8b139a76c6f1adbb68. Native remains unpublished
5552c5db43351d1a9ae8d376196cc99ba9c7f05d; its existing private source bundle
and capacity evidence remain available without duplicate archives/reruns.

Frozen local qualification passed 15/15, zero errors/failures/skips, 36.015645742s,
Linux/Python 3.12.14. The forced actual lease/exit gap passed native recovery,
15.041575s hold, no repeat request for the saved response, zero unexplained gaps
and two equal fresh replays. Raw recovery audit stays FAILED for intentional
hold/startup gaps. New owner collection/reporting smoke proof passes. Two new
checks from the exact ZIP extracted into a path with spaces passed in .747s,
with pre/post inventory. No unchanged full-size or old-packet repeat occurred.
An earlier streamed development log lacked a final summary and is marked
incomplete; the explicit direct-file result and frozen result are authoritative.

Next: extract the new ZIP into a separate output directory and run
64_verify_daily_hot_exit_fix.cmd in sea-green, about 45 seconds. Supply final
JSON plus actual returned CMD prompt. Windows correction acceptance is pending;
the result qualifies this correction and retains prior component evidence,
not a retroactive PASS for command 63. Then finish provider capacity and
concrete deployment/rollback/settings/activation review before controlled Hot.
No source installation, real vault/SDK/provider access, adopted setting, main
merge or Hot activation occurred. Production Hot remains disabled; manual
membership and read-only Overlay follow closely, deferred OV work stays deferred.
