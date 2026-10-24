"""Evidence rules shared by automatic PGN writers.

Search may propose histories; only a complete, unique legal explanation can
be committed automatically. Repeated images establish stability, not order.
Manual choices are validated separately and audited by their callers.
"""
from dataclasses import dataclass
import chess


def speculative_detour(board, path):
    """Repeated unseen moves by a non-pawn require video confirmation."""
    if len(path) < 3:
        return False
    state = board.copy(stack=False)
    destinations = {chess.WHITE: set(), chess.BLACK: set()}
    for move in path:
        piece = state.piece_at(move.from_square)
        if piece is None or move not in state.legal_moves:
            return True
        prior = destinations[state.turn]
        if move.from_square in prior and piece.piece_type != chess.PAWN and not state.is_castling(move):
            return True
        if not state.is_castling(move):
            prior.discard(move.from_square)
            if piece.piece_type != chess.PAWN:
                prior.add(move.to_square)
        state.push(move)
    return False


@dataclass(frozen=True)
class CommitEvidence:
    kind: str
    path: tuple | None = None

    @property
    def automatic(self):
        return self.kind == 'unique'


def assess_search(board, result, observed=None, threshold=.8):
    """Classify a search without selecting or mutating a possible history."""
    if not result.exhaustive:
        return CommitEvidence('incomplete')
    if not result.paths:
        return CommitEvidence('unresolved')
    if not result.shortest_proven:
        return CommitEvidence('incomplete')
    paths = {tuple(path) for path in result.paths}
    if len(paths) != 1:
        return CommitEvidence('ambiguous')
    path = next(iter(paths))
    trial = board.copy(stack=False)
    for move in path:
        if move not in trial.legal_moves:
            return CommitEvidence('invalid')
        trial.push(move)
    if observed is not None and not observed.matches(trial, threshold):
        return CommitEvidence('invalid')
    if speculative_detour(board, path):
        return CommitEvidence('speculative')
    return CommitEvidence('unique', path)
