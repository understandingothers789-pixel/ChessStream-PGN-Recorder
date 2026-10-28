"""The user's longest-recorded-line policy, including stable ties and nesting."""
import io
import chess
import chess.pgn
from chessstream.domain import Settings,Observation,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store


def setup(tmp_path):
    store=Store(tmp_path);m=GameManager(store,Settings());m._create(chess.Board(),utcnow())
    m.correct_line('e4 e6 d4 d5 Nd2 Nf6')
    m.annotate(m.current_id,[0]*4,'Nc3 Bb4',comment='Recorded alternative')
    return store,m


def game(store,m):return chess.pgn.read_game(io.StringIO(store.game(m.current_id)['pgn']))


def test_equal_length_retains_mainline_then_new_move_promotes_and_survives_restart(tmp_path):
    store,m=setup(tmp_path);gid=m.current_id;m.persist()
    assert m.rec.verified[-2:]==['b1d2','g8f6']
    m.lifecycle.mode='analysis';m.analysis_cursor={'path':[0]*4+[1,0]}
    board=chess.Board()
    for san in 'e4 e6 d4 d5 Nc3 Bb4 e5'.split():board.push_san(san)
    now=[10.];m._clock=lambda:now[0]
    obs=Observation.from_board(board)
    m.process(obs);now[0]+=.6;m.process(obs)
    assert m.current_id==gid and m.rec.board.board_fen()==board.board_fen()
    assert m.rec.verified[-3:]==['b1c3','f8b4','e4e5']
    saved=game(store,m);anchor=saved
    for _ in range(4):anchor=anchor.variations[0]
    assert [node.san() for node in anchor.variations]==['Nc3','Nd2']
    assert not saved.errors and len(store.games())==1
    restored=GameManager(store,Settings());restored.recover(gid)
    assert restored.rec.verified==m.rec.verified
    store.close()


def test_nested_longer_branch_promotes_without_names_clocks_or_inferred_requirement(tmp_path):
    store,m=setup(tmp_path)
    m.annotate(m.current_id,[0]*4+[1,0],'e5 Ne7 Qg4',comment='Longer nested continuation')
    m.inferred_moves={};m.lifecycle.clocks={};m.lifecycle.mode='analysis'
    m.persist()
    assert len(m.rec.verified)==9 and m.rec.verified[-1]=='d1g4'
    before=m.rec.verified[:];m.persist();m.persist()
    assert m.rec.verified==before and not game(store,m).errors
    store.close()


def test_new_extension_at_analysis_mainline_endpoint_is_saved(tmp_path):
    store,m=setup(tmp_path)
    m.lifecycle.mode='analysis'
    board=m.rec.board.copy();board.push_san('Ngf3')
    # A cursor at the current mainline endpoint must not discard its extension.
    m.analysis_cursor={'path':[0]*6};m.rewind_state={'anchor_ply':6,'cursor':6}
    now=[10.];m._clock=lambda:now[0];obs=Observation.from_board(board)
    m.process(obs);now[0]+=.6;m.process(obs)
    assert len(m.rec.verified)==7 and m.rec.verified[-1]=='g1f3'
    assert len(list(game(store,m).mainline_moves()))==7
    store.close()
