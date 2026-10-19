# ChessStream PGN Recorder v1.5.7

ChessStream now automatically chooses a visible YouTube browser window when it starts without a saved hand-drawn region. Titles containing chess-related words rank first; ties and generic YouTube titles preserve Windows' window-list order. If the browser is still opening, it retries every two seconds until a match appears. The existing Window, Monitor, and Select capture region controls remain available, and a saved hand-drawn region is respected.

Automatic selection tracks the browser client area. Board detection locates the chessboard inside that area; it does not start recording by itself. Click Start recording when the board is visible. Automatic window choice was covered by ranking and GUI startup tests; physical Windows desktop capture still depends on the browser remaining visible and is not hardware-validated here.

Validation: unit tests cover chess-title ranking, fallback order, and automatic GUI startup selection. The complete automated suite and Windows portable-package validation run in GitHub Actions.
