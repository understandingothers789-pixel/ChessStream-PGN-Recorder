# Comprehensive check — October 24, 2026

Development build **1.6.24-dev7**, reviewed from dev6 (`f45484c`). Main is not changed. The corresponding push workflow checks Windows tests and produces the portable artifact; the final delivery links that workflow. Machine-readable results: [comprehensive-check-2026-10-24.json](comprehensive-check-2026-10-24.json).

## Confirmed issues fixed

1. **Stale setup headers could corrupt PGN export.** Exporting a standard-start game with an old `FEN`/`SetUp` header made the PGN reader interpret otherwise correct moves from the wrong position. Export now derives these tags exclusively from the actual initial board. Explicit midgame roots still export their true FEN. Both cases have regression tests.
2. **Integrity checks could inspect another thread's partial edit.** The recording consistency check previously read shared state outside the manager lock. A test reproduced a spurious checkpoint rollback while a second thread held an unfinished edit. Checks and the complete persistence operation now hold the existing reentrant lock, and that test passes without rollback.
3. **Two simultaneous faults defeated the error path.** A corrupt accepted move list plus a NaN recognition frame caused the worker to call `snapshot()` on corrupt history while reporting the bad frame. Integrity recovery now runs before any error snapshot. A combined-fault test verifies restoration and an unchanged saved PGN.
4. **Direct processing lacked the worker's input validation.** Non-GUI callers of `GameManager.process()` now get the same structural recognition checks before lifecycle or search uses the frame. Invalid scores preserve the accepted PGN and invalidate pending recovery/audio evidence.

5. **Library join validation had a timing gap.** UI source checks ran before acquiring the manager lock. Saving a combined PGN now rechecks source content and existence under that lock and refuses a non-activating library join if a source has become active. Tests cover changed, deleted and newly active sources; no combined record is written in those cases.

Files changed: `chessstream/games.py`, `chessstream/capture.py`, `tests/test_pipeline_faults.py`, new `tests/test_export_setup.py`, version labels in `pyproject.toml`/`chessstream/gui.py`, and documentation. No model weights, sound fingerprints, or dependency pins changed.

## Verification

| Area | Result and scope |
|---|---|
| Full local suite | **273 passed**, 10.83 s, in a fresh environment with the currently pinned runtime libraries. No tests deleted. |
| Recognition/continuity corpus | **116 board positions, zero square errors; 14/14 sequences correct**. Five deliberately weakened classifier cases recovered (old exact-label baseline 0/5). This is a fixed corpus, not a general accuracy estimate. |
| End-to-end real-image replay | Four games, **64 frames**, correct complete sequences and PGN round trips; every-other-frame runs also matched. Final pending moves were explicitly confirmed as required by the evaluator. |
| Built-in audio | Seven published default sounds × three offsets: **21/21 controlled trials** detected one cue with reduced volume and a quiet background tone. No user learning or audio saving required. Real commentary remains unmeasured. |
| Legal search | Same complete shortest-path sets as the pinned pre-optimization implementation in the three benchmark cases: 1, 2, and 29 paths. Search node counts remain reduced. Timings came from shared cloud CPU with concurrent checks, so they are not a live-recording FPS comparison. |
| Combined fault handling | False audio plus an impossible disappearing piece; audio polling/cleanup failures during recording; malformed scores; transient name/clock OCR errors; corrupt board/accepted moves; simultaneous corrupt history and NaN frame; partial concurrent edit. Saved PGNs were preserved, and valid subsequent frames resumed the tested recordings. |
| Export failure | Injected an `OSError` during atomic PGN file export. SQLite retained the accepted game; a later `persist()` repaired the file. This is not a physical disk-full or power-loss test. |
| Abrupt process exit | A separate recorder process committed three plies and exited with `os._exit(0)`. Reopening SQLite passed `PRAGMA integrity_check`; accepted moves, full FEN, PGN and diagnostic ZIP were correct. Zero screenshots were saved. |
| Desktop UI | Offscreen Qt 6.12 launch rendered dev7 with the audio checkbox and no learning buttons. Existing interaction tests cover navigation, source ranking, history review, context actions, multiselect screenshot deletion, and older-PGN joins during recording. |

## Dependency and security review

A fresh runtime closure contains 16 packages including the Windows-only audio pin: NumPy 2.2.6; OpenCV headless 4.12.0.88; chess 1.11.2; PySide6-Essentials/shiboken6 6.12.0; mss 10.0.0; platformdirs 4.3.7; Pillow 13.0.0; psutil 7.0.0; ONNX Runtime 1.24.4; PyAudioWPatch 0.2.12.9; flatbuffers 25.12.19; protobuf 7.36.2; packaging 26.3; sympy 1.14.0; mpmath 1.3.0. The Windows-only package was explicitly included in the advisory query, rather than skipped by Linux environment markers. **No known package advisories were returned for these versions.** `pip check` passed.

The old workspace venv still contains earlier native library versions; it was not used for the final local check. Windows CI installs project pins afresh. The native dependency fixes and vendor advisories from the [October 23 audit](COMPREHENSIVE-CHECK-2026-10-23.md) remain relevant. Package advisory databases do not prove that embedded codecs, PortAudio or all native paths are vulnerability-free.

Bandit reported 11 findings (no high-severity findings), all manually reviewed: SQL strings assemble fixed clause fragments while binding data values; the static desktop PowerShell command receives structured JSON through stdin; Windows modifier constants resemble passwords to the scanner. No runtime configuration `eval`, `exec`, or Pickle loading was found; `.exec()` calls are Qt UI methods. The developer-only sound regeneration script uses an explicit ffmpeg argument list, without a shell, and is not called by the desktop app.

Bundled model hashes, non-pickle bounded template loading, trusted custom model directories, bounded screenshot decoding/path handling, and explicitly disabled ONNX telemetry remain in place. App inference and audio matching use local inputs; the runtime does not download sound samples or start a network service. Python socket-blocking tests cover model/OCR inference; they do not inspect every native operating-system event.

PaddleOCR, PaddleX, PaddlePaddle and Paddle Serving are absent from the runtime dependency closure and app imports. Published records for **CVE-2026-108961** and **CVE-2024-0917** were rechecked; the affected Paddle code is not reachable in this application. The separately maintained safe-scale helper/patch remains tested, rather than installing PaddleX just to apply it.

## Remaining limits

Physical Windows fullscreen/DPI/window replacement, real speaker/headset loopback, long commentary-heavy multi-game sessions, installer/uninstaller behavior and long-duration memory/storage growth still require hardware acceptance. Consistently wrong but legally plausible visual readings can escape these checks. Ambiguous unobserved move orders remain pending; the recorder does not prove historical accuracy from a matching endpoint alone. Observation/audit tables remain uncapped, the distribution is unsigned, and the transitive supply chain is not fully locked by hashes. No claim of complete security or elimination of every recording error is made.
