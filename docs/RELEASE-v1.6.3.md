# ChessStream PGN Recorder v1.6.3

- When a visible-FEN checkpoint can be joined to the preceding preserved game, the recorder validates the joined legal line against the current board and makes the combined PGN the active/main game. It keeps the source checkpoint in the library, marked as reconnected, and labels inferred gap moves.
- Screenshot image writing is now off by default. Capture, recognition, game reconstruction, and PGN joining still run on in-memory frames. Enable **Settings → Storage & saving → Save screenshot images to disk while recording** to keep images for review.
- Added checks for checkpoint joining and active PGN selection, screenshot-saving defaults and stable-position rules, and the desktop default.

The local focused test suite and Windows tagged workflow validate this release. Live behavior across a particular browser, Windows scaling setup and fullscreen transition still needs acceptance on the target computer.
