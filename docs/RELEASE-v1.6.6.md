# ChessStream PGN Recorder v1.6.6

- Preserve the active verified PGN and pending move when nearby OCR player names change. A name change alone no longer starts a separate game; immediate identity-based transitions require a clear starting board and reset clocks.
- Recheck board geometry every two seconds, including fullscreen changes that leave the browser window dimensions unchanged. Geometry changes reset recognition settling and recovery timers, not the chess game.
- Ambiguous searches, search limits and small unresolved differences no longer automatically replace the active PGN with a FEN checkpoint. Sustained large, unreachable positions still use the existing new-game detection.
- Live FEN checkpoints retry joining the preserved game before processing new moves. Automatically reconnected and manually combined source records are excluded from resume candidates, while their files remain available.
- Add **Combine selected PGNs** to the game library. Ctrl/Shift-select two or more rows, stop capture, and click the button. A successful legal join saves a combined game, makes it the main live game, and keeps the sources. Shared prefixes are merged rather than duplicated. Gap moves remain annotated as inferred; incompatible names, continuations or search limits produce an error.
- Screenshot saving remains off by default. No dependencies or model weights changed.

Validation: 35 focused local tests, including pending-move preservation through simulated layout/OCR changes, restart recovery, timeout preservation, persistent overlap joining, library button visibility, existing real-image recognition and result OCR fixtures. Actual Windows fullscreen interaction requires user verification; tagged Windows CI validates packaging, bundled inference and launch. Periodic board detection adds processing work every two seconds; no CPU benchmark was performed. Legal inferred bridges remain guesses when intermediate frames were unavailable.
