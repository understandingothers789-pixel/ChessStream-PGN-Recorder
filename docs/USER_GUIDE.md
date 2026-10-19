# ChessStream PGN Recorder user guide

## Download and launch

Download `ChessStream-PGN-Recorder-Portable.zip` from the repository's GitHub Releases page. Extract it to Documents or another writable folder, then open `Launch ChessStream.cmd`. No installer, administrator rights or separate Python setup is required. If Windows blocks the downloaded launcher, right-click the ZIP → Properties → Unblock (if offered), apply, then extract again. An organization-managed block requires the device administrator; do not disable system security.

## First recording

Keep the browser and board visible. Put ChessStream beside it or on another monitor; a window placed over the board becomes part of the screenshot.

Choose **Select capture region** and draw around the 64 squares. By default, the recorder also reads a temporary margin around the detected board to find nearby clocks and names, so those bars do not have to be in your rectangle. Keep automatic board detection on for a wider selected area; disable board detection only for an exact board crop. Avoid unrelated boards. Press Esc to cancel. Click **Start recording**. The first position must settle before it is accepted.

The left board is what the screen contains. The middle board previews the highest-likelihood legal candidate, comparing the classifier score on each square; recent clock movement can break close ties but never confirms a move. It marks its latest move in amber while provisional, and can change as a dragged piece moves between squares. The verified move count and PGN remain unchanged until the move is confirmed. The move list marks verified SAN with checkmarks. **Weakest square score** shows the lowest classifier score among all 64 squares, not an accuracy guarantee. Before the first position is accepted, every square must score at least 80% (or the configured threshold, if higher). Uncertain squares are named below the capture and the reconstructed board stays pending. Recording continues; position-mode screenshots are saved once a classification settles. A ply is one move by one player, so 60 plies means 30 full moves.

## Piece sets and orientation

The default bundled screenshot model supports varied shaded pieces, board textures and colors. Calibration is not required for the tested Neo and Ocean sets. For an unsupported set, the optional **Calibrate piece set** command switches to manually learned templates:

1. Display a genuine standard starting position with all pieces on their original squares.
2. Start capture and choose **Calibrate piece set**.
3. Confirm White or Black at the bottom. Do not confirm this on a midgame board.
4. Verify the reconstructed preview. Calibration stays local under `custom-templates.npz`. Return to **Settings → Piece recognition → Bundled screenshot model** to leave template mode. Calibration files from version 1.0 are not automatically activated by later versions.

Choose **Flip orientation** if automatic detection is wrong. Settings can lock White/Black at the bottom or restore Auto. Automatic mode compares both orientations to the existing position and handles a board flip without adding chess moves.

An optional compatible model can be added in **Settings → Custom ONNX model → Import model**. ChessStream copies it into the private app data `models` folder, separate from screenshots and settings. Only use models you trust. Imported custom models must be self-contained ONNX files under 512 MiB.

## Capture options

**Monitor** searches a whole selected monitor; **Window** follows a visible application's client area on Windows. Tight regions reduce work. A Windows drawn region remembers its containing window so the worker can attempt full-window reacquisition after a move/resize/fullscreen change.

**Adjust** opens an overlay while capture is temporarily paused. Drag to move it, drag its bottom/right edge to resize, then press Enter or double-click to apply. Esc cancels. Use a new drawing when moving to another monitor. Window tracking can follow source size changes; minimized or closed windows pause source processing until available again.

**Screenshots → Per position** is the default: save one image when a recognized position settles, then skip further images with the same recognized piece placement in the same game. Arrows, highlights, cursors and texture changes alone do not create duplicates when the recognized position is unchanged. A repeated position after intervening moves is saved again. This is a storage rule, not a proof that a provisional displayed position was an actual move; a held-piece image may be kept for review. Existing images are never removed by this setting.

Select **Screenshots → At interval** to save every configured interval (default **one second**), including unmatched board views. Settings also offers opt-in byte-identical image deduplication for this mode.

Adaptive recognition analyzes up to **six temporary frames per second** by default, independently of permanent image storage. Useful evidence is retained as database metadata. Disable adaptive recognition for lower load; a short unsaved confirmation capture still checks animation stability. Neither screenshot mode disables move analysis to save disk space.

**Pause** stops capture; **Resume** continues the same game. **Stop** saves and closes the recording. Use Game library → Resume recording to continue a saved game. Starting fresh after Stop starts a separate recording. The default hotkeys are F8 start/pause/resume, F9 stop, Ctrl+Shift+R region. Windows registers supported sequences globally when available, with focused shortcuts as fallback.

## Uncertainty and stream behavior

**Protect against dragged pieces** is enabled by default in Settings. A piece held over `c5` can look like a completed move for several seconds. The recorder keeps that latest move provisional until the opponent responds, while the middle board previews the current candidate. If the piece is then dropped on `b4`, the preview follows `b4`; the unconfirmed `c5` candidate can be replaced. Repeating a hover never confirms it just because time passed. The verified move list and PGN stay behind until evidence confirms the move.

At the end of a game, inspect the visible final move and choose **Confirm final / pending move**. This is an explicit override; use it only after the piece has been released or after reviewing the game. A stable game-ending message can confirm the final pending move when its changed squares remain clearly visible; covered destinations remain pending. Checkmate without an identifiable result message still waits for confirmation. Stop, export, end of video and restart never automatically promote a pending move. Turning the protection off allows immediate confirmation and loses the hover safeguard.

The recorder tries legal sequences across missing frames, up to the configured number of plies, nodes and milliseconds. Increasing these settings can resolve a larger gap but uses more CPU. Hitting a search limit leaves the current PGN unchanged.

If several sequences fit, the move panel shows competing SAN lines. Later frames can resolve some differences. If two histories have already transposed, later boards cannot distinguish their earlier order. Changed source/destination squares need positive visual support; arrows hiding unrelated pieces can be tolerated, but an unseen destination cannot prove a move. Shorter direct legal evidence can replace unverified hover/detour candidates under the documented shortest-gap assumption. It never rewrites the verified prefix. Confirm a sequence only if you know which was played. Unverified alternatives are never included in the main PGN.

**Correct moves** allows undoing recent verified plies and entering the correct legal SAN sequence. The entire correction is validated before application. The previous state is kept in the audit metadata. Corrections do not remove screenshots.

Known earlier positions are treated as likely review/rewind when a short live continuation does not explain them. Temporary menus, advertisements or a hidden board do not overwrite the current game. Legal analysis can be indistinguishable from play; pause recording during known analysis or off-board browsing.

After a nonterminal reset to the standard position, the app waits for an opening continuation different from the previous game before separating a likely new game. It also checks new clear positions against saved positions and bounded legal continuations. A matched position stays with the game as review; a uniquely supported branch from earlier play can be saved as an analysis variation without replacing the main line. A large unexplained position change starts a separate FEN PGN after five seconds by default. Settings let you adjust this threshold. Identical opening replay remains uncertain. **Start PGN from visible FEN** saves the current PGN as its own game, then begins another from the currently displayed board. Earlier moves are not added to the new PGN. Standard starting boards use the normal PGN headers; a midgame uses `SetUp` and `FEN`. Its side to move is inferred from the next legal continuation. Castling rights and en passant history are not visible and are left unset. A terminal game followed by the initial position separates automatically.

## Automatic surrounding context

**Settings → Automatic surrounding context** is enabled by default. Once per second, the recorder can capture a small temporary rectangle around the board, adding **18% of the board size on each side**. A 700-pixel board therefore gets up to 126 extra pixels at each edge. The margin is clipped to the visible desktop. Adjust **Context margin on each side** up to 50% for farther-away bars, or turn automatic context off to read only the selected area.

The piece recognizer still receives only the 64 squares. Permanent screenshots stay on the board; temporary context pixels are not saved as extra PNGs. When the wider selected source already contains the margin, those pixels are reused. Otherwise one nearby capture supplies both the board and its text, avoiding association of new clocks with old board pixels. The margin follows the board coordinates as existing window/region tracking reacquires the board after layout changes. This is not a guarantee for every fullscreen transition or DPI configuration; use Adjust if tracking loses the source.

Text recognition uses existing pretrained **PaddleOCR PP-OCRv4** models through **ONNX Runtime**, locally on the CPU. OpenCV processes screen pixels; application rules interpret clocks, results and names; python-chess validates moves and writes PGN. No custom OCR training or online inference is required. Cover labels such as NAME BLURRED or DEFINITELY NOT … do not identify the hidden account and remain Unknown, even when their letters are readable. Nearby clocks can still be read.

## Results, clocks and player names

By default, the local bundled OCR models scan the selected source about once per second. English **You Won**, **You Lost**, **White/Black Won**, a recognized winner name, a standalone score, draws, **Game Aborted** and abandonment messages can end a recording after repeated evidence. `1-0`, `0-1` and `1/2-1/2` are standard results; an aborted game or an unidentified winner keeps `*` with an explanatory note. The played main line is frozen and capture stays ready for a new starting board. If the final provisional move's changed squares are visible, the message confirms it even when other squares are covered by the dialog. If its destination is hidden, the PGN result is saved while that move stays unresolved until a clear view or correction.

**You Won / You Lost** describes the account owner. Settings → **Player color for You Won / You Lost** defaults to remembering the bottom color from the beginning of this recording, keeping it across later flips. If you start with the stream already flipped, set White or Black explicitly, or choose Unknown to require a named/color result. Explicit scores and matched visible winner names take precedence. Midgame FEN recovery starts a new segment and remembers its initial bottom color. Review a result if the initial player-color assumption was wrong. Edit Result to `*` to reopen a mistaken completed boundary.

Clocks must be visible near the board, within the automatic context margin or your selected area, outside the 64 squares. Readings are assigned to colors by board orientation and saved as standard `[%clk H:MM:SS]` PGN comments. The first observed reading for a pending move is retained when that move is later verified, rather than using a later clock value. Captures may be about one second after release, or later when a frame is missed. No exact release time, increment, time control, or missing clock value is invented. A skipped intermediate position may have no clock comment.

Names near a detected clock must repeat across three scans before they are used. Visible names can populate Unknown player headers. Hidden names remain Unknown. Stable player-name changes preserve the previous game and start a new FEN segment; a recent reset of both clocks supports separating a new standard-start game. Repeated openings with hidden names and clocks may remain ambiguous. Settings can turn result recognition and clock/name recognition off separately.

## Alternative lines and post-game review

Game library → **Moves & variations** shows the played main line, side variations, clock comments and annotations. Click any move to display its position. The main line stays flat; alternative branches are indented. **PGN text** shows the full export.

Select the position **before** the move you want to replace, choose **Add alternative line**, and enter legal SAN from that position. Add a comment if desired. Nested alternatives work inside other variations. **Edit comment** changes a move/position comment; **Remove alternative line** removes only a side branch, never the played main line. A review annotation cannot extend the actual game after its final recorded move; select an earlier branching position. Corrections to actual played moves use Correct moves.

After a result, known earlier positions can anchor automatic review variations for **120 seconds** by default (Settings → Capture post-game review variations for). Clearly reconstructed review moves are added only as alternatives to the completed main line and labeled as observed analysis. The latest held review move still waits for later evidence. The completed result and played moves are preserved. An initial board arms another game; an analysis reset to the initial board can be indistinguishable from a new game. Pause during known opening reviews if needed. Imported PGN variations and move comments survive ordinary header edits and exports.

## Starting in the middle

You can begin at a valid midgame position. The app records from that position and infers the turn from subsequent evidence under its shortest-gap assumption. When the visible position has one exact, legal path of up to four plies from the standard starting position, ChessStream includes that uniquely reconstructed opening instead of starting from a midgame FEN. If the path is ambiguous or the bounded search cannot prove uniqueness, earlier moves are left out and the game starts from a visible FEN. It assumes no castling rights or en passant target for a midgame FEN because those facts are not visible in a screenshot. If known, enter the exact full FEN in Settings **before** beginning a new recording. This includes turn, rights, target and counters.

PGN export uses standard `SetUp` and `FEN` headers. A game awaiting initial-turn inference is provisional and annotated. Use **Copy visible FEN** to send the captured board to Nibbler or another tool. If the board matches a known game position, the app preserves its known turn and rights; otherwise it asks whether White or Black moves and assumes no castling rights or en passant target. The FEN begins the new PGN; moves from before that position are not reconstructed.

## Unmatched positions and automatic recovery

When a resumed video jumps beyond the saved position, ChessStream first checks verified positions and short legal continuations from the game. A reachable position is treated as review/analysis. A clear, large unexplained change (four changed squares by default) starts a separate PGN from its visible FEN after five stable seconds; smaller unmatched positions use **Start a FEN segment after unresolved position** (15 seconds by default). A countdown appears in the live status. Missed moves are not guessed into either PGN. Set the unresolved-position timeout to **Off** to disable recovery for smaller changes. The **Start PGN from visible FEN** button starts a segment immediately.

A single legal move waiting for the opponent remains provisional and is excluded from this timeout so a dragged piece does not become a move just because it sat still. **Copy visible FEN** lets you use the displayed position before the reply arrives.

## Library and PGN export

Select a game in Game library to see its PGN and board. Drag **Review ply** to step through its verified moves. Ctrl/Shift-click rows for multi-selection.

Right-click a game row for quick **Copy PGN**, **Export selected**, and **Delete saved PGN file(s)** actions. If you right-click a row outside the current selection, that row becomes the selection. Right-clicking a row already in a multi-selection keeps the selection, so the action can apply to all selected games.

- **Export selected**, **Export entire session**, and **Export all** write standard multi-game PGN files.
- The live page exports or copies the current game.
- **Rename / edit headers** edits players, ratings, event, site, date, time control and result. Keep unknown players as `Unknown`; the app does not identify streamers.
- Checkmate and other board-provable results can be detected once the final move is verified. With reply protection on, confirm the final pending move explicitly. Enter resignation, timeout or agreed-draw results yourself when known.
- Settings → Automatic export folder writes a separate per-game PGN copy as verified state changes, including completion. Internal autosave always runs even without an export directory.
- **Open PGN** imports existing PGNs for review. Preserve your original file if it contains comments/variations you need to retain when editing.

Exports require no Nibbler or Stockfish installation. They can be opened in any standard PGN reader. Unresolved observations export only the verified prefix, with a comment explaining that evidence remains unresolved.

## Screenshot review and deletion

Screenshots are grouped by session and game and indexed in SQLite with UTC timestamp, sequence number, observed placement, similarity and verified ply. Use the game filter and timeline. The browser shows 200 entries at a time; **Older screenshots** loads the next page. Double-click an image for its original resolution, with scrolling.

The default is **keep indefinitely**. Disk usage and free space appear in the app.

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
- **Wrong verified move**: pause, undo the affected recent plies in Correct moves, enter the correct sequence, then resume.
- **Window moved / resized**: use tracked Window mode or Adjust. Source HWND replacement and unusual scaling may need re-selection.
- **Cannot launch installed app**: run `Diagnose ChessStream.cmd` in the installation directory. The rotating `application.log` in the data directory records worker failures. Packaged inference and GUI startup are tested by Windows CI; hardware-specific failures still need checking on your PC.

See `KNOWN_LIMITATIONS.md` and `evaluation.json` for exact tested scope.
