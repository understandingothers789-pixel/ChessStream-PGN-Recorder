"""Bounded, exhaustive-at-the-matched-depth legal reconstruction.

No engine ranking or plausible-looking SAN is used as evidence. Search limits
are reported and cannot certify a unique path. Hidden reversible cycles cannot
be recovered from identical images; search assumes the shortest observed gap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
import math
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


class LegalSearcher:
    def __init__(self, max_plies=4, node_limit=60000, time_limit_ms=350, threshold=.70, path_limit=128):
        self.max_plies = max_plies
        self.node_limit = node_limit
        self.time_limit_ms = time_limit_ms
        self.threshold = threshold
        self.path_limit = path_limit

    def search(self, board: chess.Board, observed: Observation) -> SearchResult:
        result = SearchResult()
        start = perf_counter()
        target = observed.labels
        mask = observed.probabilities.max(axis=1) >= self.threshold
        if mask.sum() < 60:
            result.exhaustive = False
            return result
        if observed.matches(board, self.threshold):
            result.paths = [()]
            return result
        abort = False
        def dfs(state: chess.Board, remaining: int, path: tuple[chess.Move, ...]):
            nonlocal abort
            if abort:
                return
            result.nodes += 1
            if result.nodes > self.node_limit or (result.nodes % 64 == 0 and (perf_counter()-start)*1000 > self.time_limit_ms):
                abort = True
                result.exhaustive = False
                return
            labels = board_labels(state)
            mismatch = int(np.count_nonzero((labels != target) & mask))
            if remaining == 0:
                if mismatch == 0:
                    result.paths.append(path)
                    if len(result.paths) >= self.path_limit:
                        abort = True
                        result.exhaustive = False
                return
            # A move changes at most four squares (castling). This is a safe bound.
            if mismatch > 4*remaining:
                return
            mismatch_bits = sum(1 << s for s in np.flatnonzero((labels != target) & mask).tolist()) if remaining == 1 else 0
            for move in state.legal_moves:
                if remaining == 1:
                    changed = chess.BB_SQUARES[move.from_square] | chess.BB_SQUARES[move.to_square]
                    if state.is_en_passant(move):
                        changed |= chess.BB_SQUARES[move.to_square + (-8 if state.turn else 8)]
                    if state.is_castling(move):
                        rank = chess.square_rank(move.from_square)
                        kingside = move.to_square > move.from_square
                        changed |= chess.BB_SQUARES[chess.square(7 if kingside else 0, rank)]
                        changed |= chess.BB_SQUARES[chess.square(5 if kingside else 3, rank)]
                    if mismatch_bits & ~changed:
                        continue
                state.push(move)
                dfs(state, remaining-1, path+(move,))
                state.pop()
                if abort:
                    return
        # All alternatives at the shortest matching depth must be examined.
        for depth in range(1, self.max_plies+1):
            result.depth = depth
            dfs(board.copy(stack=False), depth, ())
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


class Reconstructor:
    def __init__(self, initial: chess.Board, searcher: LegalSearcher | None = None, roots: list[str] | None = None):
        self.initial_fen = initial.fen()
        self.board = initial.copy(stack=True)
        self.searcher = searcher or LegalSearcher()
        self.branches = [Branch(fen, ()) for fen in (roots or [initial.fen()])]
        self.verified: list[str] = []
        self.history: list[str] = [initial.board_fen()]
        self.status = "recording" if len(self.branches) == 1 else "awaiting side to move"
        self.incomplete = False

    def observe(self, observed: Observation) -> ReconstructionUpdate:
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
        # For unknown initial turn compare both roots at the same shortest depth.
        # Otherwise a reversible three-ply detour from the wrong turn can mask a
        # directly observed one-ply transition forever.
        for depth in (range(1,self.searcher.max_plies+1) if infer_turn else [self.searcher.max_plies]):
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
        if not survivors:
            if observed.placement() in self.history[:-1]:
                self.status = update.status = "review / rewind • live game preserved"
            else:
                self.status = update.status = "unmatched position • recording continues"
            return update
        self.incomplete = False
        unique = {(b.root_fen, b.moves): b for b in survivors}
        self.branches = list(unique.values())
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
            self.branches = [Branch(root, b.moves[prefix:]) for b in self.branches]
        self.status = "uncertain • choose a legal sequence" if any(b.moves for b in self.branches) or len(self.branches)>1 else "recording"
        update.status = self.status
        update.alternatives = [list(b.moves) for b in self.branches if b.moves]
        return update

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
                "status":self.status,"incomplete":self.incomplete}

    @classmethod
    def restore(cls, data: dict, searcher: LegalSearcher | None = None) -> Reconstructor:
        r = cls(chess.Board(data["initial_fen"]), searcher)
        for uci in data["verified"]:
            r.board.push_uci(uci)
            r.history.append(r.board.board_fen())
        r.verified = data["verified"]
        r.branches = [Branch(b["root_fen"], tuple(b["moves"])) for b in data["branches"]]
        r.status = data.get("status", "recovered")
        r.incomplete = data.get("incomplete",False)
        return r
