# ChessStream PGN Recorder v1.5.8

ChessStream now prefers the best visible YouTube chess window on every launch, including when an older screen region was saved. It ranks YouTube titles for chess-related terms, preserves window-list order for ties, and retries every two seconds if the browser is still opening. If no YouTube window is available, the saved source remains usable. Manually choosing a monitor, window, or capture region disables automatic switching for that run.

Automatic selection tracks the browser client area. Board detection locates the chessboard inside that area; it does not start recording by itself. Click Start recording when the board is visible.

Validation: local GUI tests verify selection from an empty configuration and replacement of a previously saved screen region; ranking tests cover chess-title preference and fallback order. GitHub Actions runs the full test suite and validates the Windows portable package and launch script. Physical capture still depends on the browser remaining visible and is not hardware-validated here.
