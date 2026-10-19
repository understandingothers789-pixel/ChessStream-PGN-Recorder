# ChessStream PGN Recorder v1.6.8

- Apply the requested guess ordering consistently to normal equal-shortest-path selection, opening inference and quick first-match gap recovery: capture/recapture continuity, captures, double pawn pushes, single pawn pushes, then piece moves. Target progress and deterministic ordering break remaining ties. `d4` precedes `c3` when either legal order reaches the same board.
- Preserve shortest legal endpoint matching and computational limits. This is a preference for guessed ordering, not evidence of the actual unseen moves.
- Add explicit end-to-end recording regressions for White and Black, kingside and queenside castling, including no-reply two-second acceptance and exact exported final FEN. Existing search tests also check consecutive opposite-side castling and uncertainty on the rook destination.
- The submitted older screenshots already show White O-O in the move list; Nd3 is provisional. They do not establish a distinct castling failure. Unknown castling rights in a midgame starting FEN remain a limitation; rights are not fabricated.

Validation: 39 focused tests passed locally in approximately five seconds, including quick and exhaustive d4-before-c3 recovery and capture/pawn/piece priority checks. Tagged Windows CI validates tests, portable packaging, local recognition/OCR and launcher startup. No model or dependency changes.
