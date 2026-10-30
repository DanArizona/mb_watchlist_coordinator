**Windows81 ACCEPTED: 30/30 checks and the actual five-phase Tk preview passed.**
Run20261030T202321Z_d012b6fd used Python3.12.13/Tk8.6.15. The preview completed
30refreshes, closed itself and stopped its reader executor; the actual CMD
prompt returned. See WINDOWS_ACCEPTANCE.json. No repeat is due. The delivered
ZIP and its source inventory remain unchanged; the qualification instructions
below are retained for reference. The read-only viewing command is ready.

# Persistent membership status

An independent window keeps three lists visible between updates:

| Panel | Contents |
| --- | --- |
| Hot | All current effective Hot members. |
| Focus | Current Focus members absent from that session's published opening r1 Focus. |
| Uni | Current Uni members absent from the same r1 Uni. |

Each row includes its first effective membership time in ET. A symbol can appear
in all three lists. The opening Uni/Focus rosters are omitted. Counts, effective
revision, last verification time, saved controller/collector/source status,
source/recovery warnings and last committed Hot acquisition remain visible.
The window refreshes about once a second without scrolling its output. Lists
have their own scrollbars and preserve position/selection between refreshes.
Close the window, use Close display or press Q to stop only this display.

The fixed r1 comes from the daily session's retained binding and must match the
native journal's published revision. Reopening the window or resuming the
controller does not establish a new baseline. Only effective published
membership is displayed. Future revisions are not shown early. The current
phase's lists show additions retained in membership; this is not a replacement
for a future removal/history interface.

The reader opens SQLite with mode=ro and query_only, in one short read
transaction. It validates r0/r1/current membership with the existing native
parser and reads acquisition headers only, not quote payloads. SQLite may use
its normal WAL/SHM coordination files. The display creates no application state,
acquires no owner lease, initializes no store, prompts for no password, requests
no network access and never starts/stops/resumes a controller or poller. Its
process blocks outbound network calls. Existing controller/native sources are
unchanged; only two independent display modules are added.

On a read failure the last verified lists stay visible beneath a prominent
LAST VERIFIED banner; their old timestamp remains visible. Current health is
then unavailable. An initial failure shows Unavailable, not empty membership.
Saved controller progress older than three seconds is marked STALE. Normal
STOPPED and BLOCKED states stay distinct. This is saved-evidence monitoring,
not a new supervisor or an assertion of live provider/quote freshness.

## Windows qualification

Extract under a short root. No installation or production changes are made.

```cmd
powershell -NoProfile -Command "Expand-Archive -LiteralPath 'C:\Users\danla\Downloads\@@ZIP@@' -DestinationPath 'C:\Users\danla\hot81'"
```

```cmd
call "C:\Users\danla\hot81\p81\81_verify_membership_status.cmd"
```

This runs 30 focused checks on small synthetic native journals. On Windows it
also opens a clearly labelled synthetic Tk preview for about six seconds. The
preview observes opening empty lists, an addition in all three lists, a failed
read retaining the lists, recovery without baseline reset and a stopped
controller. It closes itself and returns to CMD. Keep its final JSON and actual
returned prompt. No old paced/provider/recovery/capacity tests are repeated.

Python's standard tkinter/Tk is required for the window. The verifier records
the actual Tk version and observed preview phases; an unavailable GUI is a
Windows qualification failure, not a skipped check. Linux headless checks alone
do not qualify the actual Windows window.

## Read-only viewing after qualification

The state root is the retained daily Hot controller directory, not the journal
directory. For example, this shows the already closed October 30 isolated trial:

```cmd
call "C:\Users\danla\hot81\p81\82_show_membership_status.cmd" --state-root "C:\Users\danla\hot75\p75\runs\market_open_daily_20261030_8e53d198\daily_hot_check"
```

It reads the saved trial only; it does not repeat or resume that trial. Its
controller should be STOPPED and its effective Hot membership includes ITOC.
Monday's operating delivery will supply that session's state root in its launch
instructions. Use --once after --state-root PATH for one JSON snapshot instead
of a window. No production Hot activation or operating settings are adopted by
this display or its qualification.
