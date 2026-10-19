# Recognition improvements without changing the model

ChessStream v1.6.4 keeps the existing offline screenshot CNN and adds a small layer of legal continuity checks. A piece that appears to vanish or change type is a recognition dispute until a supported legal transition explains it. A capture and a promotion remain normal legal changes.

## Open-source review

Reviewed on 2026-10-19:

| Repository | Findings and decision |
| --- | --- |
| [scoriiu/fenshot](https://github.com/scoriiu/fenshot) at `04d8bbb365e1abc679007cb1ac836fa2dc1e40ac` | Already supplies the bundled MIT screenshot model. Its recognizer compares detector and snapped grid candidates and checks for one king per side. The model revision is still current. Keep the small offline model; improve evidence handling around it. Its FEN composition guesses castling rights from home squares, which ChessStream deliberately does not adopt because move history matters. |
| [Elucidation/tensorflow_chessbot](https://github.com/Elucidation/tensorflow_chessbot) at `db893cf50c68307b2494cc0e92c26f70aca3ab5a` | MIT, established screenshot tile-classification approach, but uses older TensorFlow/SciPy tooling. Adopting it adds runtime migration work without demonstrated accuracy gains on this corpus. |
| [tmasouris/end-to-end-chess-recognition](https://github.com/tmasouris/end-to-end-chess-recognition) at `f8ad5652ee8e25d5d1570662c6ebc43eff67b846` | Research implementation targeting smartphone photographs and physical boards, using a different image/model pipeline. It does not establish a better replacement for browser screenshots. |

Upstream code was inspected as research; no new model, third-party source, dependency, network inference or telemetry was added.

## Implemented checks

The existing search already uses legal moves and material constraints, including captures, pawn movement, castling, en passant and promotions. Its failure mode was treating an incorrect top classifier label as an exact position constraint. Sometimes a longer legal sequence could explain a vanished queen by inventing a queen sacrifice and a bishop return.

The updated search first checks short legal continuations when a few labels are weakly disputed. It can then try one or two squares as unknown if the previous legal label still has at least 0.08 model support and the conflicting winning score is below 0.90. At most four candidate squares are considered, and at most two are ignored. Every newly changed move square must still meet the ordinary positive-evidence threshold. Hidden capture destinations, castling rook squares, en passant captures and promotion destinations cannot be supplied by an erasure.

All combinations at the smallest erasure count must complete within budget and agree on the resulting reconstruction. Otherwise the retry is discarded. The retry covers up to two new plies and has a 50 ms / 8,000-node budget; its preliminary exact short search has a separate budget of up to 50 ms / 8,000 nodes. The existing configured search remains available when the retry cannot establish a result. Clean frames take the existing path.

This is a continuity assumption for temporarily obscured pieces, not proof of an invisible square's contents. The UI names disputed squares, diagnostics retain raw labels and scores, and affected verified moves receive explicit PGN comments. Opponent-response protection remains active. Temporary probes use independent state copies so unsuccessful searches cannot alter saved move lists. Repeated identical warnings do not create repeated audit entries.

Screenshot image files are unnecessary for these checks. Frames are processed in memory and PGN/FEN metadata is persisted. Local-video replay now honors the same default-off image-saving setting as live capture.

## Measurements

Run `.venv/bin/python scripts/evaluate_continuity.py` from the repository root. The exact output is committed as [recognition-continuity-v1.6.4.json](recognition-continuity-v1.6.4.json).

- **116 actual browser-captured positions / 7,424 square classifications:** zero raw model errors before and after. These samples already passed; they cannot establish a reduction in real YouTube error rates.
- **14 browser-image reconstruction sequences:** verified prefixes and final candidates remain correct, including orientation changes, arrows, cursor samples and native held-piece drags.
- **Five controlled classifier-fault sequences:** correct completed lines increased from 0/5 to 5/5. These deliberately alter probability vectors to simulate disappearing pieces, queen/knight and color mistakes, a phantom piece and the queen-sacrifice detour. They are explicitly separate from image accuracy measurements.
- The recorded Linux CPU comparison averaged about 1.05 ms before and 1.02 ms after for reconstruction on the real-image sequences, with about 8.74 ms model inference. This small timing difference is noise, not a speed improvement claim. Desktop capture and GUI costs are excluded.
- The focused local suite contains 26 tests and finishes in about three seconds here. New cases cover unsafe hidden destinations, strong contradictions, three simultaneous faults, all special move rules, persistent hovers, raw-evidence preservation, diagnostics and screenshot-free local replay.

## Further improvements worth validating

1. **Pixel continuity per square:** compare an in-memory normalized patch against the last trusted appearance. This could flag a sudden confident label change when the actual pixels barely changed. It needs tests showing that real captures and promotions are never suppressed.
2. **Alignment arbitration:** score the detector's best few grid crops using both checker geometry and piece consistency, following fenshot's candidate-grid idea. This targets crop errors that affect many squares together.
3. **Trusted theme prototypes:** learn a small per-session color/appearance reference only from strongly observed legal positions. It may help unusual white/black artwork, provided ambiguous frames cannot contaminate that reference.

Small tile-translation ensembles did not reduce errors in the local degradation probes, so they were not added to the runtime. Strong classifier errors, unfamiliar themes, tiny boards and heavy overlays remain open problems. Any future improvement needs measured gains on additional real stream captures before a general accuracy claim.
