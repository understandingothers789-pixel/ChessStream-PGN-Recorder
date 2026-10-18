# Windows 11 acceptance checklist

The installer is built, but these Windows hardware checks have not been run on the Linux build host. Record the exact machine, OS build and results when validating a release.

1. Install the unsigned EXE as a standard user in a clean Windows 11 x64 account without Python. Launch from Start and from the installed `.cmd`. Run the packaged-runtime import and GUI smoke commands in the GitHub workflow.
2. Capture a visible browser board on each monitor, including negative desktop coordinates and 100%, 125%, 150% and mixed display scaling. Check both orientation modes. Move and resize the region overlay and the tracked browser. Toggle browser/video fullscreen. Re-select if the HWND changes.
3. Calibrate Chess.com Neo from the true starting board. Capture an entire known game and compare its PGN move-for-move. Repeat with Lichess Cburnett and one other set. Add stream video with compression, arrows, highlights and a pointer. Record failures rather than extrapolating the small PNG benchmark.
4. Play known fast sequences at various rates and compare one-second versus adaptive capture. Test a pause, a review of old moves, a board flip, two consecutive games and a result requiring manual confirmation.
5. Export current, selected and session PGNs; open in Nibbler and at least one other GUI. Include midgame FEN/SetUp and a promotion. Verify unresolved branches never appear as mainline moves.
6. Confirm screenshot file frequency and temporary-frame behavior. Explicitly enable deduplication and check repeated screenshots stop while moves continue. Test each deletion scope, a future job, app-off catch-up and job cancellation. Check PGNs survive all image-only deletions.
7. Force-close the app during capture and restore the game. Test disk-full/write errors without losing the prior verified database state. Measure one-hour memory use and CPU with the browser playing normally; report exact settings and hardware.
8. Register configurable global hotkeys, conflict one with another application, and check focused fallback. Verify app shutdown unregisters them. Confirm no network activity is needed for normal recording.
9. Uninstall. The program files and shortcuts should be removed; the independent LocalAppData recording folder must remain.

Expected data directory: `%LOCALAPPDATA%\ChessStream PGN Recorder`. Do not mark this checklist complete without performing the checks.
