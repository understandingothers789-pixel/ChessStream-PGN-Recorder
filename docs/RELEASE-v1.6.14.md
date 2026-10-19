# ChessStream PGN Recorder v1.6.14

- Replace the live Correct moves dialog button with equal-width Repair PGN and Join previous buttons. Both have explanatory tooltips and show their results inline. Advanced SAN editing remains in the move list's right-click menu.
- Repair interleaved noncapturing piece excursions, including the reported Bb8/Bf4 and Na6/Nb8 detour. Replay the retained moves and require the same final placement, turn, castling rights and legal en passant state. Remap retained clocks and move comments. Preserve compatible analysis anchors and keep the full original PGN/state in the saved audit.
- Automatically clean a narrow subset of unclocked opening detours when an inferred opening exists and the removable moves are inferred or include an enemy-back-rank excursion. Ordinary observed repetitions and clock-supported detours are excluded from automatic cleanup.
- Try joining either of the two previous recordings without a save dialog. Make the validated combined game active, retain legal pending preview moves, and keep original records. No compatible match is reported inline, including while capture is paused.

Diagnosis: the recorded sequence in the screenshot contains a White bishop excursion and Black knight excursion that can be removed together while preserving the endpoint. Previously, a legal return to the same piece placement did not invalidate those already accepted moves. The exact triggering frame or recognition fault cannot be established from the screenshot alone.

Validation: 62 local tests passed in about 14 seconds. New coverage checks the supplied detour, clock/comment remapping, unchanged endpoint, repeated repair as a no-op, automatic cleanup restrictions, castling rights, one-click previous-game joining with a pending move, and desktop button routing without the old dialog. Windows tagged CI additionally tests and builds the portable package.

Limits: endpoint equality cannot establish whether a real repetition was played. Manual Repair PGN may remove such a repetition when explicitly requested. Cleanup is bounded to inverse piece excursions in the recent 48 plies and does not correct every wrong pawn move or capture. Analysis anchors lost during cleanup remain recoverable from the original audit PGN. Joining remains limited by legal reachability, recorded results and player identity.
