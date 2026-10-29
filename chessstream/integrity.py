"""Independent structural checks at recording boundaries, without guessing moves."""
import chess
import numpy as np
from .domain import LABELS


def observation_error(obs):
    try:return _observation_error(obs)
    except (TypeError,ValueError,AttributeError):return 'unsupported recognition output'


def _observation_error(obs):
    values=np.asarray(obs.probabilities)
    if values.shape!=(64,len(LABELS)):return 'wrong recognition output shape'
    if not np.isfinite(values).all():return 'non-finite recognition scores'
    if np.any(values<0) or np.any(values>1):return 'recognition scores outside probability range'
    if not np.allclose(values.sum(axis=1),1,atol=.02):return 'recognition scores are not normalized'
    if not np.isfinite(obs.quality) or not 0<=obs.quality<=1:return 'invalid recognition quality'
    if obs.orientation not in ('white','black'):return 'invalid board orientation'
    return None


def replay_accepted(rec):
    """Derive the endpoint independently; Board.push itself is not a legality check."""
    board=chess.Board(rec.initial_fen)
    for uci in rec.verified:
        move=chess.Move.from_uci(uci)
        if move not in board.legal_moves:raise ValueError('Accepted PGN contains an illegal move: '+uci)
        board.push(move)
    if board.fen()!=rec.board.fen():raise ValueError('Accepted PGN and reconstructed board disagree')
    return board
