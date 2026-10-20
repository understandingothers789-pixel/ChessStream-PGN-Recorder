# Game identity, separation and verification — v1.6.20

## Why boundaries were missed

The old logic usually required changed names **and** a clock reset, often alongside a recognizable opening. Names were extracted only near detected clocks. A replay/history early return could run before identity handling. A six-second clock-reset flag could expire before a later board read. The capture worker also polled background legal recovery before classifying the latest context. Consequently, a legal bridge or known opening could keep the wrong game active.

## Shared decision gate

`lifecycle.py` combines repeated player-name evidence, clock history, witnessed resets, results, current positions and saved history. `GameManager.process`, the capture worker and background recovery all enter this gate before accepting moves. A pending name change or uncertain unrelated position cancels old recovery work. Pending identity checks survive restart, so fresh metadata or an explicit override is required before continuing a previously uncertain identity. Result messages pass through the same identity check before their result is assigned to a PGN. Recovery tokens include a game-generation counter as well as the game ID, root, prefix and target.

Lifecycle states distinguish waiting, game in progress, new game detected, game completed, between games, analysis/replay and uncertain transitions. The live **Game** menu exposes the state, evidence reason and correction actions. Diagnostics retain observations, boundary reasons, IDs, names, actual clock readings and starting FENs.

- A changed opponent needs repeated consistent OCR, not a one-frame mismatch. Small name differences on an unchanged board require additional repeats. A clock is not required to read names or confirm a repeated opponent change.
- A reset pair is compared across readable samples, including missing overlays. At least two reset readings and supporting live play/reset context are used for rematches. Normal increases, large increments with legal continuous play, and historical video seeks are checked before making a boundary.
- Missing metadata does not erase recorded headers. Names absent from a new game remain Unknown. OCR confidence and spatial restrictions reject interface labels and masked names.
- An initial board alone does not establish a new game. With no metadata, a completed game followed by an observed reset and a distinct opening can establish a separate game; identical replays remain ambiguous. A sustained large unmatched board uses the configured five-second fallback. Small mismatches stay pending, with a configurable reminder.
- Confirmed boundaries preserve the old record and create a separate ID. The new game starts at an actually visible FEN, or with a chain of witnessed single moves from an observed root. No legal search connects the new game to the old prefix. Unknown results stay `*`.
- Returning to another saved game requires a unique established endpoint and matching currently visible player evidence. Fresh-start automatic reuse requires matching known players and an unambiguous exact saved position. Explicit library resume remains available when metadata is absent.
- Existing replay fragments can still reconnect when there is a replay/checkpoint context, matching names and a legal connection. Deliberate separations are excluded from ordinary automatic joins.

Unseen opening reconstruction is now explicitly opt-in. The existing bounded algorithms and labeled gap inference within an identified game remain available. Their legal reachability is not evidence that two confirmed different games should be combined.

## Reversible correction

`game_boundaries.py` implements New game, Continue, Analysis, Undo and Split after selected move. Commands run on the capture worker while it is active. A manual split copies the selected suffix, its clock offsets, comments and variations into a FEN PGN; the earlier portion loses an unobserved result. A database audit backup supports restoring the original after restart. Ordinary game-switch undo restores the previous active recording and keeps the later record independently. Existing library header edits and explicit PGN combining support further reassignment.

## Layout and resource behavior

The existing board detector, orientation logic, window tracking and local ONNX models remain in use. Geometry changes invalidate OCR pixels, pending metadata candidates and settling state; they do not create a game. Player/clock extraction is relative to the newly detected board. OCR remains throttled to about one scan per second, with an immediate refresh after geometry changes. No network recognizer or telemetry was added.

Uncertain transitions retain at most 24 board distributions/context observations in RAM, without saving images. The existing 12-image RAM recovery buffer remains bounded; uncertain frames are excluded from the old game's recovery evidence. Legal-link checks use bounded node/time budgets and cache results by game, prefix, target and analysis tree/cursor. Unchanged positions take the cheap identity path. Model inference accuracy/performance was not changed; no universal frame-rate guarantee is claimed.

## Reproducible coverage

The local suite has **97 passing tests**, about **7 seconds** on this execution host. `tests/test_game_lifecycle.py` contributes 25 cases, including parameterized variants; the retained suite covers real Chess.com/Lichess recognition and native OCR, reconstruction, PGN export, premoves, castling, rewind recovery, variations, storage and desktop behavior.

| Requested situation | Representative checks |
| --- | --- |
| Completed game then different opponent | Result, observed reset, new opponent, independent new PGN |
| Same-opponent rematch | Reset pair plus witnessed starting board and clock tick |
| Names changing with a reset | Repeated reads across reset and first move |
| Clock reset with unchanged names | Three-minute and five-minute fresh-game sequences |
| New game without clocks | Repeated opponent change, including a legally reachable target |
| New game without names | Reset/tick sequence with Unknown new player headers |
| Post-game analysis | Result preserved and explicit review mode |
| Earlier-position review | Historical board plus static discontinuous clocks |
| Initial position during review | Old ID protected, manual new-game/undo available |
| Windowed/fullscreen toggling | Repeated capture-worker layout invalidation without changing game ID |
| Zoom/resizing/orientation | Board-relative OCR rectangles at four geometries and both orientations |
| Temporarily hidden names | Headers retained, name candidates reset after missing reads |
| Single OCR error | Pending check then recovery without header/PGN change |
| Skipped frames | Existing gap regressions; two skipped plies with large increments |
| Switch to another midstream game | Independent FEN game, no old-prefix reuse |
| Start in the middle | Visible FEN and no fabricated opening by default |
| Return to a saved game | Matching players and unique established endpoint |
| PGN/metadata separation | Distinct IDs, preserved results/clocks, Unknown hidden metadata, setup headers |
| Increments/corrections | Small increases and large simultaneous increments retain the game |
| Recovery still processing | Ready stale future cancelled; worker gate executes before recovery |

Additional checks ensure that a result popup seen before board processing is held during an opponent change and later assigned only to the new PGN. Other checks exercise identical-board/opponent changes, restart recognition, manual split/undo with clocks and variations, manual Continue, unrelated positions quarantined until confirmation, and the previously supplied Rc1 analysis FEN. These are controlled board/context sequences and retained image fixtures, not a replay of the user's complete YouTube session.

## Remaining limits

An identical rematch and a replay with the same players and static/hidden clocks may provide identical pixels. Persistent high-confidence OCR mistakes are still possible. Board-only classification uses bounded search and can mistake an unseen long analysis jump for another game. The interface therefore exposes uncertainty and reversible decisions rather than claiming perfect identity recognition.

Physical fullscreen/DPI behavior, browser HWND replacement and long unattended use on the user's Windows machine still need hardware acceptance. Windows CI additionally validates the source suite, packaged inference, GUI, launcher and desktop shortcut before publication. Starting FEN castling/en passant history remains unknown unless supplied; move times are observed readings, and game timestamps refer to observations or manual operations, not inferred timestamps inside a video.
