# Longest recorded line is the main line — dev14

The user requested that every recorded move remain in either the main line or a
variation, and that a variation longer than the main line become the main line.
This supersedes the earlier short-inferred-suffix, clock and checkmate requirements
for choosing between recorded lines.

The saved PGN tree is compared by total half-moves from its root. A strictly longer
line is promoted all the way from its divergence; equal lengths retain existing
ordering. Nested variations count. Promotion updates the recorder's actual board,
move list, result and saved state, so the live display and exported PGN agree.
Comments, variations and node-specific clocks are retained. Clocks from the displaced
line are not copied onto the replacement. Previous PGN and move lists are audited.
Background recovery/join work and audio support from the old endpoint are invalidated.

Newly observed legal continuations can also extend an analysis cursor at the old
mainline endpoint. Previously that case raised an error and could lose the extension.
A saved annotation snapshot still cannot resurrect moves deliberately removed by
manual splitting. Generated alternate opening-order hypotheses are not newly
recorded moves; they do not displace a pending preferred opening on length alone.
Unknown-turn early-opening rewind protection is retained.

This policy intentionally permits a longer analysis line to replace an actual played
line. It does not prove historical accuracy. Ambiguous or unrecognized frames remain
unresolved until the app can record a legal continuation; they are not fabricated
merely to increase a line's length.

Validation: 322 local tests passed, including equal-length opening alternatives,
streamed longer-branch promotion without clock/name/inference requirements, nested
branches, mainline-endpoint extension, export/restart, manual splitting, earlier
queen-hover and checkmate cases, and early-opening rewind safeguards.
