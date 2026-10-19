# ChessStream PGN Recorder v1.5.2

The live reconstructed board now previews the current legal move candidate while
the recorder waits for confirmation. The preview updates if a held piece moves
to another candidate square. Its last move is highlighted in amber and the UI
labels it as excluded from the PGN. Verified plies, stored game history, and PGN
exports continue to contain only confirmed moves. When several legal lines fit,
the board labels the candidate being previewed and how many alternatives remain.

The app still uses its own vector board colors and piece artwork. It does not
yet detect and copy Chess.com or Lichess board skins; see the limitation notes.

Validation: the workspace suite passed **127 tests**, including a GUI test that
changes an unconfirmed e4 preview to d4 and checks that the PGN stays unchanged.
