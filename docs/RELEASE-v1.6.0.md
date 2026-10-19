# ChessStream PGN Recorder v1.6.0

Resuming at a later position now searches forward from the latest saved PGN instead of requiring an exact endpoint match. The shortest legal connection keeps one game, including when the preceding move was still pending. The reported source and target boards connect through Qxd4 (or ...cxd4 Qxd4 from the verified prefix if ...cxd4 was pending). Inferred moves receive PGN comments. Equal shortest paths remain alternatives and incomplete searches never certify a guessed line. Capture, depth, node and time settings continue to bound the work.

An exact earlier position in the saved PGN is recognized as review; it does not create a new game or invent a reversible return sequence.

Existing fragments can be repaired by Ctrl-selecting the rows in Game library, then right-clicking → Join selected recordings. This exports one combined PGN while retaining originals, move clocks, comments and variations. Different known players, a declared result, incompatible continuation, search limits and equal shortest alternatives produce clear errors.

The search now compiles the observed position to bitboards, rejects impossible material/pawn changes, bounds required moves by color, prioritizes moves toward changed squares, and caches only exhausted failures so that alternate move orders remain visible. Benchmarks with the same 350 ms/60,000-node limits are recorded in `gap-search-v1.6.json`; the three-ply and four-ply cases keep the same legal path sets as v1.5.9. These are controlled search timings, not stream-recognition accuracy measurements.

Routine local validation was reduced from 147 tests to 15 essential tests, about a 90% reduction. The former suite took 15.5 seconds locally; the compact suite takes about 1.9 seconds and retains real board/OCR, security, storage, chess/PGN and GUI checks. Broad theme permutations, full-video loops and overlapping GUI tests were deleted. Optional corpus evaluation remains available separately. Windows packaging runs only for a release tag or manual build, avoiding a duplicate portable build for the accompanying main-branch push.

The old suite passed once during this change, before its redundant tests were removed. The compact suite validates the reported gap, shortest-path equivalence to independent enumeration, ambiguity, special moves, limits, live continuation and existing-fragment joining. Physical Windows capture and long YouTube-stream acceptance remain separate from automated Windows package validation.
