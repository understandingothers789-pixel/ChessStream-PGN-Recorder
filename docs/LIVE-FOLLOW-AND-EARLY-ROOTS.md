# Live follow and early-start isolation — dev10

## Live review

Selecting an older move still pins the reconstructed board while recording continues. Selecting the newest accepted move (or its pending successor) resumes following the current live position. Stepping right to the end does the same. A persistent, checkable **Follow latest** button now appears beside the move list; checked means the board is following live updates. The existing Return to live board button remains available. Left-arrow navigation from live mode now begins at the latest position instead of a stale selected cell.

## Starting with an existing library

An ambiguous early opening could bypass the startup archive exclusion because the exclusion previously depended on having recovered a unique/selected opening prefix. If the same players and position appeared in an older PGN, that could select older history at startup. The archive exclusion now also covers material/placement compatible with a shared early opening, even if its legal search times out.

For a fully recognized, noncapturing early opening, a bounded search up to six plies can establish the side to move independently of its exact move order. If it completes exhaustively, the recorder retains the resulting root hypotheses (turn, minimal move number, castling/en-passant possibilities), rather than displaying White first and removing all castling rights. Halfmove counters are reset rather than claimed as observed. Existing three-ply prefix inference remains available. Longer ambiguous prefixes remain FEN starts; this change does not fabricate their earlier move sequence or resolve general middle-game ambiguity.

No turn is certified from an incomplete search. No explicit user FEN or imported history is rewritten by this startup check. Shortest histories remain an inference: unseen repetitions cannot be excluded from a photograph.

Regression tests cover a five-ply opening with an older same-player archive, continuing the fresh game through legal Black castling, archive isolation when search cannot establish turn, and UI follow/navigation behavior.

## What the uploaded log establishes

The supplied excerpt stays on one game ID, increases from 41 to 43 accepted plies, then accumulates ambiguous continuations, including queen out-and-back detours. It also records inactive-side/premove holds. It does not show a saved-game switch during that excerpt. This is evidence of a reconstruction/turn disagreement, not proof that library contents caused that particular stall.

The initial FEN and complete earlier move history are absent from the excerpt, so it cannot establish exactly where the historical turn disagreement began. A regression fixture reproduces the local placements with a consistent White-to-move root, including skipped pairs, a transient missing queen, and the subsequent legal queen move. It verifies that these observations can continue in one PGN when their root is correct; it does not claim to repair the old 43-ply prefix from this partial log. A full diagnostic export with the saved PGN/state is needed to diagnose that earlier history if the stall recurs.

## Follow-up supplied PGN

A later supplied PGN provides the stored 43-ply prefix, starting from the standard position and ending in `22. Ne4`, with White's last clock at 191 seconds. Its endpoint matches the log's first stalled placement and has **Black to move**. Thus the White-to-move local replay above is explicitly a counterfactual test of turn sensitivity, not a correction established by the supplied game.

The anonymized exported PGN is retained in `tests/fixtures/recordings/submitted-ne4-stall.pgn`. These are machine-recorded moves, not independently verified video ground truth. New tests replay the entire line starting from the first three observed plies, both with an empty library and an older matching game present; both produce the same 43-ply prefix in a fresh recording. Another test reproduces White's inactive-side `e4g5` view and the subsequent contradictory queen placement. It verifies that no invented queen waiting moves enter the saved mainline and that a later clear legal continuation can replace the unresolved detour hypotheses and resume recording.

The full PGN narrows the disagreement to the transition after `22. Ne4`, but a video/board-frame sequence is still needed to determine whether the queued-looking knight was a premove/drag, analysis, recognition error, or whether an earlier inferred move in the export was historically wrong. The tests deliberately do not declare one of those explanations proven.


## User-confirmed move order

The user subsequently confirmed that White really played Ng5, immediately after Black Bf6-g7. The logged piece placement indicates the knight moved from e4. Ng5 must therefore be treated as a played move, not as a premove merely because the stored PGN says Black is to move. The recorded local order `...Bg7 Ne4` conflicts with this confirmed continuation; an earlier inferred move/order is wrong or missing. Simply swapping the two moves in the full export is not a legal repair, because the preceding stored move is already a White move (`Qh3`). The first mistaken earlier inference still cannot be identified uniquely from this data.

An additional regression establishes the user-confirmed local root (White knight already on e4, Black bishop on f6, Black to move), then follows `...Bg7 Neg5 ...Qc1+ Bd1 ...Rd8`. It must record exactly these moves, stay in one PGN, and never label the confirmed Ng5 as a premove or invent queen waiting moves. The older conflicting-prefix test remains only as a check that inconsistent stored history is not patched with fabricated moves; it is not evidence that Ng5 was queued.
