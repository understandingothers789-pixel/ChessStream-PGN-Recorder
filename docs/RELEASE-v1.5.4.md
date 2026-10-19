# ChessStream PGN Recorder v1.5.4

Settings files are now loaded defensively field by field. A malformed numeric
setting falls back to its own safe default without discarding other preferences.
Invalid orientation, screenshot mode, recognition mode, FEN, or saved capture
region values are reset safely instead of preventing the desktop from opening.

Validation: regression tests cover malformed individual values, preservation of
valid settings, and valid negative-origin monitor regions/FENs. This is a
maintenance release; the v1.5.3 move ranking and game-transition behavior are
unchanged.
