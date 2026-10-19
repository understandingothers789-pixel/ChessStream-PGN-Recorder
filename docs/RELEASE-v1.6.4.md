# ChessStream PGN Recorder v1.6.4

- Legal continuity can keep up to two weakly disputed, unchanged squares uncertain while following clearly observed moves. Missing pieces, queen/knight/color mistakes and phantom extra pieces no longer always force an unmatched position or a new FEN segment.
- A short continuation with an uncertain piece is checked before accepting a longer exact-label capture/return detour. Changed move squares still require positive image evidence; uncertainty cannot fill a move's hidden source or destination. Existing provisional-move protection remains active.
- The UI names disputed squares. Logs retain the raw observation, and affected verified moves carry an explicit PGN comment. Repeated identical warnings are deduplicated.
- Fixed local-video replay saving screenshots despite the default-off image-saving setting. Move reconstruction and joining continue without screenshot files.
- No model, runtime dependency, subscription or network service was added.

Validation: 26 focused local tests pass in about three seconds. The continuity evaluator retains correct reconstruction across 14 actual browser-image sequences (116 measured positions) and recovers five separately labeled controlled classifier-fault sequences. The retained images already had zero raw classifier errors, so this is not a measured percentage improvement on arbitrary YouTube videos. See `docs/RECOGNITION_IMPROVEMENTS.md` and `docs/recognition-continuity-v1.6.4.json` for sources, exact measurements and limits. Windows packaged inference and launcher checks run in tagged CI; physical Windows fullscreen behavior still needs local acceptance.
