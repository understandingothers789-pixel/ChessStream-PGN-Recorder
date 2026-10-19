# ChessStream PGN Recorder

A local Python / PySide6 desktop application that reads a visible 2D chessboard from your screen, follows legal moves, saves review screenshots, and exports standard PGNs. It does not need player usernames, a chess-site account, Nibbler, an engine, subscriptions, or chess/video APIs.

**Version 1.5.9 avoids duplicate position screenshots and resumes matching games.** Fullscreen/layout changes no longer save another image when the last recognized board position in the session is unchanged, including interval mode. At startup or before creating a separate FEN recording, ChessStream checks whether the visible position matches the latest saved game's verified endpoint or pending move and resumes that PGN when it does. See the [release notes](docs/RELEASE-v1.5.9.md), [user guide](docs/USER_GUIDE.md), [security audit](SECURITY.md), and [known limitations](docs/KNOWN_LIMITATIONS.md).

![PGN viewer with clock comments and a manual alternative line](docs/variations-v1.4-preview.png)

Game library showing clock comments from the retained native browser capture and a manually added analysis variation.

## Install on Windows 11 x64

1. Download the ZIP from [GitHub Releases](https://github.com/understandingothers789-pixel/ChessStream-PGN-Recorder/releases/latest) and extract `ChessStream-PGN-Recorder-Portable.zip` to a folder you can write to, such as Documents. No installer, administrator access, or separate Python installation is needed.
2. Double-click `Launch ChessStream.cmd` in the extracted folder. The package includes a private Python runtime; it does not install software system-wide.
3. Place the app beside the browser or on a second monitor. The captured board must remain visible.
4. ChessStream automatically selects the best visible YouTube chess window. Click **Start recording**; nearby clocks/names are captured automatically in a temporary margin. You can draw a capture region if you prefer.
5. Check the live preview and **Weakest square score**. The bundled model needs no initial calibration for the tested Chess.com/Lichess themes. An uncertain first position stays pending, with affected squares named; stable positions continue to be saved.
6. Verified moves have a checkmark. The reconstructed board ranks legal candidates against the classifier score on each square; recent clock movement can break close ties but cannot confirm a move. The amber preview is not in the PGN until confirmed. A board linked to an earlier position or short legal continuation stays with that game as review/analysis. A large unexplained change must remain stable for five seconds before a separate PGN starts from its FEN. Smaller unresolved changes use the separately configurable FEN timeout. Select **Start PGN from visible FEN** to start one immediately. **Copy visible FEN** copies the displayed position; if side to move is unknown, choose White or Black. Export from the live page or Game library. Unknown names stay `Unknown`.

After a detected result, the played main line is frozen. Post-game review can add side variations for two minutes by default. In Game library, select a position to add a legal SAN alternative or comment; exports retain them. **Diagnostics / logs** opens saved status messages and can export a support ZIP without screenshots.

The ZIP contains `pythonw.exe` as part of its private Python runtime, launched by the included `.cmd` shortcut script. No installer executable is required. Windows SmartScreen may still display warnings for unsigned downloaded scripts or binaries. The Windows workflow tests the bundled inference runtime and GUI before release. Live capture on your Windows 11 hardware remains a separate acceptance check.

## Run from source

Install official Python 3.12 or 3.13 x64, then run in PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m chessstream
```

`Launch-Windows.cmd` automates that first-time setup when a compatible Python is installed. Recognition assets are already included. Normal use makes no network requests.

To update a portable copy, stop and close the old app, extract the new ZIP into a separate folder, and launch the new copy. The default data directory is shared, so existing games and screenshots remain available. Back it up first if needed. Old verified moves are never silently rewritten; an older ambiguous recording can be resumed for further evidence or manually corrected.

For Linux development:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m chessstream
```

PySide6 requires a desktop session for interactive use. Headless GUI verification uses `QT_QPA_PLATFORM=offscreen`.

## Implemented functionality

- Region drawing and live move/resize overlay; monitor selection; Windows application-window selection with client-area tracking. On Windows, a drawn source remembers its containing window for board reacquisition after layout changes.
- Region-only MSS capture, screenshots per settled observed position by default, an optional adjustable interval mode, and adaptive temporary analysis frames (default six per second). Arrow/cursor changes that preserve the recognized position do not create duplicate position-mode screenshots. Analysis continues independently of image storage.
- OpenCV checkerboard localization, a bundled 1.3 MB pretrained 13-class screenshot CNN (fenshot, MIT), CPU inference through ONNX Runtime, optional manual template calibration, and an optional custom ONNX model imported into the app-managed models folder.
- Automatic orientation, explicit flip, stability confirmation, legal multi-ply reconstruction, castling, en passant, promotion, and independent ambiguity branches. Changed squares require positive visual support. The latest ply stays provisional until a reply or explicit confirmation; provisional hovers can be replaced without rewriting verified moves. A clear position that remains unresolved starts a separate FEN-based PGN after a configurable timeout; ambiguous plies are not invented. Incomplete searches cannot certify a unique path.
- Continuous verified-prefix PGNs, SQLite crash recovery, midgame FEN/SetUp, copy-visible-FEN and start-from-visible-FEN controls, automatic unresolved-position checkpoints, checkmate/stalemate handling, conservative reset/review handling, separate games, editable headers/results, import and multi-game export.
- Live preview, reconstructed board, SAN move list, confidence/similarity and storage indicators, game library with a move slider, screenshot thumbnails/timeline, observed positions and full-resolution review.
- Image-only deletion by game, session, date, range or all; confirmed future jobs; optional age retention; pending-job cancellation. Keep indefinitely is the default. Independent game-data deletion preserves screenshots and external exports.
- Windows global hotkeys when available (F8 start/pause/resume, F9 stop, Ctrl+Shift+R region), with focused Qt shortcuts as fallback. Configurable in Settings.

## Recognition and reconstruction boundaries

The default recognizer is the bundled MIT-licensed fenshot screenshot CNN, running offline through ONNX Runtime. Controlled browser tests cover Lichess and Chess.com pieces, textured boards, arrows, drag states, flips and compression. Those tests do not establish universal recognition accuracy. Optional calibrated templates remain available for unsupported artwork.

A piece held over a legal square can be visually identical to a dropped piece, even for several seconds. With the default protection enabled, repeating that image never verifies the latest move: an opponent response or explicit user confirmation is required. The board and PGN can therefore trail the live display by one ply. Final moves, including checkmate, need explicit confirmation if no reply follows. Disabling **Protect against dragged pieces** restores immediate confirmation but removes this safeguard.

“Verified” means supported by stable visual evidence and a unique legal path **under the shortest-gap search assumption and configured limits**. It is not a guarantee against visual misclassification. Different move orders can reach the same board. Completely unseen reversible cycles cannot be recovered. The app retains legal ambiguity instead of engine-ranking a human move into existence.

Midgame pieces alone cannot prove turn, castling rights or an en passant target. The app infers turn from the next shortest legal transition and assumes **no castling rights / no en passant target** unless you provide an exact initial FEN. Earlier moves are not invented. A PGN with unresolved evidence exports only its verified prefix with an explanatory comment.

Opening reviews and new games can be visually indistinguishable. The app now checks visible positions against the verified history and short legal branches before splitting. Large, stable unexplained positions start a separate FEN PGN automatically; long reviews beyond bounded search may still be misclassified. Menus, advertisements and hidden boards do not change the saved game.

## Tests and measured evaluation

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
python scripts/evaluate.py
```

The included `tests/fixtures/real` contains **64 actual Chromium screenshots** captured from public Lichess and Chess.com analysis boards, with a manifest of known FENs and test moves. Three are full Lichess games; the fourth is a 16-ply Chess.com opening. All frames are evaluated without calibration. This is a controlled fixture set, not a YouTube stream benchmark.

The recorded [evaluation](docs/evaluation.json) evaluates every existing real browser frame without calibration. The additional [recognition regression report](docs/recognition-v1.2.json) compares the original templates with the new model on textured boards and includes Chess.com Ocean/Walnut, analysis arrows, dragging, flips and compressed captures. These are controlled regression suites; they are not evidence of general YouTube accuracy. Your particular stream and capture still need checking.

An additional [live capture acceptance test](docs/live-capture-result.json) used headed Chromium on an actual X11 desktop with MSS and the production recording worker. It automatically verified seven of eight test plies, with one explicit final confirmation, checked pause/resume and a real board flip, and saved five position screenshots over 54 processed updates. Every measured complete sequence in the current reports includes one explicit final-move confirmation; the reports count that intervention. A compressed MJPEG video replay and three consecutive real-image games are also covered by automated tests. These Linux results do not validate Windows capture or YouTube streams.

`scripts/capture_fixtures.py` recreates the original browser fixtures. `scripts/capture_confirmation_fixtures.py` reproduces the continuation after `Bb6`, native blue arrows and a bishop held over `c5` before release at `b4`; `scripts/evaluate_confirmation.py` records the results. These use public browser UIs and known test PGNs. The application does not include any of those test sequences in its runtime behavior. `examples/*.pgn` are generated by the actual recognition pipeline from the captured sequences.

## Local video replay

The same vision and game-management pipeline can process a local prerecorded video:

```sh
python -m chessstream --data-dir ./replay-data --replay ./recording.mp4 --region 100,80,720,720 --orientation auto
```

Omit `--region` to locate the first board automatically. Replay reads frames locally; it does not download videos or consult site APIs. PGNs and screenshots are written under the selected data directory.

## Packaging

The portable ZIP contains official CPython 3.13.16 x64, pinned Windows wheels, ONNX Runtime, all source modules and offline recognition assets. It does not install system-wide or require a paid service. To rebuild, run:

```sh
python scripts/build_windows.py
```

The builder works on Linux and Windows. Windows wheels are downloaded explicitly for `win_amd64`, and a SHA-256 input manifest is included. An optional NSIS installer can still be built by passing `--makensis /path/to/makensis`; the portable ZIP is the recommended download. `.github/workflows/windows.yml` runs Windows tests, GUI rendering, packaged-runtime import checks and portable package construction when the project is pushed to GitHub. Tagged releases are published only after Windows tests, packaged neural inference and the GUI smoke check pass.

## Data and modules

Windows data: `%LOCALAPPDATA%\ChessStream PGN Recorder`. Use `--data-dir PATH` to override it. Back up the entire directory with the application closed.

| Module | Responsibility |
| --- | --- |
| `capture.py` | Windows DPI, sources, threaded screen capture and adaptive frames |
| `vision.py` | Board detection, template classification, calibration and ONNX |
| `reconstruction.py` | Bounded legal search, competing histories and commit rules |
| `games.py` | Sessions, reset/review tracking, game results and PGN generation |
| `storage.py` | SQLite, atomic PGN saving, images and durable deletion jobs |
| `gui.py`, `widgets.py`, `hotkeys.py` | Desktop interface, overlays and controls |
| `replay.py` | Local prerecorded-video ingestion |

The metadata database is `recordings.sqlite3`; images are under `screenshots/<session>/<game>/`; internal autosaves are under `pgn/`. Temporary adaptive frames exist only in memory. Recognition evidence metadata is retained on position/status changes, including frames for which no image is saved. Logs rotate independently. Deleting screenshots marks their records deleted without deleting game data.

See the [user guide](docs/USER_GUIDE.md), [architecture](docs/ARCHITECTURE.md), [stage report](docs/STAGES.md), [limitations](docs/KNOWN_LIMITATIONS.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
