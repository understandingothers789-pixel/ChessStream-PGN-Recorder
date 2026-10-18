# Architecture and trust boundaries

## Capture and recognition

The GUI never performs capture, inference or legal search. `RecordingWorker` owns its MSS instance in a QThread. A thread-safe command queue applies region changes, calibration and manual corrections. Pausing suppresses capture; stopping finishes the current bounded operation and saves the game.

The permanent screenshot clock is independent from the adaptive analysis clock. Every sampled frame can contribute evidence; only an interval-due frame is persisted as a PNG. Exact deduplication runs after recognition, and only when explicitly enabled. Changed frames are recognized; visually unchanged frames reuse the local model output while advancing stability checks.

OpenCV board detection scores alternating backgrounds across candidate rectangles. The default piece recognizer is the pinned MIT-licensed fenshot CNN. It receives floating-point grayscale board pixels, bilinearly resized to 256×256, split into flattened 32×32 tiles in a1..h8 order. Its native `1KQRBNPkqrbnp` output is already softmax-normalized and is explicitly reordered to the application's `.PNBRQKpnbrqk` labels. It uses ONNX Runtime with two CPU threads and no network. A low-confidence image is retried with modest global contrast; this view is selected only if all 64 predicted labels agree with the original and the weakest score improves. If views disagree, their disputed distributions are averaged to preserve uncertainty.

Before initialization, every square must meet max(0.80, configured threshold), and the position must pass chess validity checks. The GUI shows a pending placeholder until that root is accepted. The weakest score and names of uncertain squares are displayed; an average cannot hide missing pieces. Scores are model outputs, not measured accuracy guarantees. Live and local-video capture share the same recognizer factory. Old user calibration files cannot silently override the new default. User-selected calibrated templates and user-supplied RGB/logit ONNX models retain separate explicit modes and contracts.

Orientation is evaluated in both directions against the prior verified position. Initial orientation uses rank distribution; a one-click override is provided. Stability requires repeated evidence: two matching classifications, or a byte-identical confirmation capture after inference and at least 80 ms since capture. This avoids waiting for a second full classification on a stable fast-game position. Non-adaptive mode also takes an unsaved confirmation frame. Recognition caching requires exact pixel equality, so subtle changes are not suppressed by a perceptual threshold.

## Reconstruction

`LegalSearcher` enumerates legal moves using python-chess, iteratively deepening until the shortest matching depth is found. It examines every candidate at that depth before declaring the set exhaustive. Mismatch-square bounds and final-ply affected-square checks prune provably impossible paths, including special castling and en passant square changes. Time, node and path-count exhaustion invalidate any uniqueness claim.

`Reconstructor` keeps independent histories. A shared prefix is committed only after every surviving path supports it. Histories that transpose retain separate move lists even when their board states coincide. Searches from identical states share work without merging their historical paths. Low-confidence, obstructed, unmatched and historical-review frames do not overwrite the verified board. Full branch state is serialized for recovery. Manual selection and SAN corrections are audited.

Search follows a shortest-legal-gap assumption, which cannot recover invisible reversible cycles. The same assumption compares both initial turn candidates for midgame starts. Castling and en passant rights cannot be guessed from piece placement; an exact initial FEN can provide them.

## Games and PGN

`GameManager` recognizes standard starts, board-provable outcomes and historical reviews. An uncompleted game followed by a reset remains preserved until a different legal opening establishes a likely new game or the user confirms the transition. A separate candidate reconstruction follows the possible new game in parallel as state, not as another process. Screenshot associations are moved to the new game's directory when the reset is classified.

Only committed moves are added to PGNs. python-chess generates SAN and standard FEN/SetUp headers. Headers are sanitized for PGN serialization. Internal PGNs are atomically replaced after state changes, not repeatedly rewritten for identical frames. Optional external exports are additional independent copies. SQLite remains the authoritative recoverable state if a crash falls between database commit and autosave replacement.

## Storage and retention

SQLite uses WAL, foreign keys and FULL synchronous transactions. Image records contain UTC timestamps, sequence, session/game, path, hash, byte count, observed placement, similarity and verified-ply association. Recognition evidence is persisted separately on position/status changes, including uncertainty from temporary frames. PNGs contain no embedded metadata requirement; metadata is in SQLite.

Deletion accepts an allowlisted scope, not arbitrary SQL or file paths. Resolved paths must remain under screenshot storage. Each file is marked deleted only after unlink succeeds, so interrupted jobs retry. Bulk deletion holds the storage lock for one file at a time and rechecks scope after game reassignment. Scheduled maintenance runs in its own background task, allowing capture and new evidence writes to continue during large cleanups. Durable jobs are UTC timestamps with explicit scope and completion/error fields. Retention is zero/disabled by default. The UI shows the estimated affected bytes and requires confirmation before destructive bulk actions or enabling age retention. Deleting a game sets screenshot references to null rather than cascading image deletion.

## Optional ONNX contract

Install `pip install -e '.[onnx]'`. Input is float32 RGB normalized to `[0,1]`, NCHW `[N,3,H,W]`, with a dynamic batch of 64 or fixed batch one. Output is `[N,13]` logits in this exact order:

```text
. P N B R Q K p n b r q k
```

Uppercase is white, lowercase black, dot empty. The adapter selects CPU execution and two intra-op threads. A model with a different label order, normalization, input layout or output probability convention must be converted first. No universal-model accuracy claim accompanies this interface.
