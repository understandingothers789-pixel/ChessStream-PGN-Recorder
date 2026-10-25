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
