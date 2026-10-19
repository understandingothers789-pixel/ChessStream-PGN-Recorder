# ChessStream PGN Recorder v1.6.18

- Replayed positions and stable analysis continuations now follow the saved PGN tree, including alternative lines. Rewind protection no longer bypasses recording of variations. The played main line, result and clocks are retained.
- Short temporary fragments with the same known players can reconnect to either of the two recent longer PGNs, including a legal alternative opening order. Reconnected analysis fragments are archived and hidden from the library and ordinary exports; original records remain in diagnostic evidence. Join previous also attempts this reconnection.
- Changed opponents, clock resets, aborted games and explicit game separations prevent automatic replay merging. Analysis gap searches remain bounded; an arbitrary distant FEN is not attached merely because names match.
- Sidebar navigation now switches its checked state before changing pages, using an exclusive button group so only one page is selected.

Validation: 72 local tests passed. Added coverage uses the supplied main-game move sequence, the short d4/c6 replay fragment, and a streamed legal alternative reaching the exact supplied Rc1 FEN. It verifies variation export, unchanged played moves/clocks/result, fragment archival, restart recovery, and safeguards for unrelated positions, clock resets, identity changes and aborted games. The exact source video/image sequence was not replayed. Tagged Windows CI additionally validates the portable build and launchers.
