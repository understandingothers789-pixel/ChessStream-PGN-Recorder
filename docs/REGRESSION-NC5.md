# Reported Nxe4–Bg2–Nc5 regression

The user clarified the continuation as 9...Nxe4 10.Bg2 Nc5 11.O-O Nd3, with e4 and c5 as the opening moves. The displayed move table supplies a legal opening prefix used in controlled regression tests. Earlier reconstructed move order is not asserted to be the actual video history.

Added coverage:

- Continuous observations retain the clarified continuation and exact final FEN.
- Five-second jumps between observations, omitting intervening moves, recover the same continuation without creating another recording.
- The final observation carries a 74.9% empty-square confidence on c5, reflecting the reported low-confidence square while the knight is on d3.
- A saved/reopened inferred Rb8–Bxe4–Ra8–Bg2 detour, which incorrectly captures the e4 knight, is replaced by Nc5. The preceding opening, game ID and exact final FEN are retained.

These are controlled python-chess observations, not a replay of the original video or pixel-identical screenshot fixtures. They verify legal reconstruction and recent inferred-history repair, not the original recognition trigger. The passing cases require no runtime change beyond v1.6.9. The full focused suite now has 44 tests and runs locally in approximately six seconds.
