# Lichess-inspired PGN component — dev15

The user supplied the HTML of a Lichess analysis page. Its notation uses paired
main-line columns interrupted by compact inline alternative lines. The desktop
app now uses that presentation in Live recording and the Game library:

- Numbered White/Black pairs, without the old status prefixes and grid borders.
- Shaded alternative lines at their branch point, including nested alternatives.
- Clickable moves, a green selected-move background, adjacent clock annotations.
- Left/Right and Up/Down navigation through displayed notation; Home/End.
- Mainline and variation selections update the reconstructed board. Live review
  stays pinned until Follow latest or the latest mainline move is selected.
- Pending moves have their own clearly unsaved label. Generated diagnostic
  comments remain in tooltips; ordinary comments appear beneath main-line rows.
- Right-click Copy PGN in the library; existing live copy/export/FEN actions remain.

This is a native Qt rich-text view, not a web browser or embedded Lichess page.
No Lichess scripts, stylesheets, fonts or images are downloaded or bundled.
PGN text is escaped, external links cannot open, resources cannot load, and
annotation-derived tooltips cannot introduce HTML tags. The change concerns
presentation and navigation; the PGN recording and longest-line rules remain.

Live snapshots include the persisted PGN tree so saved variations appear during
recording. Parsed live documents and rendered notation are cached until their
inputs change. The hidden existing tree/table models retain editing and selection
integration; they are no longer the visible notation UI.

Validation: 325 local tests passed. New checks cover nested lines, clocks, literal
HTML-like comments, blocked resources/URLs, mouse and arrow activation, selection
of live/library variations, returning to live, and black-to-move FEN numbering.
A 380-pixel-wide offscreen rendering was visually inspected. Physical Windows font
rendering and DPI behavior remain to be checked on the user's desktop.
