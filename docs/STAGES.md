# Implementation and verification stages

## Stage 1 — Capture and recognition

Implemented MSS region/monitor/window capture, DPI-aware Windows source coordinates, region drawing/adjustment, OpenCV localization, bundled offline templates, calibration and orientation handling. Confirmed 64-square recognition against real Chromium captures from Lichess and Chess.com. Added full-page localization tests, not only pre-cropped board tests. Browser fixture capture is reproducible.

## Stage 2 — Reconstruction and continuous PGN

Implemented bounded legal search, multi-ply gaps, special moves, stable evidence, ambiguity branches, shared-prefix commits and crash serialization. Tests exercise castling, en passant, underpromotion, captures, repeated positions, invisible ambiguity, node exhaustion, historical rewinds and FEN/SAN/PGN round trips. A midgame turn inference test exposed an initial-root search issue, which was fixed by comparing roots at the same depth. Only exhaustive matched-depth searches commit moves.

## Stage 3 — Desktop, game detection and library

Implemented the PySide6 desktop interface, asynchronous capture/inference, source overlays, live preview and board, SAN list, competing paths and manual corrections, conservative new-game/reset detection, game library, metadata editing, move review, import/export and recovery. Rendered and visually inspected the actual Qt application offscreen. The live view contains no prerecorded demonstration moves; screenshots shown in documentation are generated separately from test fixtures.

## Stage 4 — Screenshots, review and retention

Implemented session/game PNG storage and separate SQLite metadata, thumbnails/timeline/full-image review, timestamp/date/range/session/game deletion, future UTC deletion jobs, restart catch-up, cancellation, age retention, usage estimates and independent game deletion. Automated tests close and reopen storage before running overdue jobs and assert PGN preservation. No retention was enabled by default. Version 1.2 adds position-based screenshot suppression by default, without deleting existing files.

## Stage 5 — Evaluation, packaging and polish

Implemented optional adaptive temporary frames, unchanged-image recognition reuse, opt-in exact deduplication, optional ONNX inference, local-video replay, Windows global hotkeys, bounded worker load, atomic autosave only on state changes, user documentation, licenses and Windows packaging.

The end-to-end benchmark uses 64 actual browser board captures: three completed Lichess games and one Chess.com opening. It checks all 60 plies and PGN importability, including alternate-frame omission and real UI board flips. All positions and captured sequences matched in this controlled set. Measurements and limits are in `evaluation.json`; they do not establish arbitrary-stream accuracy.

An actual headed-browser/MSS desktop test exposed inclusive Canny rectangle widths and an off-by-one-file false localization. Grid-size alternatives, all-square error penalties and original-pixel refinement fixed it; the failure image is retained as a regression fixture. The production worker then reconstructed all eight live test plies with a real flip and pause/resume, independently saving interval screenshots. `live-capture-result.json` records this Linux acceptance. Automated tests additionally cover three consecutive actual-image games, compressed MJPEG replay, real UI arrows/legal-move dots, strict retention boundaries and malformed deletion scopes.

The Windows installer is assembled from official CPython and unmodified Windows dependency wheels using NSIS. This Linux host cannot establish that installation, screen scaling, global hotkeys or capture work on Windows 11. The supplied Windows workflow adds packaged-runtime imports and GUI smoke tests, but it has not been executed here. Final Windows acceptance remains outstanding and is explicitly documented.

## Version 1.1 recognition correction

The original template default failed on common shaded pieces and textures. The production path now uses the pinned fenshot screenshot CNN and bundled ONNX Runtime. All-square startup gating, an honest pending-state preview, weakest-score display and explicit calibration mode prevent low-confidence roots being silently frozen. The new real-theme regression corpus records five sequences, including Chess.com Ocean/Walnut and orange Burled Wood, arrows, dragging, a pointer, flips and compression. See recognition-v1.1.json for measured results and limits. The original version 1.0 measurements above describe that earlier implementation.

## Version 1.2 provisional-move and storage correction

The reported recording ended at `5...Bb6`; its screenshot showed a direct `Ng5 Nh6 Qf3` continuation competing with unverified reversible bishop detours. The new recovery rechecks direct legal evidence from the verified prefix and can remove unsupported detours without rewriting verified moves. Changed squares must be positively observed. Equal-depth move-order ambiguity remains unresolved.

Held-piece safety now defaults to withholding the latest ply until an opponent response or explicit confirmation. Repeated legal hover images never verify the held move. Real native Chess.com drag fixtures keep a bishop held over `c5`, move it to `b4`, release there and then play `a3`; only `Bb4` is verified automatically. A separate controlled five-second legal-hover test exercises the same rule. Native blue-arrow captures after `Bb6` test the reported continuation. These are controlled reproductions, not byte-identical copies of inline user uploads or a full Hikaru video benchmark.

Screenshot storage defaults to one image per settled recognized position. A headed Chromium/MSS run processed 54 updates and saved five images, verified seven of eight plies automatically, then explicitly confirmed the final ply. Evaluators now count the final confirmation as intervention instead of claiming fully unattended completion. EOF, stop and restart preserve pending moves. Existing images and PGNs are not deleted or rewritten.

The portable distribution remains a ZIP with an app-local Python runtime and command launcher. GitHub's Windows workflow gates each tagged publication on source tests, bundled inference, GUI rendering and launcher validation. Physical Windows 11 capture/scaling and long-duration stream acceptance remain outstanding.

## Version 1.3 visible-position recovery

A clear board that remains unmatched, a rewind, or a multi-path ambiguity now starts a separate FEN-based PGN after a configurable 15-second timeout. The previous PGN keeps its verified moves and unresolved-gap note. The checkpoint position and its screenshot are associated with the new segment. A single legal held-move candidate is excluded from this timeout so a drag hover is not auto-verified. Users can start a segment immediately with **Start PGN from visible FEN**, or copy the recognized position with **Copy visible FEN**. If turn is unknown, the copy action asks White or Black; automatic continuation resolves it from the first legal move. Earlier moves, castling rights, and en passant history cannot be inferred from the image.

## Version 1.4 results, context, variations and diagnostics

Added local result/name/clock OCR with pinned offline models and repeated evidence, safe result-based confirmation of a final pending move, a terminal boundary latch, clock/name-based boundary evidence, and bounded post-game side-variation capture. The game library supports manual nested SAN variations, comments, branch deletion, and board navigation, preserving annotations and observed `[%clk]` comments through export, edits and recovery. Diagnostics expose rotating logs and a support bundle without images. Native Chess.com bot UI captures exercise clocks, names, a genuine game-aborted dialog and a named-winner resignation. A controlled d6 regression reproduces the supplied screenshot's obscured squares and confirms the supported final move on abandonment evidence. `context-v1.4.json` contains measured OCR latency/CPU/memory and controlled-case results; physical Windows stream acceptance remains separate.

## Version 1.5 automatic context margin

A tight 64-square selection now automatically samples a temporary nearby margin for names/clocks. Tests cover source-pixel reuse, opt-out, board/text frame consistency, negative monitor origins, resize geometry, masked names and settings persistence. A production-worker regression reads names/clocks outside the selected board while saving a single board-only PNG. An actual X11/MSS check displays the retained native capture at two moved/resized window sizes and reads both names/clocks from real screen pixels. That check exposed an OCR punctuation artifact after a rating, corrected by normalizing invalid trailing separators. The linked YouTube first game was inaccessible in this environment and is not claimed as tested.
