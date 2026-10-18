# Architecture and trust boundaries

## Capture and recognition

The GUI never performs capture, inference or legal search. `RecordingWorker` owns its MSS instance in a QThread. A thread-safe command queue applies region changes, calibration and manual corrections. Pausing suppresses capture; stopping finishes the current bounded operation and saves the game.

Every sampled frame can contribute evidence. The default position mode saves only settled classifications and suppresses consecutive PNGs with the same recognized placement and game ID; pixel changes from arrows/cursors do not bypass that rule. Repetitions after intervening positions and a new game are saved again. Hidden/unstable views are skipped. Optional interval mode uses an independent permanent screenshot clock, with separate opt-in byte deduplication. Both policies run after recognition and game processing. Neither deletes existing images. Changed frames are recognized; visually unchanged frames reuse the local model output while advancing stability checks.

OpenCV board detection scores alternating backgrounds across candidate rectangles. The default piece recognizer is the pinned MIT-licensed fenshot CNN. It receives floating-point grayscale board pixels, bilinearly resized to 256×256, split into flattened 32×32 tiles in a1..h8 order. Its native `1KQRBNPkqrbnp` output is already softmax-normalized and is explicitly reordered to the application's `.PNBRQKpnbrqk` labels. It uses ONNX Runtime with two CPU threads and no network. A low-confidence image is retried with modest global contrast; this view is selected only if all 64 predicted labels agree with the original and the weakest score improves. If views disagree, their disputed distributions are averaged to preserve uncertainty.

Before initialization, every square must meet max(0.80, configured threshold), and the position must pass chess validity checks. The GUI shows a pending placeholder until that root is accepted. The weakest score and names of uncertain squares are displayed; an average cannot hide missing pieces. Scores are model outputs, not measured accuracy guarantees. Live and local-video capture share the same recognizer factory. Old user calibration files cannot silently override the new default. User-selected calibrated templates and user-supplied RGB/logit ONNX models retain separate explicit modes and contracts.

Orientation is evaluated in both directions against the prior verified position. Initial orientation uses rank distribution; a one-click override is provided. Stability requires repeated evidence: two matching classifications, or a byte-identical confirmation capture after inference and at least 80 ms since capture. This avoids waiting for a second full classification on a stable fast-game position. Non-adaptive mode also takes an unsaved confirmation frame. Recognition caching requires exact pixel equality, so subtle changes are not suppressed by a perceptual threshold.

## Reconstruction

`LegalSearcher` enumerates legal moves using python-chess, iteratively deepening until the shortest matching depth is found. It examines every candidate at that depth before declaring the set exhaustive. Mismatch-square bounds and final-ply affected-square checks prune provably impossible paths, including special castling and en passant square changes. Time, node and path-count exhaustion invalidate any uniqueness claim. A candidate cannot change a square whose classification is below threshold: unknown unchanged pieces may retain their earlier identity, but an unseen source/destination cannot prove a move.

`Reconstructor` keeps independent histories. A shared prefix is committed only after every surviving path supports it. Production defaults additionally withhold the latest ply until an opponent reply; repeated frames or elapsed time never confirm it. A fully searched direct transition from the verified board can replace a single unconfirmed hover or prune longer unsupported detours, while compatible equal-depth move-order histories remain separate. This uses the shortest-gap assumption and cannot revise verified moves. The protection and pending branches survive serialization. One explicit manual confirmation can commit a final pending ply; export, stop and EOF cannot. Histories that transpose retain separate move lists even when their board states coincide. Searches from identical states share work without merging their historical paths. Low-confidence, obstructed, unmatched and historical-review frames do not overwrite the verified board. Full branch state is serialized for recovery. Manual selection and SAN corrections are audited. A stable, high-confidence board that remains unmatched, rewound or path-ambiguous for the configured interval can close the old record and start a separate PGN at the visible FEN. Unique one-ply held-move candidates are excluded to protect against drag hovers. The earlier PGN remains intact. Screenshots and recognition observations from the checkpoint are associated with the new segment, and the first legal move can resolve side to move.

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

## Visible game context and annotation trees

The capture worker scans the selected source (not just the board crop) at most once per second with pinned offline PP-OCRv4 DB/CTC models. Exact unchanged source pixels reuse text inference while debounce still requires temporal evidence. Spatial association assigns outside-board clocks/names to colors; names need three repeated scans. Relative You Won/Lost messages use an explicit player-color setting or the remembered initial bottom color, never the current flipped orientation. Result messages need repeated evidence. A unique final pending move needs positive evidence on every changed square, even if the popup obstructs unrelated squares. A terminal latch survives restart, freezes played moves, and arms a new standard board. A recent dual-clock reset and stable changed names contribute boundary evidence.

`game_extras.py` stores observed clocks by full resulting FEN and binds them to verified plies only after the corresponding move becomes verified. PGN output uses standard `[%clk]` comments. No exact release times or missing readings are fabricated. Completed-game review uses a separate bounded reconstructor anchored to a known main-line position. Verified review moves enter a PGN variation tree, never the recorded move list. `pgn_tools.py` merges annotations onto the authoritative main line; it refuses silent main-line extensions. The viewer navigates nested trees and preserves annotations, clocks, imports and header edits.

`diagnostics.py` rotates application logs and exports a user-requested ZIP of recent database evidence, audit records, settings, game states and PGNs. No screenshot bytes are included. The database remains the durable source of capture evidence.
