# ChessStream PGN Recorder v1.5.3

The provisional board now scores each legal candidate against all 64 per-square
recognition probabilities. The latest clock trend can break close ranking ties,
but clock readings never verify a move or change the exported main line.

New-game recovery now compares a clear screen position with every verified PGN
position and bounded short legal continuations. Reachable positions stay with
the existing recording as review/analysis. A uniquely reconstructed side line
that remains stable is added as a PGN variation. A large, unexplained board
change starts a separate FEN-based recording after five seconds by default;
smaller mismatches use the existing configurable timeout. Both thresholds are
available in Capture & recognition settings. Earlier PGNs are preserved.

The timeout and confidence ranking changes have regression coverage for
analysis branches, unrelated new games, ambiguous candidates and clock trends.
The source test suite and Windows release workflow validate the package before
the portable ZIP is published.
