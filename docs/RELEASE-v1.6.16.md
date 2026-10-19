# ChessStream PGN Recorder v1.6.16

- Replace the app artwork with a white chess knight and mint video-play symbol on navy. Bundle transparent PNG and Windows ICO assets at 16 through 256 pixels for desktop/taskbar use. Retain the original artwork and a reproducible asset-conversion script.
- Create or refresh a per-user ChessStream PGN Recorder desktop shortcut on first Windows launch. It uses ChessStream artwork and the windowless launcher, rather than the generic Python or command-file icon. Launching a moved/updated app refreshes its own shortcut automatically. Settings offers a manual refresh action.
- Set a distinct Windows application identity and apply the custom icon at both application and window level. Use a content-specific cached icon path so new artwork can replace stale Windows icon-cache entries.
- Shortcut creation runs in the background, requires no administrator rights, changes no file associations, and passes paths as JSON data rather than executable shell text. Failures are logged without preventing the app from opening. No recognition models or runtime dependencies changed.

Validation: focused asset, shortcut and desktop integration tests passed locally. Tests check ICO resolutions/transparency, windowless target, safely passed paths and refresh idempotence. Tagged Windows CI runs the existing suite, portable inference/launcher checks and an actual desktop-shortcut test inspecting the .lnk target and icon.

Usage: extract the portable ZIP, launch it once, then use the ChessStream PGN Recorder shortcut on your desktop. Existing unrelated/manual Python shortcuts are not changed. The extracted folder must remain available. Desktop access policies can prevent shortcut creation; see Diagnostics / logs if the shortcut is missing.
