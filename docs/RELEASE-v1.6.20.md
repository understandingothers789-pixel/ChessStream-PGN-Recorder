# ChessStream PGN Recorder v1.6.20

Consecutive games now pass through a shared lifecycle gate before reconstruction, replay attachment or background recovery. Repeated opponent changes can separate a game without clocks. Reset clocks, witnessed board resets, results and renewed play support rematches; historical review and clock increments are checked first. Uncertain observations preserve the existing PGN and cancel stale recovery work. Result popups also pass through the identity gate, so a new game's result cannot be assigned to the previous PGN while a confirmed opponent change is pending.

Names can be read above/below the board without readable clocks. Layout changes invalidate OCR caches and candidates while retaining the game identity. OCR still runs locally at about one scan per second.

The Game menu beside the moves explains the current state and offers New game, Continue, Analysis, Undo last switch and Split PGN after selected move. Manual splits preserve suffix variations/comments/clocks and can be undone after restart. Existing header editing and explicit PGN combining remain available.

Midgame and newly separated recordings use visible FENs by default. Earlier opening moves are not fabricated; the existing guessed-opening feature is now opt-in. A confirmed game boundary is never bridged through the previous game's move history. Small unexplained mismatches remain pending rather than forcing another PGN.

Validation: 97 local tests passed in about seven seconds, including 25 lifecycle cases and the retained real recognition/OCR, chess, storage and desktop regressions. The coverage matrix and limits are in [GAME_LIFECYCLE.md](https://github.com/understandingothers789-pixel/ChessStream-PGN-Recorder/blob/v1.6.20/docs/GAME_LIFECYCLE.md). Fullscreen/zoom checks use representative geometry and worker sequences; physical Windows video/DPI acceptance and the user's full source-video replay remain unverified. Tagged Windows CI validates the portable build before publication.
