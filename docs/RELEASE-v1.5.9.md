# ChessStream PGN Recorder v1.5.9

Recognized screenshot deduplication now spans a whole recording session rather than only consecutive captures associated with the same game. It ignores intervening screenshots with no recognized FEN and applies to stable recognized positions in both Per position and At interval modes. Unmatched views can still be saved in interval mode.

When a clean visible board first initializes a recorder, ChessStream now checks the latest chronologically started recorded game. If its placement matches that game's verified endpoint or a saved pending branch endpoint, ChessStream recovers that PGN rather than creating another. The same check runs before automatic unresolved-position recovery starts a FEN segment. Matching uses piece placement, since the screenshot cannot reliably supply side-to-move and FEN rights/counters. The app does not search older PGNs after a mismatch.

Validation: regression tests cover position deduplication across unrecognized transition images and game associations, verified and pending PGN reuse, and refusing to reuse an older non-latest PGN. Full suite and Windows portable packaging are checked in GitHub Actions.
