# Implementation and verification stages

## Stage 1 — Capture and recognition

Implemented MSS region/monitor/window capture, DPI-aware Windows source coordinates, region drawing/adjustment, OpenCV localization, bundled offline templates, calibration and orientation handling. Confirmed 64-square recognition against real Chromium captures from Lichess and Chess.com. Added full-page localization tests, not only pre-cropped board tests. Browser fixture capture is reproducible.

## Stage 2 — Reconstruction and continuous PGN

Implemented bounded legal search, multi-ply gaps, special moves, stable evidence, ambiguity branches, shared-prefix commits and crash serialization. Tests exercise castling, en passant, underpromotion, captures, repeated positions, invisible ambiguity, node exhaustion, historical rewinds and FEN/SAN/PGN round trips. A midgame turn inference test exposed an initial-root search issue, which was fixed by comparing roots at the same depth. Only exhaustive matched-depth searches commit moves.

## Stage 3 — Desktop, game detection and library

Implemented the PySide6 desktop interface, asynchronous capture/inference, source overlays, live preview and board, SAN list, competing paths and manual corrections, conservative new-game/reset detection, game library, metadata editing, move review, import/export and recovery. Rendered and visually inspected the actual Qt application offscreen. The live view contains no prerecorded demonstration moves; screenshots shown in documentation are generated separately from test fixtures.

## Stage 4 — Screenshots, review and retention

Implemented session/game PNG storage and separate SQLite metadata, thumbnails/timeline/full-image review, timestamp/date/range/session/game deletion, future UTC deletion jobs, restart catch-up, cancellation, age retention, usage estimates and independent game deletion. Automated tests close and reopen storage before running overdue jobs and assert PGN preservation. No retention or deduplication is enabled by default.

## Stage 5 — Evaluation, packaging and polish

Implemented optional adaptive temporary frames, unchanged-image recognition reuse, opt-in exact deduplication, optional ONNX inference, local-video replay, Windows global hotkeys, bounded worker load, atomic autosave only on state changes, user documentation, licenses and Windows packaging.

The end-to-end benchmark uses 64 actual browser board captures: three completed Lichess games and one Chess.com opening. It checks all 60 plies and PGN importability, including alternate-frame omission and real UI board flips. All positions and captured sequences matched in this controlled set. Measurements and limits are in `evaluation.json`; they do not establish arbitrary-stream accuracy.

An actual headed-browser/MSS desktop test exposed inclusive Canny rectangle widths and an off-by-one-file false localization. Grid-size alternatives, all-square error penalties and original-pixel refinement fixed it; the failure image is retained as a regression fixture. The production worker then reconstructed all eight live test plies with a real flip and pause/resume, independently saving interval screenshots. `live-capture-result.json` records this Linux acceptance. Automated tests additionally cover three consecutive actual-image games, compressed MJPEG replay, real UI arrows/legal-move dots, strict retention boundaries and malformed deletion scopes.

The Windows installer is assembled from official CPython and unmodified Windows dependency wheels using NSIS. This Linux host cannot establish that installation, screen scaling, global hotkeys or capture work on Windows 11. The supplied Windows workflow adds packaged-runtime imports and GUI smoke tests, but it has not been executed here. Final Windows acceptance remains outstanding and is explicitly documented.
