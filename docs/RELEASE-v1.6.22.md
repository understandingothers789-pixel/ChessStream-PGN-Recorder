# ChessStream PGN Recorder v1.6.22

Short replay recordings no longer pull the active recorder away from the longer PGN that already contains their move sequence. The saved game's complete main line is checked against the active move history before the lifecycle detector treats an earlier endpoint as a return to another game. This prevents the visible move list and active PGN from oscillating as a replay moves between earlier and later positions.

Validation: 99 local tests passed in about seven seconds. The new regression alternates repeatedly between a short replay endpoint and the later main-game endpoint and confirms the active game ID remains unchanged. See [game lifecycle validation](GAME_LIFECYCLE.md). Windows portable packaging is validated by the tagged CI workflow.
