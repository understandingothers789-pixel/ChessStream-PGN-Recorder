# ChessStream PGN Recorder v1.5.5

When recording starts from a position shortly after the standard opening, ChessStream searches for a unique, exact shortest legal sequence of up to four plies from the normal initial board. If the bounded search finds exactly one path, those opening moves are included in the main PGN and the file starts from the standard position. The PGN comment identifies these as inferred; another earlier history that transposed to the same position cannot be ruled out. Ambiguous ancestry, incomplete searches, and ordinary midgame starts keep the existing visible-FEN behavior.

The game library adds **Delete saved PGN files**. It removes app-managed per-game `.pgn` autosaves and matching copies in the configured automatic-export folder while preserving the game record, move history, screenshots, and manually exported copies. The existing **Delete game data** action remains available separately.

Validation: targeted opening-reconstruction, ambiguity, storage-deletion, and desktop GUI tests pass. The full test suite and Windows portable build are run by GitHub Actions for this release.
