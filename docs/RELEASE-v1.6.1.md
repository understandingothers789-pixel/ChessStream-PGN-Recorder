# ChessStream PGN Recorder v1.6.1

When multiple equally short legal move sequences reach the same observed board position, the recorder now selects one repeatably. It prioritizes consecutive captures, with recaptures onto the same square first, then total captures and stable UCI move order. The PGN marks moves chosen by this rule as inferred so the selected sequence is not mistaken for directly observed evidence.

The same rule applies to automatic continuation and joining saved recordings. Distinct starting-position hypotheses remain separate. Bitboard search continues to compare square-state differences without rebuilding every square label at each node.

Validation: 16 focused local tests pass. The tests cover capture-priority selection, deterministic equal-path handling, ordinary move tracking, PGN joining and existing gap-reconstruction behavior.
