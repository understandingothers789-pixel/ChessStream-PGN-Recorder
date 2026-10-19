# ChessStream PGN Recorder v1.6.7

- A legal position unchanged for two seconds accepts pending moves without waiting for a reply. Timed moves are marked as inferred in PGN comments and amber live move indicators.
- Settled gaps use bounded search up to at least six plies, accepting the first shortest legal endpoint match without exhausting equivalent orders. Existing capture-based ordering remains in ordinary reconstruction.
- Positions unresolved for three seconds show a recovery error, write an audit entry, retain the saved PGN and continue retrying. Resource limits remain in effect; an impossible or unrecognized position cannot be forced into an illegal PGN.
- The latest timed suffix retains rollback information in saved game state. A subsequent one-move alternative from its earlier state replaces a mistaken hover instead of inventing a reversible detour. Earlier accepted prefix and earlier analysis remain intact. Later replies close this correction window; arbitrary old guessed moves may still require manual correction.
- Pauses, hidden boards and board geometry changes reset the settling timer. Screenshot saving remains off by default.

Validation: 37 focused tests, including two-second boundary behavior, no-reply PGN export, inferred indicators, rollback after saved recovery, corrected hover with exact final FEN, non-exhaustive legal gap recovery, three-second error preservation and timer reset. Actual stream interaction still needs user verification. Two new recovery tests bring the full local suite to roughly five seconds. No accuracy percentage or CPU benchmark is claimed.
