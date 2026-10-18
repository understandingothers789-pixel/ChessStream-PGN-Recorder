A tight board selection can now find nearby player names and clocks automatically. The recorder adds a temporary margin around the detected board once per second, defaulting to 18% of the board size on every side. Adjust the margin or disable it in Settings. The selected board, piece recognition and permanent board screenshots stay separate from the temporary context capture. Existing source tracking supplies updated board coordinates after moves, resizes or board reacquisition.

If the wider selected source already contains that context, its pixels are reused. Otherwise a small additional screen capture supplies the board and text together, so a clock from a newer frame is not attached to older board evidence. Padding is clipped to the desktop. Covered/offscreen names or clocks cannot be recovered from missing pixels.

Explicit cover labels such as NAME BLURRED and DEFINITELY NOT … remain Unknown rather than being mistaken for real account names. Readable clocks remain usable. Name parsing also tolerates a trailing OCR separator after the rating.

Text recognition continues to use bundled, pretrained open-source PaddleOCR PP-OCRv4 models and ONNX Runtime on the local CPU. No new model training, paid API or online inference was added.

Validation: 104 automated tests pass locally. A production-worker regression reads names/clocks outside a tight selection and saves only one board-sized screenshot. A separate actual X11/MSS test moves and resizes a window showing a retained native Chess.com capture; both names and both clock readings matched at both sizes. Measurements are in `docs/context-v1.5.json`. This is not physical Windows capture acceptance, and the user-linked YouTube video could not be opened here, so its first game has not been tested end to end. Windows CI separately validates source tests, portable inference, GUI startup and the command launcher before release.

Download **ChessStream-PGN-Recorder-Portable.zip**, extract it into a new writable folder, close the older copy and open **Launch ChessStream.cmd**. No installer, administrator access or separate Python setup is required. Existing games and screenshots are kept.
