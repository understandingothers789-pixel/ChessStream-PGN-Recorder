# ChessStream PGN Recorder user guide

## Download and launch

Download `ChessStream-PGN-Recorder-Portable.zip` from the repository's GitHub Releases page. Extract it to Documents or another writable folder, then open `Launch ChessStream.cmd`. No installer, administrator rights or separate Python setup is required. If Windows blocks the downloaded launcher, right-click the ZIP → Properties → Unblock (if offered), apply, then extract again. An organization-managed block requires the device administrator; do not disable system security.

On Windows, the first launch creates or refreshes a **ChessStream PGN Recorder** desktop shortcut with the app's knight-and-play icon. Use that shortcut for everyday launches. It points to this extracted copy, so launch an updated copy once to refresh the shortcut after moving or updating the app. **Settings → Hotkeys & help → Create / refresh desktop shortcut** recreates it if needed. Keep the extracted app folder in place. The generic icon of a `.cmd` file or Python itself is independent of the ChessStream desktop shortcut.

## First recording

Keep the browser and board visible. Put ChessStream beside it or on another monitor; a window placed over the board becomes part of the screenshot.

ChessStream automatically selects the most chess-related visible YouTube window and arms recording. The untouched initial board stays in preview. A clear playable position starts a PGN automatically; a first position already in progress uses its visible FEN by default. Settings → Automatic recording disables this behavior. Start recording still works manually. Keep the board visible; Select capture region and the Window/Monitor controls remain available. The automatic context margin reads nearby names and clocks without requiring them inside a tight board crop.

The left board is what the screen contains. The middle board previews the highest-likelihood legal candidate, comparing the classifier score on each square; recent clock movement can break close ties but never confirms a move. It marks its latest move in amber while provisional and can change as a dragged piece moves between squares. The move list uses checkmarks for observed reconstructed SAN, **≈** for guessed opening moves included in the PGN, and **…** for a pending move still excluded from the PGN. **PGN plies** counts the included moves. **Weakest square score** shows the lowest classifier score among all 64 squares, not an accuracy guarantee. An arbitrary first-position FEN requires every square to meet 80% (or the configured threshold, if higher); a short standard-opening hypothesis can carry up to two uncertain unchanged squares. Uncertain squares are named below the capture. Screenshot image files are only written if you enable image saving in Settings. A ply is one move by one player, so 60 plies means 30 full moves. **Copy PGN**, **Export PGN**, and **Copy FEN** sit above the move list. Right-click the move list for the same actions; this keeps PGN access beside the board even when the page needs scrolling.

## Piece sets and orientation

Click a move in the live move list to show the position after that move on the reconstructed board. With the move list focused, the **left and right arrow keys** step through PGN plies in order, including across row boundaries. The heading identifies review mode; capture and PGN recording continue. The selected position remains visible as new moves arrive. **Return to live board** restores the current preview. A new active game or a correction that replaces the selected prefix also returns the display to live. Move numbers alone do not change the board.

During recording, **Continuity check** can identify up to two weakly misrecognized squares, such as a queen suddenly appearing empty or becoming a knight. The recorder retains its previous legal piece on those squares while checking a short continuation. A disputed square is treated as unknown; it cannot supply the missing source or destination of a move. The live warning names the squares, diagnostics retain the raw reading, and moves verified using this continuity assumption receive a PGN comment. Strong contradictions and heavy obstruction still wait for more evidence. This works on position data without saving screenshot images.

The default bundled screenshot model supports varied shaded pieces, board textures and colors. Calibration is not required for the tested Neo and Ocean sets. For an unsupported set, the optional **Calibrate piece set** command switches to manually learned templates:

1. Display a genuine standard starting position with all pieces on their original squares.
2. Start capture and choose **Calibrate piece set**.
3. Confirm White or Black at the bottom. Do not confirm this on a midgame board.
4. Verify the reconstructed preview. Calibration stays local under `custom-templates.npz`. Return to **Settings → Piece recognition → Bundled screenshot model** to leave template mode. Calibration files from version 1.0 are not automatically activated by later versions.

Choose **Flip orientation** if automatic detection is wrong. Settings can lock White/Black at the bottom or restore Auto. Automatic mode compares both orientations to the existing position and handles a board flip without adding chess moves.

An optional compatible model can be added in **Settings → Custom ONNX model → Import model**. ChessStream copies it into the private app data `models` folder, separate from screenshots and settings. Only use models you trust. Imported custom models must be self-contained ONNX files under 512 MiB.

## Capture options

**Monitor** searches a whole selected monitor; **Window** follows a visible application's client area on Windows. Automatic YouTube selection uses the same tracked-window mode. A manual source selection takes precedence during the current run. Tight regions reduce work. A Windows drawn region remembers its containing window so the worker can attempt full-window reacquisition after a move/resize/fullscreen change.

**Adjust** opens an overlay while capture is temporarily paused. Drag to move it, drag its bottom/right edge to resize, then press Enter or double-click to apply. Esc cancels. Use a new drawing when moving to another monitor. Window tracking can follow source size changes; minimized or closed windows pause source processing until available again.

**Screenshots → Per position** is the default image cadence, but image saving itself is off by default. Enable **Settings → Storage & saving → Save screenshot images to disk while recording** to write review images. Captures are still analyzed in memory when saving is off, so move reconstruction and automatic PGN joining continue to work. When saving is enabled, one image is kept when a recognized position settles, then further images are skipped while the latest placement is unchanged. Arrows, highlights, cursors, fullscreen/layout changes and texture changes alone do not create duplicate position-mode screenshots. A repeated position after intervening recognized moves is saved again. Existing images are never removed by this setting.

Select **Screenshots → At interval** to save at the configured interval (default **one second**), including unmatched board views. When a stable recognized board matches the latest recognized position, the duplicate is skipped even in interval mode. Settings also offers opt-in byte-identical image deduplication for this mode.

Adaptive recognition analyzes up to **six temporary frames per second** by default, independently of permanent image storage. Useful evidence is retained as database metadata. Disable adaptive recognition for lower load; a short unsaved confirmation capture still checks animation stability. Neither screenshot mode disables move analysis to save disk space.

**Pause** stops capture; **Resume** continues the same game. **Stop** saves and closes the recording. Use Game library → Resume recording to continue a saved game. On a new start, ChessStream checks the latest chronologically started recording for an exact position match or a shortest legal continuation to the current board. It keeps that PGN when a complete bounded search connects the positions; pending hovers are reconsidered from the verified prefix. If equal shortest paths reach the same position, the recorder keeps one repeatable choice: same-square recaptures first, then consecutive captures, capture count, and stable move order. The PGN labels this as inferred. Completed results, changed visible opponents and reset clocks block forward bridging where that evidence is available. Older games are not searched automatically. Matching uses the 64-square placement because turn and FEN rights/counters are not always visible; known rights/history from the saved PGN are retained. The default hotkeys are F8 start/pause/resume, F9 stop, Ctrl+Shift+R region. Windows registers supported sequences globally when available, with focused shortcuts as fallback.

## Uncertainty and stream behavior

**Protect against dragged pieces** is enabled by default. A reply or **0.5 seconds of unchanged recognized position** now accepts the pending move. Timed moves and best-effort gap guesses appear with amber ≈ markers and PGN comments. A held piece may therefore be accepted before release; the latest timed guess retains a saved rollback state so a later one-move alternative can correct it. If a position remains unresolved at three seconds, the recorder logs a recovery error and retries a bounded legal gap search. It may take the first shortest legal match rather than exhaust alternative orders. If no legal match is found, the existing PGN is kept. Pausing, losing the board or reacquiring its layout restarts the half-second timer.

At the end of a game, inspect the visible final move and choose **Confirm final / pending move**. This is an explicit override; use it only after the piece has been released or after reviewing the game. A stable game-ending message can confirm the final pending move when its changed squares remain clearly visible; covered destinations remain pending. Checkmate without an identifiable result message still waits for confirmation. Stop, export, end of video and restart never automatically promote a pending move. Turning the protection off allows immediate confirmation and loses the hover safeguard.

The recorder tries legal sequences across missing frames, up to the configured number of plies, nodes and milliseconds (defaults: four plies, 60,000 nodes, 350 ms). A ply is one player's move. It searches shorter sequences first, then completes the whole first matching depth to detect ties. For example, the shown position after ...cxd4 connects to the later queen-on-d4 position through Qxd4; if ...cxd4 was still pending, the bridge includes both plies. PGN comments label inferred gap moves. The latest move still follows the normal provisional-move protection. Increasing search settings can resolve a larger gap but uses more CPU. Hitting a limit does not certify a partial path.

A resumed view of an exact earlier position in the latest PGN is treated as review. It resumes that game without inserting a reversible sequence to return to the old board.

If sequences with different endpoints fit, the move panel shows competing SAN lines. Later frames can resolve some differences. If equal shortest paths reach the same endpoint, ChessStream chooses one using capture continuity and stable ordering, then marks that choice in the PGN; this preference is a heuristic, not proof of the exact move order. If two histories have already transposed, later boards cannot distinguish their earlier order. Changed source/destination squares need positive visual support; arrows hiding unrelated pieces can be tolerated, but an unseen destination cannot prove a move. Shorter direct legal evidence can replace unverified hover/detour candidates under the documented shortest-gap assumption. It never rewrites the verified prefix. Confirm a sequence only if you know which was played. Unverified alternatives are never included in the main PGN.

**Repair PGN** and **Join previous** are the two compact buttons below the live move list. Hover for an explanation; click to run the action with its result shown inline. Repair removes paired piece round trips only when replaying the retained moves is legal and preserves the final placement, turn, castling rights and legal en passant state. It preserves retained move comments and clocks; analysis branches keep their anchors where the same position survives. The full original PGN and reconstruction state are saved in audit metadata. This can simplify a genuine repetition too, so use it when the recorded detours look wrong. A narrow automatic check also removes unclocked opening detours with inferred evidence or an enemy-back-rank ghost excursion; ordinary observed repetitions stay recorded.

**Join previous** tries the two previous recordings within bounded legal search limits, makes a compatible combined PGN active, retains its pending preview and keeps both originals in the library. A result or incompatible player names can prevent a join. No match is reported inline.

For explicit SAN editing, right-click the live move list → **Edit moves manually…**. This allows undoing recent verified plies and entering a legal replacement sequence. The entire correction is validated before application and the previous state is retained in the audit metadata.

Known earlier positions are treated as likely review/rewind when a short live continuation does not explain them. The recorder follows positions throughout the saved PGN tree, including existing alternative lines. A replay can return to an earlier played position and then branch: stable legal analysis moves are saved as PGN variations, while the played main line and its clocks remain intact. Analysis continuations use the same 0.5-second stability check and a shared bounded search of up to six plies for missing frames. The board preview follows the analysis; the library's Moves, variations viewer and exported PGN include its branches. Temporary menus, advertisements or a hidden board do not overwrite the current game.

When a short temporary recording has both of the same known players as either of the two recent longer games, the recorder checks legal positions and opening prefixes before treating it as separate play. A replay with a different guessed opening order can become a variation in the original PGN. A matched fragment is archived in the database and omitted from the game library and ordinary exports; its original PGN remains available in diagnostic audit evidence. **Join previous** also tries this analysis reconnection. Changed opponents, recent clock resets, explicit game separations and aborted games block automatic replay merging. Matching player names alone never attaches an unrelated position. A long unseen variation may still exceed the search budget; showing its earlier branch point and continuation supplies the missing evidence.

Game identity is decided before move reconstruction, replay matching or background recovery. Repeated opponent changes can identify a separate game without visible clocks. Reset clocks plus an observed board reset and renewed play can identify a rematch without changed names. Increments and video seeks are checked against continuous play and saved history. Merely returning to the initial board does not establish a new game. While evidence is uncertain, the old PGN is protected and up to 24 board observations are held in memory. Confirmed game boundaries receive a separate ID and a visible starting FEN, or a chain of actually witnessed single moves from an observed starting board. A search is never used to bridge a confirmed boundary.

## Game identity and correction controls

The **Game: … ▾** button above the live move list shows the lifecycle state. Its tooltip names the players, identity confidence and the reason for a possible boundary. Detailed evidence is in Diagnostics / logs and exported diagnostic bundles.

- **Automatic game detection** restores the default classifier.
- **Start separate PGN from visible board** preserves the old recording and explicitly starts a new one from the current FEN.
- **Continue current PGN** overrides a suspected identity change; unrelated positions still require a legal connection and cannot silently overwrite the PGN.
- **Treat as analysis / replay** protects played moves and records legally connected review variations.
- **Undo last game switch** restores the previous active PGN and keeps the later record separately. A manual split can also be undone after restarting.
- Click a recorded move, then **Split PGN after selected move** to save the suffix as a separate FEN recording. Its comments, variations and clock offsets are retained, and the original is backed up in audit evidence. Edit player headers in Game library and use Combine selected PGNs for an explicit reassignment/join.

Choose Automatic game detection after a manual Continue or Analysis override when you want automatic switching again. If the same players replay exactly the same opening with invisible/static clocks, the images may not distinguish review from a rematch. Use the Game menu rather than relying on an invented identity.

## Automatic surrounding context

**Settings → Automatic surrounding context** is enabled by default. Once per second, the recorder can capture a small temporary rectangle around the board, adding **18% of the board size on each side**. A 700-pixel board therefore gets up to 126 extra pixels at each edge. The margin is clipped to the visible desktop. Adjust **Context margin on each side** up to 50% for farther-away bars, or turn automatic context off to read only the selected area.

The piece recognizer still receives only the 64 squares. If image saving is enabled, permanent screenshots stay on the board; temporary context pixels are not saved as extra PNGs. When the wider selected source already contains the margin, those pixels are reused. Otherwise one nearby capture supplies both the board and its text, avoiding association of new clocks with old board pixels. The margin follows the board coordinates as existing window/region tracking reacquires the board after layout changes. This is not a guarantee for every fullscreen transition or DPI configuration; use Adjust if tracking loses the source.

Text recognition uses existing pretrained **PaddleOCR PP-OCRv4** models through **ONNX Runtime**, locally on the CPU. OpenCV processes screen pixels; application rules interpret clocks, results and names; python-chess validates moves and writes PGN. No custom OCR training or online inference is required. Cover labels such as NAME BLURRED or DEFINITELY NOT … do not identify the hidden account and remain Unknown, even when their letters are readable. Nearby clocks can still be read.

## Results, clocks and player names

By default, the local bundled OCR models scan the selected source about once per second. English **You Won**, **You Lost**, **White/Black Won**, a recognized winner name, a standalone score, draws, **Game Aborted** and abandonment messages can end a recording after repeated evidence. `1-0`, `0-1` and `1/2-1/2` are standard results; an aborted game or an unidentified winner keeps `*` with an explanatory note. The played main line is frozen and capture stays ready for a new starting board. If the final provisional move's changed squares are visible, the message confirms it even when other squares are covered by the dialog. If its destination is hidden, the PGN result is saved while that move stays unresolved until a clear view or correction.

**You Won / You Lost** describes the account owner. Settings → **Player color for You Won / You Lost** defaults to remembering the bottom color from the beginning of this recording, keeping it across later flips. If you start with the stream already flipped, set White or Black explicitly, or choose Unknown to require a named/color result. Explicit scores and matched visible winner names take precedence. Midgame FEN recovery starts a new segment and remembers its initial bottom color. Review a result if the initial player-color assumption was wrong. Edit Result to `*` to reopen a mistaken completed boundary.

Clocks must be visible near the board, within the automatic context margin or your selected area, outside the 64 squares. Readings are assigned to colors by board orientation and saved as standard `[%clk H:MM:SS]` PGN comments. The first observed reading for a pending move is retained when that move is later verified, rather than using a later clock value. Captures may be about one second after release, or later when a frame is missed. No exact release time, increment, time control, or missing clock value is invented. A skipped intermediate position may have no clock comment.

Names above/below the current board can be read even if clocks are hidden. Clock-adjacent name matching remains available. Names need repeated consistent scans; a single different reading pauses move assignment while it is checked. Missing names retain existing confirmed headers, and a new game with unreadable names uses Unknown. Both clocks are compared across readable observations, including brief missing overlays; small increases, large increments with continuous play and clock discontinuities during historical review do not automatically create a game. Changed opponents and clock evidence can separate a new game even when its board is legally reachable from the old PGN.

## Alternative lines and post-game review

Game library → **Moves & variations** shows the played main line, side variations, clock comments and annotations. Click any move to display its position. The main line stays flat; alternative branches are indented. **PGN text** shows the full export.

Select the position **before** the move you want to replace, choose **Add alternative line**, and enter legal SAN from that position. Add a comment if desired. Nested alternatives work inside other variations. **Edit comment** changes a move/position comment; **Remove alternative line** removes only a side branch, never the played main line. A review annotation cannot extend the actual game after its final recorded move; select an earlier branching position. Explicit played-move corrections are available by right-clicking the live move list → **Edit moves manually…**.

After a result, recognized replays can follow earlier positions and alternative lines without changing the completed result or played moves. Stable new analysis moves are added as variations. The fallback post-game tracker uses 120 seconds by default; recognized replay tracking can continue beyond that window. Setting post-game review to Off disables automatic new analysis for ended games. Resetting the board alone remains uncertain; changed players, corroborated clock resets or subsequent distinct opening evidence can identify another game. Imported PGN variations/comments survive edits and exports.

## Starting in the middle

A first position already in progress starts from its visible FEN by default. Earlier moves are not fabricated. Settings → Unseen opening → Recover unseen opening moves as labeled guesses explicitly enables the older bounded opening-recovery feature. It can choose a legal order with castling and up to two captures, but that order is inferred, not observed. This option does not permit a search across a confirmed game boundary. Starting FENs preserve only known information; turn may require the next legal continuation, and hidden castling/en passant history remains unset unless an exact FEN is supplied.

Resuming an application-created early FEN recording also attempts this prefix repair. If the guessed prefix and existing continuation are legal together, the same game gains the opening; its recorded moves, variations and clock comments remain. The PGN and audit identify the guessed prefix. Imported PGNs and an explicitly configured initial FEN are not automatically rebased.

For a later valid midgame position, the app records from its FEN and infers the turn from subsequent evidence. Positions outside the bounded opening search use this path. Having only a few pieces left on the board is an endgame, not evidence that only a few opening moves occurred. Castling rights and en passant history for arbitrary midgame FENs remain unset. If known, enter the exact full FEN in Settings **before** beginning a new recording, including turn, rights, target and counters.

PGN export uses standard `SetUp` and `FEN` headers. A game awaiting initial-turn inference is provisional and annotated. Use **Copy visible FEN** to send the captured board to Nibbler or another tool. If the board matches a known game position, the app preserves its known turn and rights; otherwise it asks whether White or Black moves and assumes no castling rights or en passant target. The FEN begins the new PGN; moves from before that position are not reconstructed.

## Unmatched positions and automatic recovery

**Settings → Capture & recognition → Switch to unrelated positions** controls the board-only fallback. A clear position that differs substantially and cannot be linked to current play or earlier analysis stays quarantined during the configured new-game delay (five seconds by default), then can start a separate FEN recording. Failed bounded search is evidence, not proof of mathematical impossibility. Small unexplained mismatches remain pending; Warn about a small unresolved mismatch after controls a reminder to use the Game menu. It no longer forces a new PGN for a small recognition disagreement.

The search is bounded: failure to find a connection does not prove mathematical impossibility. Weak, invalid, animated or obscured boards do not trigger this general split. A supported opening can retain up to two weak **unchanged starting squares**, including in the longer opening search, only when the original label has model support and none of the inferred moves touch those squares. Those assumptions are shown in diagnostics and the PGN note.

Within a confirmed game, skipped frames can still use bounded legal gap reconstruction and are marked inferred. A different identity or uncertain boundary blocks that recovery first. On a fresh launch, a saved game is reused automatically only with matching known players and an unambiguous exact saved position; use Game library → Resume recording when choosing the intended saved game yourself. A prior established endpoint with matching visible identity can also identify a return to another previously watched game. A deliberate game separation blocks ordinary automatic joins. Explicit library combining, Game → Undo last game switch and manual corrections remain available.

A single legal move waiting for the opponent remains provisional and is excluded from this timeout so a dragged piece does not become a move just because it sat still. **Copy visible FEN** lets you use the displayed position before the reply arrives.

## Library and PGN export

Select a game in Game library to see its PGN and board. Drag **Review ply** to step through its verified moves. Ctrl/Shift-click rows for multi-selection.

Right-click a game row for quick **Copy PGN**, **Export selected**, and **Delete saved PGN file(s)** actions. If you right-click a row outside the current selection, that row becomes the selection. Right-clicking a row already in a multi-selection keeps the selection, so the action can apply to all selected games.

For existing split recordings, Ctrl-select both rows and right-click → **Join selected recordings…**. ChessStream orders them by recording time, finds a shortest legal bridge into the next fragment's starting position, checks its subsequent moves, and saves a combined PGN at the location you choose. Gap moves have inference comments; existing move comments, clocks and variations are retained. If several equally short connections reach the same recorded continuation, it keeps one using the capture-continuity preference and labels that choice in the PGN. Originals stay in the library. The configured search limit, incompatible moves, different known player names or a declared result can prevent joining.

- **Export selected**, **Export entire session**, and **Export all** write standard multi-game PGN files.
- The live page exports or copies the current game.
- **Rename / edit headers** edits players, ratings, event, site, date, time control and result. Keep unknown players as `Unknown`; the app does not identify streamers.
- Checkmate and other board-provable results can be detected once the final move is verified. With reply protection on, confirm the final pending move explicitly. Enter resignation, timeout or agreed-draw results yourself when known.
- Settings → Automatic export folder writes a separate per-game PGN copy as verified state changes, including completion. Internal autosave always runs even without an export directory.
- **Open PGN** imports existing PGNs for review. Preserve your original file if it contains comments/variations you need to retain when editing.

Exports require no Nibbler or Stockfish installation. They can be opened in any standard PGN reader. Unresolved observations export only the verified prefix, with a comment explaining that evidence remains unresolved.

## Screenshot review and deletion

Screenshots are grouped by session and game and indexed in SQLite with UTC timestamp, sequence number, observed placement, similarity and verified ply. Use the game filter and timeline. The browser shows 200 entries at a time; **Older screenshots** loads the next page. Ctrl-click individual images or Shift-click to select a range, then choose **Delete selected screenshots** or right-click the selection. Double-click an image for its original resolution, with scrolling.

Screenshot image saving is **off by default**. Frames continue to be processed in memory, without writing image files. Turn on the setting above when you want screenshots in this browser. For images that have been saved, the default retention policy is **keep indefinitely**. Disk usage and free space appear in the app.

**Delete screenshots** supports one game, an entire session, older than a chosen date, an inclusive-from/exclusive-before range, or all screenshots. The confirmation reports the current file count and estimated bytes and explicitly states which data stays. Only screenshot PNG files are removed. Their metadata is marked deleted; PGNs, verified histories, game details and exports remain.

**Schedule deletion** accepts a future local date/time and a scope. The job is stored in UTC and survives restart. It evaluates its scope when it runs, so additional matching screenshots may be included. If the computer/app was off, it runs next time ChessStream opens. The app does not install a system service or wake your computer. Use **Scheduled jobs** to cancel a pending job.

Settings → Automatically delete after enables an explicit age policy. Zero means indefinite. Enabling a positive period requires confirmation and applies to already-saved older screenshots as well as future ones.

Game library → **Delete saved PGN files** removes the selected game's internal autosaved `.pgn` file(s) and matching per-game copies in the configured automatic-export folder. Game details, move history, screenshots and manually exported PGNs remain. The app can recreate an automatic save if you later resume or change that game. **Delete game data** removes the selected game's database record, move history and internal PGN autosave; screenshots are kept and become unassigned. Stop an active recording before either deletion.

## Diagnostics and saved logs

**Diagnostics / logs** in the sidebar opens the saved log, with Refresh, Copy, Open folder and **Export diagnostic ZIP**. The usual Windows path is `%LOCALAPPDATA%\ChessStream PGN Recorder\application.log`. It records changing recognition warnings/uncertain squares, pending moves, recovery decisions, game results, observed move clocks, user-facing errors and exception tracebacks. Logs rotate at 2 MB with three backups (about 8 MB total).

The support ZIP includes logs, recent recognition/audit records, settings, saved game states and PGNs. It can include visible player names and your local folder/region settings. It excludes screenshots. Save it anywhere and attach it when asking for debugging help. Screenshot retention controls remain independent.

## Recovery and troubleshooting

To update, close the old copy, extract the new ZIP into a separate folder, then launch it. The default data directory is shared across versions; existing screenshots and games remain available. Old verified moves are not automatically rewritten.

Progress is saved after state changes. After a crash or restart, open the saved game in Game library and choose **Resume recording**, or export it immediately. Pending ambiguity branches survive restart. Keep the data folder together when backing up: `%LOCALAPPDATA%\ChessStream PGN Recorder` on Windows. Close the app before copying it.

- **Board not found**: tighten the region, remove menus, increase the displayed board size, or disable automatic detection for an exact board crop.
- **Uncertain squares / invalid position**: check the capture bounds and orientation, use the bundled screenshot model in Settings, and show a clear stable board. The new version does not automatically use old calibration files. Manual calibration from a starting position is an optional fallback for unsupported sets.
- **Search limit**: enable adaptive frames or raise limits moderately. Review the screenshots and supply missing SAN if necessary.
- **Wrong verified move**: use Repair PGN for redundant piece excursions. For an explicit replacement, pause, right-click the live move list → Edit moves manually, undo the affected recent plies, enter the correct sequence, then resume.
- **Window moved / resized**: use tracked Window mode or Adjust. Source HWND replacement and unusual scaling may need re-selection.
- **Cannot launch the app**: on the portable download, run `Diagnose ChessStream.cmd` from its extracted folder. It starts the same app using the bundled console Python, so startup errors remain visible in a command window; that window pauses after the app exits. Close the normal ChessStream window first to avoid opening a second copy on the same saved data. This command does not perform a separate scan or create a support bundle. The source ZIP does not contain this portable launcher; it expects a local Python setup. The rotating `application.log` in the data directory also records worker failures.

See `KNOWN_LIMITATIONS.md` and `evaluation.json` for exact tested scope.


### Guess ordering and castling

When several legal shortest sequences reach the same board, guesses prefer capture/recapture continuity, then captures, two-square pawn pushes, one-square pawn pushes, and other piece moves. Quick first-match recovery uses this ordering too. For example, `d4` is preferred before `c3` when both move orders fit. These preferences describe likely move order; they do not prove it.

Castling moves the king and rook together and is accepted after 0.5 seconds unchanged, like other legal moves. Both colors and both castling sides are covered by tests. Recordings begun from a midgame FEN with unknown castling rights still require an accurate FEN to enable castling; a home king and rook alone do not prove those rights.


### Repairing contradicted guesses

Live comparisons run at least twice per second, independently of screenshot saving. The default adaptive rate is two frames per second; an existing faster setting is preserved. Acceptance measures 0.5 seconds from the first captured observation, including the animation-settling gate.

If later evidence contradicts a guessed capture or detour, recovery can retry from before a recent inferred move, at most eight recorded plies back. Searches remain bounded and only replace the suffix when a legal sequence reaches the exact observed placement. The correction is marked as inferred, and diagnostics record both the replaced and replacement moves. Earlier moves before the repair point are kept. A longer historical error may still require manual correction or joining recordings.


### Rewinding the video

The recorder checks earlier saved positions before trying to reconstruct new moves. If the displayed board matches an earlier position and is not a legal next move from the current endpoint, it enters rewind review. The main PGN keeps the pre-rewind game while the board preview follows the historical video. Pending additions are removed, and historical clocks are not attached to new moves.

Return to the saved endpoint to resume, or advance to a legal continuation beyond it. Rewind protection survives reopening a recording. A terminal-game reset still allows a new game. Normal one-move repetitions, including a legal return to the starting board, continue recording normally.

When rewind evidence also reveals a recent **inferred** four-ply, noncapturing rook round trip, the recorder can delete that loop from the main PGN and shift subsequent clock/move metadata. The diagnostic log records the removed moves. It does not delete arbitrary older verified history or silently collapse real repetitions. If both the historical and live continuation remain plausible, it keeps the PGN protected until clearer evidence arrives.


### Premoves and extra recovery time

A possible premove is shown in the preview but excluded from the PGN when only the inactive side's piece changes position. The recorder waits for an opponent move or for the preview to cancel; time alone cannot commit this out-of-turn change. This prevents invented waiting moves merely to make a premoved mate legal. Resignation ends the game at the last played position. A genuine preceding pending move can still be confirmed if its changed squares are visible.

The capture worker retains at most **12 changed board frames in RAM**, downscaled to at most 768 pixels per side (about 21 MB maximum pixel storage for square frames). Identical images refresh their timestamps rather than consuming another slot. This buffer is temporary and never writes screenshot files; your screenshot-saving preference remains separate.

Unresolved gaps can use a single background recovery worker with progressively larger, bounded search budgets up to 1.5 seconds. The worker can reconstruct through retained intermediate observations. Frame comparison continues while the longer search runs. Results are accepted only if the game, accepted prefix, root FEN and current observed placement still match the task that requested them. Premoves, rewinds and ended games cannot receive a background continuation. Corrections remain labeled inferred. These are resource limits, not guarantees of a specific frame rate under heavy CPU load.

Result OCR retries the board crop at native scale when full-window text is insufficient, preserving screen coordinates for player/clock extraction. It still requires repeated end-message evidence; an ordinary Resign button does not end the game. Diagnostics include possible premoves, discarded end-of-game premoves, queued background recovery and recovered gaps.
