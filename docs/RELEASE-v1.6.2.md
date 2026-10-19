# ChessStream PGN Recorder v1.6.2

- Chess-related YouTube windows rank ahead of other apps in automatic selection and the manual Window chooser. Titles including speedrun, speed run, rating climb, chess, blitz and rapid receive stronger ranking.
- Startup opens a live capture and recognition preview for the selected YouTube window. Preview-only mode does not save screenshots, create PGNs or process game state. Press Start recording to switch the preview into a recording.
- The screenshot browser uses extended selection: Ctrl selects individual images and Shift selects a range. Selected screenshot files can be deleted from a button or the right-click menu; PGNs and game data remain.
- If a visible-FEN checkpoint was just created during live capture, the recorder retries the preserved preceding PGN before retaining the split. Clock OCR resets alone no longer block a legal midgame reconnect; declared results, terminal messages and changed player identities still do.

Validation: 19 focused local tests pass. Coverage includes YouTube-over-File-Explorer ranking, the chess title from the reported window list, screenshot multi-selection and ID-scoped deletion, and reconnecting a live FEN checkpoint to its preserved game. Windows packaging and physical fullscreen behavior require the tagged CI run and local device acceptance, respectively.
