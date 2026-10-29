# Three-ply opening startup — dev8

The supplied log recorded the correct initial placement:

`rnbqkb1r/pppppppp/5n2/8/2PP4/8/PP2PPPP/RNBQKBNR`

At the first startup it reported `awaiting side to move` with zero plies, then retained White/Black root hypotheses. The saved PGN used a White-to-move FEN as its initial display hypothesis. Later recovery found `...e6` and resolved the turn, but did not recover the omitted opening moves. This was a startup/history issue rather than evidence of a piece recognition error in that frame. The pasted log also contains older sessions; those were not assumed to describe this recording.

The default short opening search previously stopped at two plies. It now covers three. For a completed three-ply startup search with independent noncapturing piece moves, all legal shortest explanations are checked. The chosen order is explicitly inferred, never presented as witnessed history. A central double pawn move is preferred first when the image cannot distinguish the orders. For this placement the main order is `d4 Nf6 c4`; `c4 Nf6 d4` is retained as an annotated PGN variation. Both reach the same placement with Black to move. Castling rights and move numbers now follow the standard starting board rather than a synthetic midgame root.

The existing final-move policy still applies: the third move can briefly remain provisional, with the preview showing the visible Black-to-move endpoint, until stable-image or reply evidence accepts it. After settling, export includes all three opening moves without a FEN/SetUp tag. Following moves remain in the same game.

The same bounded recovery can repair an app-created early FEN segment when its recorded continuation fits, preserving that continuation and moving its clock comments to the correct ply numbers. Imported PGNs and explicitly configured initial FENs are preserved. This does not arbitrarily choose between ambiguous gaps later in an ongoing game or infer an unseen four-ply transposition.

Regression tests cover startup in both display orientations, automatic recording, the Black-to-move preview, PGN round trips, the alternative variation, the continuation `...e6 Bg5 ...d5 Nc3 ...Be7`, and repairing a legacy FEN with clock preservation. The older no-prefix legacy test was updated to assert the newly requested short-prefix recovery, rather than deleting its continuation/clock checks.
