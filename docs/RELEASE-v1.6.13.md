# ChessStream PGN Recorder v1.6.13

- Reconstruct clear opening boards up to 14 plies from the standard start when at least 30 pieces remain. The bounded search follows legal piece moves, supports castling and up to two captures, and selects one plausible order when earlier frames were missed. Every inferred move is labeled in the PGN. The shorter opening path still handles up to two weak unchanged squares.
- Recognize a stable, divergent opening after about one second. Compare the current game and the two most recent saved PGNs before creating a new recording. A legal continuation from the active game stays in its PGN; an exact saved-position match can reconnect a temporary recording to the prior game.
- Treat changed player names together with reset clocks as stronger evidence of a new game, even if an early board placement repeats. Preserve the separation across restarts so the automatic join does not immediately undo that decision.
- Keep a possible premove out of the new-opening decision. Ordinary moves and matching saved positions take the quick path without repeatedly searching from the standard start.

Diagnosis: the earlier six-ply/six-displaced-piece opening limit could not reconstruct the supplied board, which needs about ten plies and castling. The rewind guard could then keep treating the clear new opening as old-game review. The new bounded path creates a standard-root PGN instead of discarding the prior PGN or beginning from a late FEN.

Validation: 58 local tests passed. New cases cover the supplied ten-ply castled opening, a ten-ply opening with two captures, a divergent opening that creates a new PGN and later reconnects to an earlier saved position, a skipped opening continuation that keeps the same PGN, and a matching early placement with changed players and reset clocks. Tagged Windows CI additionally builds and checks the portable package.

Limits: when move order was not observed, the chosen legal line is a guess. Openings beyond 14 plies, with more than two captures, weak squares, or ambiguous game identity can still need a visible-FEN segment or manual correction. A new analysis line that does not match recent saved history can resemble a new game. The supplied inline screenshot was used to construct the board-position regression; the exact video frames and live timing were not replayed.
