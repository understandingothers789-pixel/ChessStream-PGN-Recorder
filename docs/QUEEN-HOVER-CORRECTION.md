# Recovering the played line after a hovered move

The submitted Sephiroth–Kirby log records d1-e2 accepted after 0.531 seconds at
ply 41. The queen then returned to d1, which was treated as a rewind. The actual
Bg3 Nf5 Be5 continuation was preserved as analysis while Qe2 remained the main
line. The user confirmed that Qe2 was a hover, not the played move.

The existing checkmate correction now also accepts a longer observed continuation
without checkmate when all of these hold:

- Automatic mode, matching currently visible player names, unfinished game.
- Exactly one displaced move, recorded as inferred rather than established.
- At least three plies after the divergence: replacement, reply, next move.
- Both current clock readings below their last accepted readings, with no recent
  reset. Missing/static clocks do not authorize this heuristic.
- The current board confidently matches the legal continuation's endpoint.

This favors ongoing play over an abandoned inferred hover. Length alone does not
promote variations, and explicit analysis mode blocks promotion. The old move
remains an alternative, the prior PGN is audited, and clocks from the abandoned
move are dropped. The replacement moves remain labeled inferred. This is a
heuristic; a replay with advancing clocks can resemble live play. Videos without
usable clock evidence retain the continuation as a variation for review.

The supplied fixture tests both final export and normal streamed processing after
Bg3, Nf5 and Be5, plus explicit analysis, established history, absent/static clocks
and insufficient continuation length. Existing checkmate correction remains tested.
