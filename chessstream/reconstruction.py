"""Bounded, exhaustive-at-the-matched-depth legal reconstruction.

No engine ranking or plausible-looking SAN is used as evidence. Search limits
are reported and cannot certify a unique path. Hidden reversible cycles cannot
be recovered from identical images; search assumes the shortest observed gap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from time import perf_counter
import chess
import numpy as np
from .domain import Observation, board_labels


@dataclass
class SearchResult:
    paths: list[tuple[chess.Move, ...]] = field(default_factory=list)
    exhaustive: bool = True
    nodes: int = 0
    elapsed_ms: float = 0
    depth: int = 0
    shortest_proven: bool = False


def capture_path_rank(board: chess.Board, path: tuple[chess.Move, ...] | list[chess.Move]):
    """Rank equal-length paths by recaptures, then capture continuity/count.

    A capture followed by a capture onto the same square is the strongest
    cue: it commonly represents a natural recapture (for example cxd4 Qxd4).
    UCI ordering is applied by callers as a stable final tie-break.
    """
    state = board.copy(stack=False)
    same_square_recaptures = consecutive_captures = captures = 0
    previous_capture_square = None
    previous_was_capture = False
    for move in path:
        is_capture = state.is_capture(move)
        if is_capture:
            captures += 1
            if previous_was_capture:
                consecutive_captures += 1
                if previous_capture_square == move.to_square:
                    same_square_recaptures += 1
            previous_capture_square = move.to_square
        else:
            previous_capture_square = None
        previous_was_capture = is_capture
        state.push(move)
    return same_square_recaptures, consecutive_captures, captures


def select_capture_path(board: chess.Board, paths):
    """Choose one deterministic path from equally short equivalent results."""
    paths = list(paths)
    if len(paths) < 2:
        return paths
    ranked = sorted(paths, key=lambda path: (
        tuple(-score for score in capture_path_rank(board, path)),
        tuple(move.uci() for move in path)))
    return [ranked[0]]


class LegalSearcher:
    def __init__(self, max_plies=4, node_limit=60000, time_limit_ms=350, threshold=.70, path_limit=128):
        self.max_plies = max_plies
        self.node_limit = node_limit
        self.time_limit_ms = time_limit_ms
        self.threshold = threshold
        self.path_limit = path_limit

    def search(self, board: chess.Board, observed: Observation, *, target_turn: bool | None = None,
               first_shortest: bool = False, pawn_first: bool = False) -> SearchResult:
        result = SearchResult()
        start = perf_counter()
        target = observed.labels.tolist()
        mask = observed.probabilities.max(axis=1) >= self.threshold
        if mask.sum() < 60:
            result.exhaustive = False
            return result
        if observed.matches(board, self.threshold) and (target_turn is None or board.turn==target_turn):
            result.paths = [()]
            result.shortest_proven = True
            return result
        # Compile the observation once. Board comparisons in the search use
        # integer bitboards instead of rebuilding 64-element NumPy arrays.
        known = sum(1 << s for s in range(64) if mask[s])
        wanted = [0] * 7
        wanted_white = wanted_black = 0
        for s, label in enumerate(target):
            if not label or not mask[s]:continue
            bit = 1 << s
            wanted[(label - 1) % 6 + 1] |= bit
            if label <= 6:wanted_white |= bit
            else:wanted_black |= bit
        min_white, min_black = wanted_white.bit_count(), wanted_black.bit_count()
        # Pawns cannot move backward or be recreated by promotion. This cheap
        # reachability proof rejects new-game resets and unrelated openings
        # before traversing a tree of impossible continuations.
        for square,label in enumerate(target):
            if not mask[square] or label not in (1,7):continue
            color = label == 1
            direction = 1 if color else -1
            rank,file = chess.square_rank(square),chess.square_file(square)
            origins = board.pawns & board.occupied_co[color]
            if not any((rank-chess.square_rank(origin))*direction >= abs(file-chess.square_file(origin))
                       for origin in chess.scan_forward(origins)):
                result.elapsed_ms = (perf_counter()-start)*1000
                return result
        initial = (board.pawns,board.knights,board.bishops,board.rooks,
                   board.queens,board.kings,board.occupied_co[chess.WHITE])
        dead = set()
        path = []
        abort = False

        def castle_target_bonus(state, color, needed):
            # Castling can fill two required target squares in one turn only
            # when BOTH its king and rook destinations are actually wanted.
            # Granting this bonus for any home rook makes short openings with
            # three pawn moves look reachable in two turns and wastes a tree.
            rank=0 if color else 7
            if not (state.castling_rights & state.occupied_co[color]):return 0
            for king_file,rook_file,origin_file in ((6,5,7),(2,3,0)):
                king=chess.BB_SQUARES[chess.square(king_file,rank)]
                rook=chess.BB_SQUARES[chess.square(rook_file,rank)]
                origin=chess.BB_SQUARES[chess.square(origin_file,rank)]
                if state.castling_rights & origin and needed & king and needed & rook and wanted[6] & king and wanted[4] & rook:
                    return 1
            return 0

        def dfs(state: chess.Board, remaining: int):
            nonlocal abort
            result.nodes += 1
            if result.nodes > self.node_limit or (result.nodes % 64 == 0 and (perf_counter()-start)*1000 > self.time_limit_ms):
                abort = True
                result.exhaustive = False
                return False
            white,black = state.occupied_co[chess.WHITE],state.occupied_co[chess.BLACK]
            # Captured material cannot reappear; promotions preserve piece count.
            if white.bit_count() < min_white or black.bit_count() < min_black:
                return False
            mismatch = ((state.pawns ^ wanted[1]) | (state.knights ^ wanted[2]) |
                        (state.bishops ^ wanted[3]) | (state.rooks ^ wanted[4]) |
                        (state.queens ^ wanted[5]) | (state.kings ^ wanted[6]) |
                        (white ^ wanted_white)) & known
            if remaining == 0:
                changed = ((state.pawns ^ initial[0]) | (state.knights ^ initial[1]) |
                           (state.bishops ^ initial[2]) | (state.rooks ^ initial[3]) |
                           (state.queens ^ initial[4]) | (state.kings ^ initial[5]) |
                           (white ^ initial[6]))
                if mismatch == 0 and not changed & ~known and (target_turn is None or state.turn==target_turn):
                    result.paths.append(tuple(path))
                    result.shortest_proven = True
                    if first_shortest or len(result.paths) >= self.path_limit:
                        abort = True
                        result.exhaustive = False
                    return True
                return False
            if mismatch.bit_count() > 4 * remaining:
                return False
            # Each side can fill at most one required target square per turn;
            # allow one extra square if it retains any castling rights.
            white_turns = (remaining + int(state.turn == chess.WHITE)) // 2
            black_turns = remaining - white_turns
            white_needed=mismatch & wanted_white;black_needed=mismatch & wanted_black
            if (white_needed.bit_count() > white_turns + (castle_target_bonus(state,chess.WHITE,white_needed) if white_turns else 0)
                    or black_needed.bit_count() > black_turns + (castle_target_bonus(state,chess.BLACK,black_needed) if black_turns else 0)):
                return False
            key = (state.pawns,state.knights,state.bishops,state.rooks,state.queens,
                   state.kings,white,black,state.turn,state.castling_rights,state.ep_square,remaining)
            if key in dead:return False

            def priority(move):
                label = (move.promotion or state.piece_type_at(move.from_square)) + (0 if state.turn else 6)
                return (4 * (target[move.to_square] == label) +
                        2 * bool(mismatch & chess.BB_SQUARES[move.from_square]) +
                        bool(mismatch & chess.BB_SQUARES[move.to_square]))

            moves = state.legal_moves
            if pawn_first:
                moves=sorted(moves,key=lambda move:(state.piece_type_at(move.from_square)!=chess.PAWN,
                    -priority(move),-int(abs(move.to_square-move.from_square)==16),
                    abs(3.5-chess.square_file(move.to_square)),move.uci()))
            elif remaining > 1:moves = sorted(moves,key=priority,reverse=True)
            found = False
            for move in moves:
                if remaining == 1:
                    changed = chess.BB_SQUARES[move.from_square] | chess.BB_SQUARES[move.to_square]
                    if state.is_en_passant(move):
                        changed |= chess.BB_SQUARES[move.to_square + (-8 if state.turn else 8)]
                    if state.is_castling(move):
                        rank = chess.square_rank(move.from_square)
                        kingside = move.to_square > move.from_square
                        changed |= chess.BB_SQUARES[chess.square(7 if kingside else 0, rank)]
                        changed |= chess.BB_SQUARES[chess.square(5 if kingside else 3, rank)]
                    if mismatch & ~changed:
                        continue
                state.push(move)
                path.append(move)
                try:found = dfs(state, remaining-1) or found
                finally:path.pop();state.pop()
                if abort:return found
            # Only cache exhausted failures. Caching successes would hide
            # different shortest move orders reaching the same position.
            if not found:dead.add(key)
            return found

        # All alternatives at the shortest matching depth must be examined.
        state = board.copy(stack=False)
        for depth in range(1, self.max_plies+1):
            if target_turn is not None and (board.turn ^ bool(depth & 1))!=target_turn:continue
            result.depth = depth
            if (perf_counter()-start)*1000 > self.time_limit_ms:
                result.exhaustive = False
                break
            dfs(state, depth)
            if abort or result.paths:
                break
        result.elapsed_ms = (perf_counter()-start)*1000
        return result


@dataclass
class Branch:
    root_fen: str
    moves: tuple[str, ...]

    def board(self) -> chess.Board:
        b = chess.Board(self.root_fen)
        for uci in self.moves:
            b.push_uci(uci)
        return b


@dataclass
class ReconstructionUpdate:
    verified: list[str] = field(default_factory=list)
    status: str = "waiting"
    alternatives: list[list[str]] = field(default_factory=list)
    nodes: int = 0
    search_ms: float = 0
    recovered: bool = False
    tie_broken: bool = False
    ignored_squares: list[int] = field(default_factory=list)


class Reconstructor:
    def __init__(self, initial: chess.Board, searcher: LegalSearcher | None = None, roots: list[str] | None = None, confirmation_plies: int = 0):
        self.initial_fen = initial.fen()
        self.board = initial.copy(stack=True)
        self.searcher = searcher or LegalSearcher()
        self.branches = [Branch(fen, ()) for fen in (roots or [initial.fen()])]
        self.verified: list[str] = []
        self.history: list[str] = [initial.board_fen()]
        self.status = "recording" if len(self.branches) == 1 else "awaiting side to move"
        self.incomplete = False
        self.confirmation_plies = confirmation_plies

    def _recover_provisional(self, observed, update):
        """Replace an unconfirmed hover or unsupported reversible detour.

        Never changes verified moves. Direct alternatives at equal depth remain
        ambiguous; prior constraints are retained where they still fit. A fully
        supported direct transition is required before discarding a hypothesis;
        every changed square must be observed, even if arrows hide other pieces.
        """
        if not any(b.moves for b in self.branches) or len({b.root_fen for b in self.branches}) != 1:
            return None
        lengths = [len(b.moves) for b in self.branches]
        if len(set(lengths)) == 1 and all(observed.placement() == b.board().board_fen() for b in self.branches):
            return None
        direct = LegalSearcher(self.searcher.max_plies, self.searcher.node_limit,
                               self.searcher.time_limit_ms * .7, self.searcher.threshold,
                               self.searcher.path_limit).search(self.board, observed)
        update.nodes += direct.nodes;update.search_ms += direct.elapsed_ms
        if not direct.exhaustive or not direct.paths:
            return None
        paths = [tuple(m.uci() for m in path) for path in direct.paths]
        compatible = [p for p in paths if any(p[:len(b.moves)] == b.moves for b in self.branches)]
        candidates = compatible
        if not candidates and (max(lengths) <= 1 or len(paths[0]) < min(lengths)):
            candidates = paths
        if not candidates:
            return None
        old = {(b.root_fen, b.moves) for b in self.branches}
        root = self.board.fen()
        result = [Branch(root,p) for p in candidates]
        update.recovered = any((root,p) not in old for p in candidates) and not compatible
        # A shorter supported line also removes unverified reversible cycles.
        update.recovered |= any(len(b.moves)>len(paths[0]) for b in self.branches)
        return result

    def observe(self, observed: Observation) -> ReconstructionUpdate:
        candidates=self._noise_candidates(observed)
        if candidates and self.searcher.max_plies>2:
            # Do not invent a longer capture/return detour merely to explain
            # one weak disappearing piece. First compare short observations
            # with short continuations that leave that square uncertain.
            probe=Reconstructor.restore(self.serialize(),LegalSearcher(2,
                min(8000,self.searcher.node_limit),min(50.,self.searcher.time_limit_ms),
                self.searcher.threshold,self.searcher.path_limit))
            short=probe._observe_exact(observed)
            if short.status=='unmatched position • recording continues':
                retry=self._retry_noisy_squares(observed,short,candidates)
                if retry.ignored_squares:return retry
                candidates=()
            elif not probe.incomplete and not short.status.startswith(('obstructed','review / rewind')):
                self._adopt_probe(probe)
                return short
        update=self._observe_exact(observed)
        if update.status != 'unmatched position • recording continues':
            return update
        return self._retry_noisy_squares(observed,update,candidates)

    def _noise_candidates(self, observed):
        if len(self.branches)>8:return ()
        probabilities=observed.probabilities
        labels=observed.labels;confidence=probabilities.max(axis=1)
        if not np.any((confidence>=self.searcher.threshold)&(confidence<.90)):return ()
        candidates=set()
        for branch in self.branches:
            expected=board_labels(branch.board())
            supported=probabilities[np.arange(64),expected]
            candidates.update(int(s) for s in np.flatnonzero(
                (labels!=expected)&(confidence>=self.searcher.threshold)&
                (confidence<.90)&(supported>=.08)))
        return tuple(sorted(candidates)) if len(candidates)<=4 else ()

    def _adopt_probe(self, probe):
        for name in ('initial_fen','board','branches','verified','history','incomplete','status'):
            setattr(self,name,getattr(probe,name))

    def _retry_noisy_squares(self, observed, original_update, candidates):
        """Let legal continuity resolve at most two weak, unchanged squares.

        A disappearing piece or a queen/knight misread is not a move. Retain
        the raw distribution, and only try erasing a small disputed area when
        an existing legal board label still has model support. The ordinary
        search requires positive evidence on every changed square, including
        captures, castling, en passant and promotions. Erasures therefore
        cannot supply a move's missing source or destination.
        """
        if not candidates:return original_update
        # Bounded fallback only. A limited retry cannot prove that competing
        # interpretations were exhausted and must leave the recorder intact.
        started=perf_counter();node_budget=min(8000,self.searcher.node_limit//4)
        time_budget=min(50.,self.searcher.time_limit_ms*.20)
        nodes=0;search_ms=0.;state=self.serialize()
        for count in range(1,min(2,len(candidates))+1):
            matches=[]
            for squares in combinations(sorted(candidates),count):
                remaining_nodes=node_budget-nodes
                remaining_ms=time_budget-(perf_counter()-started)*1000
                if remaining_nodes<1 or remaining_ms<=0:return original_update
                searcher=LegalSearcher(min(2,self.searcher.max_plies),remaining_nodes,
                    remaining_ms,self.searcher.threshold,self.searcher.path_limit)
                probe=Reconstructor.restore(state,searcher)
                evidence=observed.with_unknown(squares)
                retry=probe._observe_exact(evidence)
                nodes+=retry.nodes;search_ms+=retry.search_ms
                if probe.incomplete:return original_update
                if retry.status.startswith(('unmatched','review / rewind','obstructed','search limit')):
                    continue
                if all(evidence.matches(branch.board(),self.searcher.threshold) for branch in probe.branches):
                    signature=(probe.initial_fen,tuple(probe.verified),
                               tuple(sorted((b.root_fen,b.moves) for b in probe.branches)))
                    matches.append((signature,probe,retry,squares))
            if not matches:continue
            if len({row[0] for row in matches})!=1:return original_update
            if (perf_counter()-started)*1000>time_budget:return original_update
            _,probe,retry,squares=matches[0]
            self._adopt_probe(probe)
            retry.ignored_squares=list(squares)
            retry.nodes=original_update.nodes+nodes
            retry.search_ms=original_update.search_ms+search_ms
            self.status=retry.status+' • recognition uncertain on '+', '.join(chess.square_name(s) for s in squares)
            retry.status=self.status
            return retry
        return original_update

    def _observe_exact(self, observed: Observation) -> ReconstructionUpdate:
        update = ReconstructionUpdate()
        if observed.confidence < .50 or (observed.probabilities.max(axis=1) >= self.searcher.threshold).sum() < 60:
            self.status = update.status = "obstructed / low confidence"
            return update
        # A hidden board, rewind or transient animation does not destroy pending paths.
        survivors: list[Branch] = []
        all_complete = True
        infer_turn = not self.verified and len({b.root_fen for b in self.branches})>1
        evidence_start=perf_counter()
        cache={}
        recovered = self._recover_provisional(observed, update)
        if recovered is not None:
            survivors = recovered
        # For unknown initial turn compare both roots at the same shortest depth.
        # Otherwise a reversible three-ply detour from the wrong turn can mask a
        # directly observed one-ply transition forever.
        for depth in (range(1,self.searcher.max_plies+1) if infer_turn else [self.searcher.max_plies]):
            if survivors:break
            for branch in self.branches:
                state=branch.board()
                key=(state.fen(),depth)
                if key in cache:
                    result=cache[key]
                else:
                    remaining_nodes=self.searcher.node_limit-update.nodes
                    remaining_ms=self.searcher.time_limit_ms-(perf_counter()-evidence_start)*1000
                    if remaining_nodes<=0 or remaining_ms<=0:
                        all_complete=False
                        break
                    searcher=LegalSearcher(depth,remaining_nodes,remaining_ms,self.searcher.threshold,self.searcher.path_limit)
                    result=searcher.search(state,observed)
                    cache[key]=result
                    update.nodes += result.nodes
                    update.search_ms += result.elapsed_ms
                all_complete &= result.exhaustive
                for path in result.paths:
                    survivors.append(Branch(branch.root_fen, branch.moves+tuple(m.uci() for m in path)))
            if survivors or not all_complete:
                break
        if not all_complete:
            # Re-run from the previous evidence next time; never keep a partial search
            # as if it contained every legal alternative.
            self.incomplete = True
            self.status = update.status = "search limit • evidence retained"
            return update
        self.incomplete = False
        if not survivors:
            if observed.placement() in self.history[:-1]:
                self.status = update.status = "review / rewind • live game preserved"
            else:
                self.status = update.status = "unmatched position • recording continues"
            return update
        self.incomplete = False
        unique = {(b.root_fen, b.moves): b for b in survivors}
        # When several shortest move orders explain the same observed endpoint,
        # prefer a natural capture/recapture sequence and keep one stable line.
        # Distinct starting roots remain separate hypotheses.
        grouped = {}
        for branch in unique.values():
            endpoint = branch.board().board_fen()
            grouped.setdefault((branch.root_fen, endpoint), []).append(branch)
        self.branches = []
        for (root_fen, _), branches in grouped.items():
            root = chess.Board(root_fen)
            update.tie_broken |= len(branches) > 1
            selected = select_capture_path(root, [tuple(chess.Move.from_uci(m) for m in b.moves)
                                                    for b in branches])[0]
            selected_uci = tuple(m.uci() for m in selected)
            self.branches.append(next(b for b in branches if b.moves == selected_uci))
        roots = {b.root_fen for b in self.branches}
        if len(roots) == 1 and not self.verified:
            self.initial_fen = self.branches[0].root_fen
            self.board = chess.Board(self.initial_fen)
            self.history = [self.board.board_fen()]
        prefix = min(len(b.moves) for b in self.branches)
        if len(roots) != 1:
            prefix = 0
        for i in range(prefix):
            if len({b.moves[i] for b in self.branches}) != 1:
                prefix = i
                break
        common = self.branches[0].moves[:prefix]
        if self.confirmation_plies:
            # Repetition or elapsed time cannot prove a piece was dropped.
            # The opponent's reply confirms the preceding move, while the last
            # ply stays provisional until later evidence or explicit review.
            supported = max(0,min(len(b.moves) for b in self.branches)-self.confirmation_plies)
            common = common[:min(len(common),supported)]
        for uci in common:
            # Defensive validation at the only commit point.
            move = chess.Move.from_uci(uci)
            if move not in self.board.legal_moves:
                raise RuntimeError("Internal reconstruction invariant violated")
            self.board.push(move)
            self.verified.append(uci)
            self.history.append(self.board.board_fen())
            update.verified.append(uci)
        if common:
            root = self.board.fen()
            self.branches = [Branch(root, b.moves[len(common):]) for b in self.branches]
        if self.confirmation_plies and len(self.branches)==1 and len(self.branches[0].moves)==1:
            self.status = "provisional move • waiting for opponent response"
        else:
            self.status = "uncertain • choose a legal sequence" if any(b.moves for b in self.branches) or len(self.branches)>1 else "recording"
        update.status = self.status
        update.alternatives = [list(b.moves) for b in self.branches if b.moves]
        return update

    def bridge_gap(self, observed: Observation, searcher: LegalSearcher | None = None) -> ReconstructionUpdate | None:
        """Atomically attach the shortest legal continuation from the saved prefix.

        Pending hovers are hypotheses, so search again from the verified board.
        Equal shortest paths to the same endpoint are resolved by capture
        continuity, then stable UCI ordering. A limited search changes nothing.
        """
        searcher = searcher or self.searcher
        if observed.uncertain_squares(max(.8, searcher.threshold)):
            return None
        roots = list(dict.fromkeys(b.root_fen for b in self.branches)) if not self.verified else None
        probe = Reconstructor(self.board,searcher,roots,self.confirmation_plies)
        update = probe.observe(observed)
        if probe.incomplete or not probe.branches or any(
                b.board().board_fen() != observed.placement() for b in probe.branches):
            return None
        if not self.verified:
            self.initial_fen = probe.initial_fen
            self.board = chess.Board(self.initial_fen)
            self.history = [self.board.board_fen()]
        for uci in probe.verified:
            self.board.push_uci(uci)
            self.verified.append(uci)
            self.history.append(self.board.board_fen())
        self.branches = probe.branches
        self.incomplete = False
        self.status = probe.status
        return update

    @staticmethod
    def rank_branches(branches, observed: Observation, active_turn=None):
        """Order visual hypotheses by square likelihood, using the clock only as a tie-break.

        The clock is contextual evidence for which side is currently thinking; it
        never changes the legal search result or confirms a move by itself.
        """
        probabilities = np.clip(observed.probabilities, 1e-8, 1.0)
        indices = np.arange(64)
        ranked = []
        for branch in branches:
            board = branch.board()
            labels = board_labels(board)
            likelihood = float(np.log(probabilities[indices, labels]).mean())
            clock_match = int(active_turn is not None and board.turn == active_turn)
            ranked.append((likelihood, clock_match, branch))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return ranked

    def choose(self, index: int) -> list[str]:
        if self.incomplete:
            raise ValueError("Increase search limits or correct the position before selecting a path")
        branch = self.branches[index]
        if not self.verified:
            self.initial_fen = branch.root_fen
            self.board = chess.Board(branch.root_fen)
            self.history = [self.board.board_fen()]
        moves = list(branch.moves)
        for uci in moves:
            self.board.push_uci(uci)
            self.verified.append(uci)
            self.history.append(self.board.board_fen())
        self.branches = [Branch(self.board.fen(), ())]
        self.status = "recording • sequence confirmed manually"
        return moves

    def serialize(self) -> dict:
        return {"initial_fen":self.initial_fen,"verified":list(self.verified),
                "branches":[{"root_fen":b.root_fen,"moves":list(b.moves)} for b in self.branches],
                "status":self.status,"incomplete":self.incomplete,"confirmation_plies":self.confirmation_plies}

    @classmethod
    def restore(cls, data: dict, searcher: LegalSearcher | None = None) -> Reconstructor:
        r = cls(chess.Board(data["initial_fen"]), searcher)
        for uci in data["verified"]:
            r.board.push_uci(uci)
            r.history.append(r.board.board_fen())
        r.verified = list(data["verified"])
        r.branches = [Branch(b["root_fen"], tuple(b["moves"])) for b in data["branches"]]
        r.status = data.get("status", "recovered")
        r.incomplete = data.get("incomplete",False)
        r.confirmation_plies = data.get("confirmation_plies",0)
        return r
