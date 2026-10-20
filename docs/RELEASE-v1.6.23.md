# ChessStream PGN Recorder v1.6.23

You can now combine older saved PGNs while a live recording continues. The combine action saves a separate combined game and leaves the live recorder's active game and move history unchanged. It still blocks the operation if the active PGN is among the selected records, since that PGN is being updated by the capture worker. Stop capture to combine that game.

Validation: 100 local tests passed. Coverage includes joining two compatible saved segments while preserving a third active recording, plus the library behavior that permits older records and rejects a selection containing the active record. Windows portable packaging and launcher checks run on the v1.6.23 tag.
