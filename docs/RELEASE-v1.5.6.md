# ChessStream PGN Recorder v1.5.6

The game library now opens a context menu when you right-click a game row. It offers Copy PGN, Export selected, and Delete saved PGN file(s). Right-clicking a row outside the selection selects that row; right-clicking a selected row preserves a multi-selection.

PGN deletion uses the same confirmation and app-managed-file safeguards as the library button. It removes the selected games' local autosaves and matching files in the configured automatic-export folder while preserving game data and manually exported files.

Validation: GUI regression tests verify the context-menu actions and selection behavior; the full test suite and Windows portable package checks run in GitHub Actions.
