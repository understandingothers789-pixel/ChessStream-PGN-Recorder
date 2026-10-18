# ChessStream PGN Recorder user guide

## Download and launch

Download `ChessStream-PGN-Recorder-Portable.zip` from the repository's GitHub Releases page. Extract it to Documents or another writable folder, then open `Launch ChessStream.cmd`. No installer, administrator rights or separate Python setup is required. If Windows blocks the downloaded launcher, right-click the ZIP → Properties → Unblock (if offered), apply, then extract again. An organization-managed block requires the device administrator; do not disable system security.

## First recording

Keep the browser and board visible. Put ChessStream beside it or on another monitor; a window placed over the board becomes part of the screenshot.

Choose **Select capture region** and drag from one outer board corner to the opposite corner. Include all 64 squares and avoid clocks, evaluation bars and player panels. Press Esc to cancel. Click **Start recording**. The first position must settle before it is accepted.

The left board is what the screen contains. The middle board is the last internally verified position. The move list shows verified SAN with checkmarks and the latest provisional move in amber. **Weakest square score** shows the lowest classifier score among all 64 squares, not an accuracy guarantee. Before the first position is accepted, every square must score at least 80% (or the configured threshold, if higher). Uncertain squares are named below the capture and the reconstructed board stays pending. Recording continues; position-mode screenshots are saved once a classification settles. A ply is one move by one player, so 60 plies means 30 full moves.

## Piece sets and orientation

The default bundled screenshot model supports varied shaded pieces, board textures and colors. Calibration is not required for the tested Neo and Ocean sets. For an unsupported set, the optional **Calibrate piece set** command switches to manually learned templates:

1. Display a genuine standard starting position with all pieces on their original squares.
2. Start capture and choose **Calibrate piece set**.
3. Confirm White or Black at the bottom. Do not confirm this on a midgame board.
4. Verify the reconstructed preview. Calibration stays local under `custom-templates.npz`. Return to **Settings → Piece recognition → Bundled screenshot model** to leave template mode. Calibration files from version 1.0 are not automatically activated by version 1.1.

Choose **Flip orientation** if automatic detection is wrong. Settings can lock White/Black at the bottom or restore Auto. Automatic mode compares both orientations to the existing position and handles a board flip without adding chess moves.

## Capture options

**Monitor** searches a whole selected monitor; **Window** follows a visible application's client area on Windows. Tight regions reduce work. A Windows drawn region remembers its containing window so the worker can attempt full-window reacquisition after a move/resize/fullscreen change.

**Adjust** opens an overlay while capture is temporarily paused. Drag to move it, drag its bottom/right edge to resize, then press Enter or double-click to apply. Esc cancels. Use a new drawing when moving to another monitor. Window tracking can follow source size changes; minimized or closed windows pause source processing until available again.

**Screenshots → Per position** is the default: save one image when a recognized position settles, then skip further images with the same recognized piece placement in the same game. Arrows, highlights, cursors and texture changes alone do not create duplicates when the recognized position is unchanged. A repeated position after intervening moves is saved again. This is a storage rule, not a proof that a provisional displayed position was an actual move; a held-piece image may be kept for review. Existing images are never removed by this setting.

Select **Screenshots → At interval** to save every configured interval (default **one second**), including unmatched board views. Settings also offers opt-in byte-identical image deduplication for this mode.

Adaptive recognition analyzes up to **six temporary frames per second** by default, independently of permanent image storage. Useful evidence is retained as database metadata. Disable adaptive recognition for lower load; a short unsaved confirmation capture still checks animation stability. Neither screenshot mode disables move analysis to save disk space.

**Pause** stops capture; **Resume** continues the same game. **Stop** saves and closes the recording. Use Game library → Resume recording to continue a saved game. Starting fresh after Stop starts a separate recording. The default hotkeys are F8 start/pause/resume, F9 stop, Ctrl+Shift+R region. Windows registers supported sequences globally when available, with focused shortcuts as fallback.

## Uncertainty and stream behavior

**Protect against dragged pieces** is enabled by default in Settings. A piece held over `c5` can look like a completed move for several seconds. The recorder keeps that latest move provisional until the opponent responds. If the piece is then dropped on `b4`, the unconfirmed `c5` candidate can be replaced; repeating a hover never confirms it just because time passed. The reconstructed board and PGN stay one ply behind while the amber move waits.

At the end of a game, inspect the visible final move and choose **Confirm final / pending move**. This is an explicit override; use it only after the piece has been released or after reviewing the game. Checkmate also waits for this confirmation. Stop, export, end of video and restart never automatically promote a pending move. Turning the protection off allows immediate confirmation and loses the hover safeguard.

The recorder tries legal sequences across missing frames, up to the configured number of plies, nodes and milliseconds. Increasing these settings can resolve a larger gap but uses more CPU. Hitting a search limit leaves the current PGN unchanged.

If several sequences fit, the move panel shows competing SAN lines. Later frames can resolve some differences. If two histories have already transposed, later boards cannot distinguish their earlier order. Changed source/destination squares need positive visual support; arrows hiding unrelated pieces can be tolerated, but an unseen destination cannot prove a move. Shorter direct legal evidence can replace unverified hover/detour candidates under the documented shortest-gap assumption. It never rewrites the verified prefix. Confirm a sequence only if you know which was played. Unverified alternatives are never included in the main PGN.

**Correct moves** allows undoing recent verified plies and entering the correct legal SAN sequence. The entire correction is validated before application. The previous state is kept in the audit metadata. Corrections do not remove screenshots.

Known earlier positions are treated as likely review/rewind when a short live continuation does not explain them. Temporary menus, advertisements or a hidden board do not overwrite the current game. Legal analysis can be indistinguishable from play; pause recording during known analysis or off-board browsing.

After a nonterminal reset to the standard position, the app waits for an opening continuation different from the previous game before separating a likely new game. Identical opening replay remains uncertain. **New game from visible board** explicitly archives the current game and starts another if you know the stream changed games. A terminal game followed by the initial position separates automatically.

## Starting in the middle

You can begin at a valid midgame position. The app records from that position and infers the turn from subsequent evidence under its shortest-gap assumption. Earlier moves are unavailable. It assumes no castling rights or en passant target because those facts are not visible in a screenshot. If known, enter the exact full FEN in Settings **before** beginning a new recording. This includes turn, rights, target and counters.

PGN export uses standard `SetUp` and `FEN` headers. A game awaiting initial-turn inference is provisional and annotated. Do not treat that provisional initial FEN as a verified history. Select the correct turn from the competing options or wait for the next clear move.

## Library and PGN export

Select a game in Game library to see its PGN and board. Drag **Review ply** to step through its verified moves. Ctrl/Shift-click rows for multi-selection.

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

Game library → **Delete game data** is independent. It removes the selected game's database record, move history and internal PGN autosave. Screenshots are kept and become unassigned. Exports saved elsewhere are kept. Stop an active recording before deleting its game data.

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
