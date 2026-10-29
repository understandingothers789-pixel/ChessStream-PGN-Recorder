# Safe Stop → Start — dev16

Review found a race in the capture worker lifecycle. The GUI could replace its
QThread reference after isRunning() became false without joining it. Qt documents
that thread-local cleanup may continue after finished() is emitted. Also, the
old queued finished handler was not tied to the current worker and could reset
the replacement recording's controls.

Stop now disables recording controls while finalization runs. A Start request
through a hotkey during shutdown is queued once. The GUI retains the worker and
polls wait(0) every 20 ms without blocking; only a successful join allows deletion
and replacement. Repeated requests cannot start overlapping capture workers.
Finished, update, frame and region signals from retired workers cannot alter the
current recording. Preview startup follows the same ownership restriction.
Worker join and queued restart events are logged for future diagnosis.

Removed local logging imports that made logging a local variable throughout the
capture run method, potentially masking command/context error handling with an
UnboundLocalError.

Validation: 327 local tests passed. Regression tests use real Qt threads with
controlled delayed finalization, repeated Stop/Start cycles, a premature finished
notification, repeated Start requests, stale update/region/finished signals and
PGN persistence before restart. Physical Windows capture/audio shutdown remains
untested here. Without the original crash report, this fixes a verified unsafe
restart path but does not establish that it caused every reported crash.

## Native session teardown — dev17

The supplied pythonw.exe dialog reports an access violation but does not name the
faulting module. A further lifecycle review found that the worker retained its
OCR detector (which owns native inference sessions) after run() returned. Qt could
then destroy those sessions on the GUI thread. Cleanup now explicitly releases
the recognizer, OCR detector, context stabilizer and stopped audio listener before
capture-thread exit. This complements dev16's join-before-restart protection.
A real QThread regression verifies that detector construction and destruction
occur on the same capture thread, not the GUI thread. This does not reproduce or
prove the cause of the reported Windows access violation; physical Windows
inference/capture restart testing remains outstanding.

## Native crash evidence — dev18

A repeated user report arrived while the dev17 portable workflow was still
running; the installed version was not established. Do not treat that report as
proof either that dev17 fixes the crash or that the user tested dev17.
Native faulthandler stacks are now written to native-crash.log and included in
exported diagnostic bundles. One previous log is retained after the current file
exceeds 2 MB at startup. Capture is best effort: some native failures or external
termination cannot produce Python stacks. A subprocess test exercises the open
descriptor and diagnostic ZIP export without executing a destructive payload.

## Auto-selection double launch — dev19

The new log showed worker join completing, followed by automatic YouTube selection
and duplicate audio initialization errors. Inspection identified a deterministic
second launch route: toggle_start() calls _auto_select_youtube_window(), which
starts a preview as a side effect. toggle_start() then overwrote that live worker
with a recording worker. Qt could destroy a running QThread or both workers could
initialize native audio/capture simultaneously. No chessboard is needed.

Window selection now accepts start_preview=False for explicit Start, so the
caller launches exactly one recording worker. Startup/timer selection retains
its automatic preview behavior. The regression uses real controlled QThreads,
a mocked YouTube window, and no board/OCR. It asserts exactly two workers across
automatic initial preview → Stop → Start: the initial preview and one recorder.
Earlier restart tests disabled auto-window selection and therefore missed this
path. Audio device lookup errors in the log remain recoverable audio failures;
this change does not claim to repair every Windows device enumeration problem.
