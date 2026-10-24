# Collective pipeline checks — 1.6.24-dev6

The recorder now has independent structural checks at capture and persistence boundaries, plus fault tests through the recording worker, game manager and SQLite PGN store.

## Changes

- Optional audio initialization, polling and cleanup errors are isolated. A missing preset or disconnected device reports audio unavailable while visual capture continues. Audio evidence is cleared when the listener fails.
- Malformed recognition probabilities (wrong dimensions, NaN/infinity, negative values, unnormalized rows, or invalid quality/orientation) are rejected before processing. The previous PGN stays intact, settling evidence resets, and pending recovery/join work is cancelled. Following valid frames can resume recording.
- Before saving, a separate validator replays every accepted move with an explicit legality check and compares the complete resulting FEN with the reconstructed board. Successful checks are cached until the game, accepted sequence, initial FEN or reconstructed FEN changes.
- If that comparison fails, the active recording returns to its last saved, independently validated checkpoint. Saved annotations, clock comments, headers and lifecycle metadata are restored with it; pending background work and audio evidence are invalidated. The rejected state does not overwrite the saved PGN, and the recovery is audited. If no valid checkpoint exists, the operation fails explicitly instead of writing inconsistent state.
- A direct legal successor is rechecked before consulting the game detector's cached search failure. An outstanding recovery job also yields to that successor, allowing normal recording checks to process it. A transient bad frame cannot monopolize recovery and keep subsequent clear moves behind it. This identifies a connection; it does not bypass premove, rewind, identity or move commitment checks.

## Fault tests

`tests/test_pipeline_faults.py` exercises:

- audio device failure plus a cleanup exception and transient name/clock OCR errors during an opening;
- malformed visual output while fresh audio evidence is present, followed by valid frames;
- a corrupted reconstructed board or illegal accepted move, verifying checkpoint recovery and an unchanged saved PGN;
- a false sound cue plus a confidently misread disappearing queen, followed by a valid bishop move;
- agreement of the accepted sequence, SQLite state, exported PGN main line and final complete FEN after recovery.

Existing integration tests also cover incomplete/ambiguous search, stale asynchronous results after A→B→A observations, result/stop boundaries, old-library contamination, new players and clock resets, replay variations, premoves, rewinds, layout changes, and independently unavailable OCR/audio. Existing audio tests check that a sound cannot resolve an ambiguous move order or override visual/legal safeguards.

## Limits

These checks detect structural contradictions and the tested component failures. They cannot prove that a plausible legal move was actually played when the visual reader misidentifies it consistently and no independent evidence disagrees. Clocks, names and audio may be missing, delayed, or wrong together. A legal but historically incorrect saved checkpoint is not corrected simply by replaying its moves. Physical Windows playback/fullscreen/DPI interactions and long commentary-heavy recordings still require real-world testing. This is not a guarantee that every possible subcomponent failure is recoverable.
