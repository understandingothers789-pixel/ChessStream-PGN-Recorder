# ChessStream PGN Recorder v1.6.10

- Detect a rewind before forward legal search: an exact earlier saved placement that is not a legal next move enters protected review rather than inventing a reversible continuation.
- Keep the accepted pre-rewind mainline, remove pending additions, show the historical board in preview, and prevent rewind playback from appending moves or assigning historical clocks to new plies.
- Resume at the saved endpoint or a compatible forward continuation. Persist rewind state across reopening the recording. Clear it for a terminal/reset new game.
- On detected rewind, delete a recent inferred four-ply noncapturing rook round trip that returns to the same placement, such as Re1 Ra7 Rf1 Ra8. Keep later legal moves, shift their clocks/inference indices, and audit deleted moves. Cleanup is bounded to the recent 12 plies and requires all four loop moves to be marked inferred. It does not erase arbitrary verified history.
- Preserve real one-move repetitions, including a legal return to the starting position; these must not become rewinds or new-game candidates.

Diagnosis: the prior pipeline attempted forward legal search before treating an earlier observed position as video review. Reversible rook moves could explain the screen change and become accepted, after which ordinary recording continued from the invented detour. The new history-first guard intercepts that path. Board images cannot prove whether the user rewound or the streamer reviewed; both are protected as historical review.

Validation: 47 focused local tests passed in approximately six seconds. Added coverage follows the reported d4/a6/e4/b5/Bd3/Bb7/Nf3/e6/O-O/Nf6/Re1 opening, rewinds to check e6/Nf6, pauses, reopens the recording, plays forward, and resumes with g6 without rook detours. Separate tests remove an inferred rook loop while preserving later clocks and check actual knight repetitions. This is controlled position testing, not a replay of the supplied screenshot pixels. Existing real-image/OCR tests remain covered; tagged CI builds and tests the Windows portable download.

Limits: detection needs a position represented in saved history. An unseen review position or ambiguous continuation may remain protected until the endpoint returns; manual correction may be needed for older or unmarked detours. Screenshot saving remains off by default, acceptance remains 0.5 seconds, and no dependencies or models changed.
