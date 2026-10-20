# Development handoff implementation — 1.6.24.dev0

Starting point: 195158e5773c4a95302a1ceba6fab18c8c72ce3c on
fix/non-destructive-pgn-gap-joins, draft PR #1. These changes stay on that
development branch; they are not a main-branch release.

## Supplied log and existing protections

The 582-line excerpt alternates between recordings 7b9e5861… (12 plies,
analysis) and 589ff479… (2 plies, unmatched) with the same displayed clocks
and identities. It later reads the interface label **Board** as Black and
switches to a third record. The interleaving is consistent with competing
capture loops, but this older log has no process/thread IDs and does not prove
which process emitted each entry. It also lacks a complete source-frame/FEN sequence,
so this pass cannot replay that entire incident from the log alone.

The starting branch already contains the global GUI lock, PID/thread logging,
false-result rejection, truncated-name handling, early rewind/root correction,
the timed-ambiguity fix and cancellation of stale detour flags. Those changes
were retained. The unchanged starting suite passed 151 tests locally.

## Remaining causes and fixes

1. **Conflicting automatic writers.** The analysis linker still used
   first_shortest=True, and a legacy history-recovery path could save an
   unsolicited analysis variation. A stable result popup could also promote
   a pending path after the current search was incomplete. Shared evidence
   classification now requires complete shortest-path evidence, uniqueness,
   legality, endpoint agreement and no speculative repeated-piece route.
   Analysis extension is tied to its observed cursor. Existing transpositions
   remain navigable without generating new moves.
2. **Saved search budgets leaked into live capture.** The saved helper raised
   limits to at least five seconds even when called by checkpoint recovery.
   Live checkpoint attempts and their fallback share 75 ms, with four plies and
   at most 8,000 nodes per search. Join previous snapshots its inputs, performs deeper work outside the
   capture thread and recorder lock, then validates the result before applying
   it. Saved requests share a five-second total budget across previous
   candidates; library searches share a bounded total budget across segments.
3. **Protected gaps could not recover.** A same-player hold canceled or bypassed
   the deeper worker every frame. An identified unresolved move gap is now
   distinct from an uncertain game boundary: the accepted PGN remains protected,
   while the recovery worker can prove a unique continuation.
4. **Stale work could match A after a seek through B.** Tokens previously compared
   the final placement but not its observation generation. Monotonic evidence
   revisions now invalidate A → B → A results, as well as game/root/prefix and
   lifecycle changes. Searches poll cancellation; discarded work cannot append
   moves. Only one recovery request and one saved-join request are owned at once.
5. **Original automatic-join sources were rewritten.** Automatic checkpoint
   joining now creates a derivative, as manual joining already did. Tests check
   source PGN strings byte for byte. Inferred suffix and timed-drop corrections
   retain the prior PGN, state, clocks and inference metadata in audit records.
   Supplied/imported FEN constraints, including zero castling rights and legal
   en-passant state, are respected. Explicitly unknown image-derived history is
   stored separately. A bare screenshot with both turn hypotheses can use the
   uniquely established continuation instead of forcing its default White root.
   A failed full segment join cannot be bypassed with a direct old-endpoint
   path that discards the intervening segment; both records stay separate.
6. **OCR vocabulary was being used as identity evidence.** Python, Codex,
   Slowkaru and Candidate are accepted as usernames in appropriate player bands.
   Spatial/rating/clock evidence and prose/URL/control structure filter overlays.
   The unadorned Board control is rejected; a rated username is not discarded
   merely because it shares an interface word. Existing partial-name and actual
   opponent-change checks remain.
7. **Opening guessing contradicted the requested correctness policy.** The
   directed opening solver remains available as a proposal/search aid, but its
   first route is no longer automatically exported. Even the opt-in opening
   setting now requires a complete unique search; otherwise the visible FEN
   remains the start. Normal first-move recording and observed continuations
   remain automatic. Unseen repeated-piece saved joins also need explicit
   verification, even if a search happened to find only one shortest route.
8. **Old library records were treated as continuation candidates.** The user's
   observation that clearing the library helped prompted a second-game audit.
   Automatic checkpoint recovery scanned up to 16 records; archived endpoints
   could also be selected with just one matching visible name. Recovery now
   uses only the active record and its explicitly saved checkpoint source.
   Archive returns require both current, confirmed player identities, respect
   confirmed separation and exclude imported records. A shared starting/opening
   position cannot identify an older game at startup, including rematches.
   The regression records two games with and without an old library and checks
   identical outcomes and preservation of the old PGN. This reproduces a
   reachable failure route; it does not prove which route caused the user's
   entire past recording incident.
9. **Completed/stopped jobs and missing diagnostic context.** Recovery results
   now include headers and ended state in their validity token and cannot append
   after a manual result edit or stop. Each compared recognized board has a
   persistent metadata trace, including unstable frames and lifecycle holds.
   Repeats coalesce with comparison counts and first/last timestamps. The newest
   10,000 transitions are retained across sessions; no pixels are written.
   Observed placement is separate from reconstructed FENs because side to move,
   castling and en passant are not directly visible. Candidate summaries include
   at most eight histories and their first 32 moves plus total counts/endpoints;
   full pending state remains in the game record. Diagnostics export this trace
   with PGNs, audits and logs. Low-confidence boards remain evidence, not moves.

## Commitment routes reviewed

| Route | Automatic evidence requirement |
| --- | --- |
| Live Reconstructor | Exhausted alternatives; only a supported shared prefix; detours remain pending |
| Half-second settling | One complete surviving path, or shared search assessment; time alone never chooses an order |
| Background recovery | Shared assessment for every retained intermediate frame and final gap |
| Opening/bootstrap/backfill | Complete unique route; proposed ambiguous orders retain a visible FEN |
| New-game buffered frames | Each recorded transition is a complete unique one-ply search |
| Rewind/history | Position navigation is classification; speculative links cannot append variations |
| Analysis/replay | Explicit analysis/observed replay context, observed anchor and completed unique continuation |
| Terminal pending move | One supported pending move; incomplete/speculative paths remain excluded |
| Saved-PGN joins | Exact known constraints, complete search, unique non-detour path or explicit revalidated choice |
| Manual SAN/confirmation/import | Explicit user-supplied history; legal validation and existing audits |

The remaining first-match calls classify reachability, detect an apparent
rewind, or probe a corrected one-move hover. They do not append their returned
paths to PGNs. Capture-continuity ranking is a search/preview preference,
never proof of history.

## Files and architectural changes

- commitment.py: shared pure evidence classifier and detour rule.
- reconstruction.py: cancellation, stop reasons, exact en-passant target
  constraints, bounded retained hypotheses, explicit unknown-history metadata.
  Limit hits preserve the previous evidence instead of trimming to a winner.
- games.py, game_boundaries.py, game_extras.py: automatic commitment callers,
  observation revisions, asynchronous previous-join coordination,
  result protection and non-destructive checkpoint derivatives.
- saved_joins.py, gap_join.py: immutable background saved work, shared
  budgets, known/unknown FEN constraints and explicit speculative-gap choices.
- analysis_tracking.py, lifecycle.py: anchored analysis and a recoverable
  same-player unresolved-gap state.
- capture.py, gui.py: background polling/cancellation, race protection when
  capture starts during a library join, game ID/pending-history tooltip and
  compact diagnostics. Queue/revision/timing information stays in saved logs.
- results.py: contextual username handling.
- storage.py, diagnostics.py: bounded board-state trace and diagnostic export,
  independent of screenshot saving and game deletion.

No new service, network recognizer, telemetry, model download or screenshot
disk requirement was introduced. Existing neural models, board reacquisition,
selective weak-square continuity and the bounded 12-image RAM buffer remain.
Temporal averaging that could synthesize a never-seen board was not added.

## Regression coverage and intentional compatibility changes

tests/test_commitment_pipeline.py adds complete manager/worker/GUI workflows
for ambiguous analysis, normal single-move variations, stale A → B → A work,
cancellation, hypothesis limits, actual buffered repeated-piece moves,
nonblocking previous joins, changed live-state rejection, a library/capture
race, incomplete terminal moves, actual FEN constraints, an unresolved gap
that successfully recovers, and known opening turn recovery.
It also covers populated versus empty libraries, incomplete identity readings,
confirmed rematches, common openings at restart, result/stop invalidation,
repeat-coalesced FEN traces, trace retention/export without images, and failed
checkpoint fallback limits without dropping a source segment.

No tests were deleted. Earlier tests that explicitly demanded a guessed
five/ten-ply opening now assert the visible FEN and subsequent observed moves;
clock and endpoint checks remain. Checkpoint-join tests now require a new
derivative ID and unchanged original PGNs. A screenshot-FEN fixture explicitly
declares its unknown history. The synthetic queen-shuttle preservation test
now also asserts that automatic joining refuses it before exercising explicit
confirmation. The UI callback mock accepts the new asynchronous keyword.

Local validation on Linux/Python 3.12: **181 passed in 8.58 seconds**;
git diff --check passed, and the offscreen application launch rendered the
desktop successfully. The unchanged baseline had 151 tests. Windows portable
validation and its downloadable artifact are linked in the delivery message.
CPU timings are reproducible using:

    python scripts/benchmark_commitment.py --output docs/commitment-benchmark-2026-10-20.json

The JSON distinguishes unique, ambiguous and unresolved outcomes. It compares
the bounded live checkpoint workload with the deeper saved-search workload;
the smaller live budget intentionally leaves hard work to the background.
These are CPU search measurements, not a promised screen-capture frame rate.
Capture logs now estimate missed scheduling slots; source video frame loss
cannot be measured from screenshots alone.

Three-run local means: unique two-ply search 0.557 ms; four-knight ambiguous
search 2.087 ms; the live-budget fixture 17.173 ms (34.331 ms worst, unresolved);
the deeper saved fixture 887.308 ms (890.034 ms worst, 29 alternatives, held).
Metadata tracing across 64 comparisons averaged 0.296 ms (0.504 ms worst),
retaining 16 coalesced rows totaling 19,526 bytes of JSON. These storage timings
are specific to this workspace; Windows disks and heavily ambiguous states can
cost more. There is no claim of measured real-video accuracy or CPU utilization.

## Remaining limits and acceptance

Automated test success is distinct from real-world live-video validation.
This pass uses controlled observation sequences, real retained OCR/board
fixtures, offscreen GUI checks and packaged Windows smoke checks. It does not
establish error rates for a new full YouTube session or physical fullscreen/
DPI changes on the user's Windows desktop.

A unique shortest legal route is still an inference under the shortest-gap
assumption; unseen repetitions cannot be ruled out. Exact transpositions may
never reveal their historical order. Persistent high-confidence recognition
errors, hidden names/clocks and identical rematches remain possible sources
of uncertainty. Larger gaps can exceed bounded work and stay unresolved.
Search budgets are cooperative, checked periodically; PGN parsing and file
writes are not hard real-time operations.

Legacy recordings made before these fixes are not silently corrected. Clearing
the library is not required; explicitly select an intended game for manual
resumption, and close old builds that do not honor the current global lock.
Original recordings and revisions remain available for review. The diagnostic
trace contains player names, positions and clock readings and stays local until
the user exports/shares a bundle; old trace entries age out at the fixed cap.
