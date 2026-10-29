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
