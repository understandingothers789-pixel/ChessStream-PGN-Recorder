# Keeping a recording together through short gaps — 1.6.24.dev1

This work starts from development commit 2a838d3 on
`fix/non-destructive-pgn-gap-joins`. It implements the October 23 request to
reduce early truncation, preserve midgame continuity and reconnect temporary
segments through the shortest supported legal continuation.

## Causes found and addressed

1. A short reachability search could miss a continuation and start a new-game
   timer when names were unreadable. Material counts and a distinct-origin
   pawn matching check now identify positions still compatible with forward
   play. Such a position stays with the active game while recovery runs.
   Passing this check is a necessary condition, not proof of reachability.
   Small mismatches and the existing possible-boundary grace period now also
   allow recovery, including correction of recent inferred suffixes.
2. Every new position canceled a running recovery. A request can now finish
   while up to 12 later changed observations arrive. Its game, accepted prefix,
   root, lifecycle generation, mode, headers and ended state must still match.
   Later frames must have passed stability gating and fit a bounded legal
   forward chain before application. Rewinds, repeated positions, weak frames,
   layout changes, identity changes and stopped games invalidate the request.
3. The 12-image RAM buffer could fill with cursor/highlight changes on the
   same board. Recovery now has a separate 96-position RAM history of stable
   recognition distributions, coalesced by placement and isolated by game ID.
   It copies incoming distributions and retains intermediate boards even when
   their pixels have left the image buffer. These positions are not image files.
4. The deeper worker discarded all ambiguous results, even complete useful
   candidate sets. It now uses the normal reconstruction policy: retain
   complete shortest alternatives, accept their supported shared prefix, and
   follow subsequent observations through the surviving histories. No tie is
   selected automatically. Unobserved repeated-piece detours remain rejected.
5. Negative reachability cache entries ignored new pending candidates. The
   cache key now includes those candidates, so a formerly distant position
   can become a one-move continuation as soon as recovery finds its anchor.
6. A temporary checkpoint could remain separate when its 75 ms live join
   failed. Stable checkpoints now automatically queue a deeper join with
   their explicitly recorded parent. This never scans arbitrary archive games.
   Sources are revalidated, originals are preserved, and a combined derivative
   becomes active only if the request still matches the current recording.
   A duplicate failed request waits for changed source/candidate data. Live
   gap recovery takes priority over automatic parent joining.
7. Starting after White and Black's first moves previously lost that pair by
   default. A completed unique search of at most two plies now restores such
   an opening automatically, including after a confirmed opponent change.
   Those moves are labeled inferred. Longer ambiguous openings retain a FEN.
   An app-created early FEN may gain a unique prefix on resume, preserving
   move clocks and backing up its original PGN/state. Imported or configured
   FENs are respected; unknown screenshot rights are passed to the joiner
   explicitly rather than interpreted as known loss of castling rights.
8. Rollback recovery snapshots advanced the accepted board while leaving
   their pending root at the initial position. The snapshot root now agrees
   with its accepted prefix. A regression corrects an inferred `exd5` to the
   later-supported `Nf3` while keeping the same game ID and old PGN in audit.

## How shortest recovery works

The forward search still tries smaller ply counts first and exhausts
alternatives at the first matching depth. A limited search cannot establish
uniqueness. With retained intermediate frames, each observed interval gets
its shortest explanations; this is the shortest history consistent with
those landmarks, which can be longer than a shortcut ignoring them.

New `reachability.py` bounds deeper searches by minimum piece travel. It
accounts for pawn direction/double pushes, knight distance and optimistic
unblocked movement. Castling grants a rook move for free, and non-pawn bounds
are relaxed when promotion might fit. It allows the same origin to explain
multiple target pieces when calculating a lower bound, so it underestimates
work rather than excluding legal paths. Exact pawn-origin matching is used
only for the separate irreversible-material check. Bounds apply to fully
recognized targets and searches of at least five plies; ordinary short live
searches retain their existing work. The per-search cache is bounded and does
not retain its owner through a bound-method reference cycle.

Recovery retries can inspect six, eight and ten plies, with at most 300,000
nodes and 1.5 seconds per request. Three identical failed attempts stop until
new observations or settings provide a reason to retry. Catch-up after an
older completed request shares 75 ms and 8,000 nodes, with at most two plies
between each later stable observation. Automatic saved-parent joins use the
existing separate five-second worker budget. Limits are cooperative, not hard
real-time guarantees; capture and inference still compete for CPU resources.

Unknown turn is retained as multiple roots and compared at equal shortest
depth. A screenshot after `e4` followed only by `e4 c5 Nf3` can fit two starting
turns and move orders. An intermediate `c5` frame or a later `...Nc6` can
distinguish them. A default White root must not create `Qe2–Qd1` to fix parity.

## Broader options considered

| Approach | Decision and reason |
| --- | --- |
| Preserve an active identity through plausible skipped moves | Implemented, with opponent/reset/result evidence evaluated first. |
| Use intermediate positions as landmarks | Implemented as a separate bounded metadata history. |
| Finish older work and validate newer forward steps | Implemented; avoids perpetual cancellation during continuing play. |
| Keep all completed shortest histories | Implemented; later observations can eliminate different endpoints/turns. |
| Reconnect temporary fragments automatically | Implemented only for their recorded parent, with source and live-state validation. |
| Recover the initial move pair | Implemented when a completed search establishes a unique shortest pair. |
| Minimum travel and irreversible pawn/material checks | Implemented as optimistic bounds and necessary conditions, using python-chess for actual legality. |
| Progressively larger work during thinking time | Implemented with finite retries and changed-input detection. |
| Roll back a recent inferred mistake | Existing route repaired and exercised during boundary grace; previous PGN/state retained. |
| Majority-vote each square across unrelated times | Deferred: a mixed board can describe a position never actually shown. Existing selective weak-square continuity remains. |
| Reverse legal search from the screenshot | Deferred: missing captured pieces, turn, rights, en passant and promotions make valid predecessor generation much harder than reversing moves. |
| Keep the entire search tree between time slices | Deferred: requires additional bounded state and invalidation rules. Current retries increase bounded depth and reuse observed landmarks. |
| Ask a chess engine for the best-looking line | Not used to certify history. Strongest play and actual video moves can differ; existing capture/pawn order remains a search preference. |
| Read YouTube's playback timestamp for explicit seeks | Possible future corroboration; it is often outside the selected board and is not necessary for the current fixes. |
| Save images around every failure | Optional screenshot saving remains available. Default storage uses metadata; the 12-image RAM buffer is unchanged. |

## Validation and performance

The new workflow tests cover a missing initial pair, changed opponents at an
early board, an old FEN prefix with clocks/backup, imported-FEN protection,
unreadable names with a long plausible gap, rollback of a bad inferred
capture, image-buffer churn, forward play while recovery is blocked on an
explicit test barrier, rewind/identity/weak-frame rejection, candidate cache
refresh, pending histories continuing through later frames, unknown turn,
automatic parent joining, ambiguous parent joins, finite retries, pawn
matching, castling, en passant and promotion.

The earlier forward-only stale-result test now asserts that a certified
`...Nc6` may extend completed work. The early opponent-change test now expects
the uniquely recovered first pair. Both still check game identity/endpoints;
new interruption tests and all previous false-queen regressions remain.
No tests were deleted.

Local Linux/Python 3.12 validation: **205 passed in 7.95 seconds**;
`git diff --check` passed and the offscreen desktop rendered successfully.

`scripts/benchmark_gap_continuity.py` compares the same completed searches
with the new travel bound switched off/on. Three-run local results:

| Fixture | Baseline mean | Travel-bound mean | Nodes before/after | Shortest alternatives |
| --- | ---: | ---: | ---: | ---: |
| Routine two plies | 0.496 ms | 0.418 ms | 23 / 23 | 1 / 1 |
| Six-ply capture gap | 288.833 ms | 174.674 ms | 36,496 / 22,802 | 2 / 2 |
| Saved middlegame gap | 814.482 ms | 676.071 ms | 109,631 / 88,632 | 29 / 29 |

Every compared shortest path was identical. The routine case uses the same
algorithm in both modes; its timing difference is measurement variation.
The deeper fixtures improved about 40% and 17% in this workspace. These are
CPU search measurements, not a measured live-video error rate or frame rate.
Machine-readable results are in `gap-continuity-benchmark-2026-10-23.json`.
The final local test count and Windows portable checks are reported with the
delivered commit and artifact.

## Remaining uncertainty

There is no promise to reconstruct arbitrary gaps. Exact transpositions can
hide move order permanently; an identical later board does not reveal it.
Incomplete searches and unobserved shuffles stay outside the authoritative
PGN. Later observed moves remain in pending histories when their earlier
order is unresolved, available for explicit verification.

Material/pawn compatibility cannot identify a game. With hidden names and
clocks, a genuinely new game that also fits forward play may need the Game
menu's New game action. Conversely, apparent irreversible jumps still have
the existing boundary timer, with recovery allowed during its grace period.
High-confidence recognition errors remain possible. Real Windows video seeks,
fullscreen/DPI changes and a complete new YouTube session need live acceptance
testing beyond the deterministic workflows and packaged smoke tests.

The 96-position solver buffer is temporary RAM. The separate 10,000-transition
diagnostic trace remains bounded persistent metadata, never a source of
unrelated archived-game anchors. Screenshot saving remains off by default.
