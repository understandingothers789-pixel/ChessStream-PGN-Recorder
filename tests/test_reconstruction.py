import io
import chess
import chess.pgn
import pytest
from chessstream.domain import Observation
from chessstream.reconstruction import LegalSearcher, Reconstructor, Branch
from chessstream.games import export_pgn


@pytest.mark.parametrize("fen,moves", [
    (chess.STARTING_FEN, "e4 e5"),
    (chess.STARTING_FEN, "e4 d5 exd5"),
    ("r3k2r/ppp2ppp/2n5/3pp3/3PP3/2N5/PPP2PPP/R3K2R w KQkq - 0 10", "O-O O-O-O"),
    ("7k/P7/8/8/8/8/8/7K w - - 0 1", "a8=N"),
    ("7k/8/8/3pP3/8/8/8/7K w - d6 0 1", "exd6"),
])
def test_special_and_missing_frames(fen,moves):
    b=chess.Board(fen)
    r=Reconstructor(b,LegalSearcher(max_plies=4,time_limit_ms=5000,node_limit=500000))
    expected=[]
    for san in moves.split():
        move=b.parse_san(san);expected.append(move.uci());b.push(move)
    update=r.observe(Observation.from_board(b))
    assert update.verified==expected
    assert r.board.fen()==b.fen()


def test_ambiguous_move_order_is_not_invented():
    b=chess.Board()
    r=Reconstructor(b,LegalSearcher(max_plies=4,time_limit_ms=15000,node_limit=1000000))
    for san in "Nf3 Nf6 Nc3 Nc6".split():b.push_san(san)
    u=r.observe(Observation.from_board(b))
    assert not u.verified
    assert len(r.branches)>=4
    assert "uncertain" in u.status
    # Later evidence cannot distinguish histories that already transpose.
    b.push_san("e4");r.observe(Observation.from_board(b))
    assert not r.verified
    r.choose(0)
    assert r.board.board_fen()==b.board_fen()


def test_limits_do_not_certify_partial_results():
    b=chess.Board();r=Reconstructor(b,LegalSearcher(node_limit=1,max_plies=4))
    b.push_san("e4");b.push_san("e5")
    assert "limit" in r.observe(Observation.from_board(b)).status
    assert r.verified==[]


def test_game_rewind_repeat_flip_and_pgn():
    b=chess.Board();r=Reconstructor(b)
    frames=[]
    for san in "Nf3 Nf6 Ng1 Ng8 e4 e5 Qh5 Nc6 Bc4 Nf6 Qxf7#".split():
        b.push_san(san);frames.append(b.copy());r.observe(Observation.from_board(b))
    assert len(r.verified)==len(frames)
    # A review of a distant old position does not replace live history.
    r.observe(Observation.from_board(frames[1]))
    assert r.board.fen()==b.fen()
    from chessstream.vision import choose_orientation
    obs=Observation.from_board(b).flipped()
    assert choose_orientation(obs,b).placement()==b.board_fen()
    text=export_pgn(r.initial_fen,r.verified,{"White":"Unknown","Black":"Unknown","Result":"1-0"})
    imported=chess.pgn.read_game(io.StringIO(text))
    assert not imported.errors
    assert imported.end().board().fen()==b.fen()


def test_obscured_square_waits_then_recovers():
    b=chess.Board();r=Reconstructor(b);b.push_san("e4")
    obs=Observation.from_board(b)
    obs.probabilities[:10]=1/13
    assert not r.observe(obs).verified
    assert r.observe(Observation.from_board(b)).verified==["e2e4"]


def test_recovery_preserves_alternatives():
    b=chess.Board();r=Reconstructor(b);b.push_san("e4")
    r.observe(Observation.from_board(b))
    copy=Reconstructor.restore(r.serialize())
    assert copy.board.fen()==b.fen()
    b.push_san("e5");assert copy.observe(Observation.from_board(b)).verified==["e7e5"]


def test_provisional_preview_ranks_per_square_likelihood_then_clock_tie_break():
    board=chess.Board()
    white=Branch(board.fen(),())
    black_root=chess.Board(board.fen().replace(' w ',' b '))
    black=Branch(black_root.fen(),())
    obs=Observation.from_board(board)
    ranked=Reconstructor.rank_branches([black,white],obs,chess.WHITE)
    assert ranked[0][2] is white
    assert ranked[0][0]>-0.01 and ranked[0][1]==1
    tied=Reconstructor.rank_branches([black,white],obs,chess.BLACK)
    assert tied[0][2] is black
