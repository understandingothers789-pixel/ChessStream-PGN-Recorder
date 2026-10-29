# Opening order popularity — dev9

When the legal startup search finds multiple equal shortest three-ply opening orders, ChessStream now prefers the order seen most often in a public game database sample. It preserves the other order as a PGN variation and marks the missing opening as inferred. Frequency never overrides legality, square confidence, the observed endpoint, or the existing restrictions on ambiguous gaps in an ongoing game.

For the reported position:

| Inferred order | Games in sample |
|---|---:|
| d4 Nf6 c4 | 26,419 |
| c4 Nf6 d4 | 94 |

The sample also contains 87,763 starts with d4 versus 16,008 with c4. The algorithm first compares the frequency of the complete candidate order, then first-move and two-ply-prefix counts to break ties. Comparing complete orders uses more information than only asking whether d4 is generally more popular than c4. Missing entries do not make a legal line impossible. Equal or unavailable counts use the existing deterministic fallback. The selected PGN's opening comment records the sample and count; it does not claim the order was observed.

## Source and offline use

The bundled **44.7 KB** table contains aggregate prefixes up to three plies from **279,942** eligible games in the [November 2025 Lichess Elite Database](https://database.nikonoel.fr/lichess_elite_2025-11.zip). The source publisher filters strong-player games (2500+ versus 2300+, excluding bullet). This is an elite-player sample from one month, not all online chess or a live popularity estimate. Sampling biases may differ from the video being recorded.

The archive contained 280,246 game headers; 304 openings were excluded because the generator requires a standard start and three legal, unannotated opening plies on the first movetext line. The generator validates all included SAN moves and counts prefixes. Archive SHA-256: `1ffa577aa0a1352fa04c9a890a6706049a3a79edc52810b136758d1e2a1a2eab`. The aggregate asset records its source URL, selection, sample size and hash. Only aggregate moves/counts are shipped; the 80 MB source ZIP, full games, and player names are not shipped.

No token, account, or network access is needed while recording. This replaces the central-pawn heuristic with measured counts wherever the database has coverage. If the bundled table is unavailable/corrupt, recording continues with the deterministic legal fallback. This change does not retrain the image reader or expand the set of legal candidate moves.

During development, unauthenticated Lichess opening explorer requests to both `/masters` and `/lichess` returned HTTP 401. The separate ChessDB.cn API was accessible, but its documented `score`, `rank` and `winrate` fields describe evaluation, not played-game frequency; they are not used as popularity counts. See [ChessDB documentation](https://www.chessdb.cn/cloudbookc_api_en.html) and [Lichess explorer documentation](https://lichess.org/api#tag/Opening-Explorer). No authentication restriction is bypassed.

## Reproduction and validation

Download the pinned public ZIP separately, then run `python scripts/build_opening_popularity.py /path/to/archive.zip`. The developer tool performs no network access, bounds ZIP size/expansion, verifies the pinned hash and writes the aggregate asset. Refreshing to a different corpus requires deliberately reviewing/updating the source metadata and hash. No installation of a large database is required by the app.

Tests check the reported counts and selected order, a case where measured counts reverse the old heuristic, count totals at every depth, legal validity of all stored prefixes, corruption/missing-entry fallback, operation with network sockets disabled, and corpus-prefix parsing. Existing startup tests still verify the inferred three moves, Black's turn, retained alternative, and subsequent recorded moves. General ambiguous gaps retain their prior safety policy.
