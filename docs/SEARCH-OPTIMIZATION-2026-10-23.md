# Search optimization — development build 1.6.24.dev2

The profile identified move generation, sorting and board pushes as the main
costs of gap recovery. This change reduces that work without selecting fewer
valid shortest alternatives or weakening the commitment rules.

Changes in `chessstream/reconstruction.py`:

- On the last move, generate only candidates capable of placing the required
  piece at the observed destination and vacating a mismatched origin. Preserve
  castling exceptions and check en passant and promotions legally.
- With two plies remaining, the current player also has only one turn left.
  Its move must fill any missing target belonging to that color: the opponent
  cannot do that for it. If no target is missing, allow sacrifices that the
  opponent could capture on the final move.
- When the opponent has exactly the minimum number of pieces required by the
  observation, exclude further captures before generating/pushing them. Handle
  en passant separately because its destination square is empty.
- Carry the previous capture square into recursive calls rather than undoing
  and replaying the previous move to discover it again.
- Share the piece lookup used by move ordering, and calculate castling bonuses
  only when needed to satisfy the target-square lower bound.

Capture/recapture, double pawn push and stable ordering preferences remain the
same. The search still reports incomplete work as incomplete. Existing limits,
ambiguity handling, recovery safeguards, screenshot settings and game identities
remain in force. Skipping impossible branches can let a bounded search finish
where the previous implementation timed out; that is the intended difference.

## Measurements

Five interleaved repetitions against commit `ed253d6`, using identical fixtures,
budgets and the existing travel bound in both versions:

| Search fixture | Previous mean | Optimized mean | Reduction | Nodes before → after |
| --- | ---: | ---: | ---: | ---: |
| Routine two-ply opening | 0.361 ms | 0.229 ms | 36.6% | 23 → 4 |
| Six-ply capture gap | 167.164 ms | 53.818 ms | 67.8% | 22,802 → 6,566 |
| Saved middlegame gap | 640.562 ms | 324.985 ms | 49.3% | 88,632 → 46,919 |

All shortest path sets matched exactly, including both alternatives in the
capture fixture and all 29 alternatives in the middlegame fixture. The JSON
report includes SHA-256 fingerprints of the complete sorted path sets.

These are local CPU search measurements, not whole-video/OCR performance or
recognition accuracy measurements. Times vary by hardware and system load;
sub-millisecond opening differences have little practical impact.

Reproduce from the repository root with the project Python environment:

```sh
python scripts/benchmark_search_optimization.py --repeats 5 --output /tmp/search-optimization.json
```

The comparison loads our pinned, trusted reference commit from local Git into
a temporary module. It does not download or execute external configuration.

## Validation

The local suite passes: **206 tests**. An independent unpruned legal-move oracle
checks all legal next moves across opening, random middlegame, both colors of
castling, both colors of en passant, capture promotions and underpromotions.
Each endpoint is checked with full visibility and with four uncertain squares.
Two-ply oracle cases also cover castling and a last-turn sacrifice followed by
capture, protecting the exception in the new pruning rule. Existing recovery,
rewind, game-boundary, ambiguity and false-piece-excursion tests remain intact.

Files changed: reconstruction, search tests, both benchmark scripts, this report
and its JSON measurements, README, and development version labels in the GUI,
package metadata and installer. No model, dependency, image-recognition or
security setting changed. Main remains untouched.
