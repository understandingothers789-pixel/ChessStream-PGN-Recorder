# Known limitations and validation status

This document describes the current development branch. Automated Linux and
Windows checks do not establish accuracy on arbitrary YouTube streams. See the
[October 24 comprehensive check](COMPREHENSIVE-CHECK-2026-10-24.md) for the current
measurements, fixes and boundaries of validation.

1. **Recognition is fallible.** The bundled screenshot CNN and offline text
   models cover a finite set of piece styles and English horizontal text. Small
   boards, video compression, arrows, drags, overlays and unfamiliar themes can
   fail. Classifier scores are not measured accuracy percentages; a high score
   can still be wrong. The current changes do not retrain either model.
2. **Capture needs visible pixels.** MSS sees windows covering the board.
   Minimized, hidden, DRM-protected and off-desktop boards cannot be recovered
   by the capture backend. Tracked windows can reacquire changed geometry, but
   fullscreen, replacement window handles, mixed DPI and multi-monitor behavior
   still require physical Windows acceptance.
3. **Moves need evidence.** Search considers shortest legal histories within
   time, node and depth limits. A unique complete explanation can be inferred;
   equal alternatives stay pending, with only their supported shared prefix
   exported. Capture/recapture and pawn preferences order searches and displayed
   choices; they do not prove an unobserved order. Repeated unseen non-pawn
   excursions require explicit confirmation. A witnessed intermediate board
   separates capture gaps; it must not be treated as another unseen move.
4. **Stable images cannot resolve ambiguity.** The default 0.5-second settling
   rule can accept a complete unique non-speculative hypothesis. It cannot
   establish which of several transposed histories occurred, or prove that a
   held piece was dropped. Opponent replies, visible clocks and game-ending
   messages provide additional bounded evidence. A final move may still need
   confirmation, and premoves are excluded until supported.
5. **Openings are bounded.** By default up to three opening plies can be inferred from the standard start.
   A small three-ply startup transposition can select an explicitly inferred
   order and retain the equal alternative as a PGN variation. This exception
   does not resolve ambiguous gaps in an ongoing game. Longer unseen opening inference is
   opt-in and still requires completed unique evidence. Actual unobserved order
   may remain unknown. Imported or explicitly configured FENs retain their
   supplied history fields; an image-derived midgame has unknown turn, castling
   rights and en passant history and may need a provisional FEN start.
6. **Game identity can be ambiguous.** Names, clocks, results, witnessed resets
   and known positions help separate new games from review. A missing link alone
   does not prove a new game: forward-compatible gaps may remain unresolved
   while deeper recovery runs. Identical rematches and replays with hidden
   metadata can be indistinguishable. Manual New game, Continue and Analysis
   controls remain available. Ordinary opening similarity does not select an
   arbitrary archived game.
7. **Recovery is finite.** Twelve changed downscaled images and 96 coalesced
   stable position observations are retained in RAM. Deeper background searches
   have bounded budgets, at most three unchanged-evidence retries and bounded
   catch-up. Long jumps, noisy endpoints and missing intermediate boards may
   remain unresolved. The recorder retries only a temporary checkpoint's
   recorded parent automatically; manual joining can consider older PGNs.
   Combined records preserve their original sources.
8. **Review is separate from play.** Observed legal alternatives can be stored
   as PGN variations linked to witnessed positions. Unknown analysis jumps may
   require manual linkage. Rewinding should preserve the played mainline rather
   than fabricate forward shuffles; some review/rematch distinctions remain
   impossible without additional identity or clock evidence.
9. **Results and clocks have limits.** Board-provable outcomes and supported
   English result overlays can be detected. Relative You Won/Lost messages need
   the correct configured account color. Hidden results, languages outside the
   OCR corpus and unidentified winners may need editing. Clocks are sampled
   observations, not exact release times; unseen intermediate moves may have no
   clock comment. Names require nearby clock evidence and repeated scans.
10. **Continuity correction is conservative.** At most two weak unchanged
    squares may be carried through a short continuation when the previous label
    retains classifier support. Strong contradictions, hidden move endpoints,
    incorrect roots and larger recognition errors are not repaired arbitrarily.
11. **Screenshots are optional.** Saving is off by default; inference and PGN
    recovery use RAM observations. Enabling saving uses the chosen position or
    interval policy. Recognized duplicate positions are skipped, including across
    layout changes. A recognition mistake can still create an extra screenshot.
    Image deletion leaves game records intact. Saved images remain until the
    user deletes them or enables retention; scheduled jobs require the app to
    run and catch up on the next launch.
12. **Diagnostics have privacy and growth implications.** The board trace keeps
    the latest 10,000 diagnostic transitions, coalescing exact consecutive
    payload repeats. This is an internal cap, not a user-adjustable setting.
    Exported diagnostics include player names, settings, hypotheses, PGNs and
    logs, without screenshots or the live database. Observation and audit tables
    are separate from this cap and can grow during long use. There is no current
    one-hour/long-duration memory or storage acceptance measurement.
13. **Local files still require trust.** Bundled model hashes, bounded decoding,
    non-pickle templates and trusted custom-model directories reduce risk.
    Selecting a custom ONNX model remains a trust decision. Python package
    advisory scans do not audit every native library embedded in binary wheels.
    Build hashes record inputs, but the distribution is unsigned and does not
    provide a fully hash-locked transitive supply chain. ONNX telemetry is
    explicitly disabled; Python-level offline tests do not monitor every native
    Windows operating-system event.
14. **Distribution checks have boundaries.** Windows CI validates source tests,
    packaged inference, offline OCR, GUI startup, the command launcher and
    shortcut artwork. Physical Windows 11 display scaling, hotkeys, unattended
    multi-game streams, disk-full behavior and long-running performance still
    require hardware acceptance. The optional NSIS installer is separate from
    the portable ZIP; a portable CI pass is not an installer/uninstaller test.

The retained browser PNG corpus is useful regression evidence, not a statistical
study of arbitrary live streams. A passing suite does not mean all bugs or all
security vulnerabilities have been eliminated.

15. **Playback audio is optional evidence.** Built-in fingerprints cover default Chess.com and Lichess sounds, not all themes or playback speeds. Other apps on the output device and commentary can cause false/missed cues. Audio never proves an unseen move order; physical loopback acceptance remains outstanding.
16. **Integrity checks detect contradictions.** Legal replay catches illegal accepted moves or a mismatch with the reconstructed board, and can restore a validated checkpoint. It cannot prove that a consistently misrecognized legal position actually appeared. Checks now run under the manager lock and precede invalid-frame error snapshots.
