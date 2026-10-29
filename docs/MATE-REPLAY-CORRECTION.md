# Checkmate correction and repeated opening replay

The supplied Goomba–Bowser PGN ended its main line at inferred 13.Nf3 while
13.Nxe6 through 33...Qd2# was stored as analysis. The user confirmed that the
checkmating continuation was the played game. The log then showed a duplicate
recording created after both clocks reset and the same opening reappeared.

A confident historical position at ply three or later, with both currently
visible player names matching, now takes precedence over clock-reset evidence.
The initial board alone and matching names alone do not establish replay. An
unlinked opening can still trigger a separate game. A real rematch reproducing
the same opening cannot always be distinguished from replay; this policy favors
replay, as requested. Use the game mode control to start a separate game if needed.

An observed legal mating variation may replace only a one- or two-ply entirely
inferred mainline suffix. It requires automatic mode, matching visible players,
an unfinished mainline, and a confidently matching mating board. Explicit
analysis mode, established suffixes, changed players and completed results block
promotion. The old line remains a PGN variation and the previous PGN is included
in an audit entry. Clocks from the displaced suffix are not assigned to the new
line. Checkmate alone does not prove that an arbitrary analysis line was played;
this is a deliberately narrow recovery heuristic, not a general proof of history.

Tests cover the submitted PGN, normal processing through the analysis cursor,
legal export/reload, retained old variation, replay after clock reset, unrelated
opening and the blocked promotion cases. The full local suite passed 312 tests.
