"""A hovered Qe2 must not strand the actual Bg3 continuation in analysis."""
import io
from pathlib import Path
import chess
import chess.pgn
import pytest
from chessstream.domain import Observation,Settings,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store

FIXTURE=Path(__file__).parent/'fixtures/recordings/submitted-queen-hover.pgn'


def recorded(tmp_path):
    game=chess.pgn.read_game(io.StringIO(FIXTURE.read_text()))
    store=Store(tmp_path);m=GameManager(store,Settings());m._create(chess.Board(),utcnow())
    m.correct_line(' '.join(node.san() for node in game.mainline()))
    m.headers.update(White='Sephiroth',Black='Kirby')
    m.observe_context({'names':{'white':'Sephiroth','black':'Kirby'},'names_stable':True},utcnow())
    m.review_pgn=FIXTURE.read_text()
    m.inferred_moves={'41':{'uci':'d1e2','comment':'Inferred: position unchanged'}}
    m.move_clocks={'40':407,'41':390};m.lifecycle.clocks={'white':380,'black':400}
    source=m.review_pgn;m.review_pgn="";m.persist();m.review_pgn=source;anchor=game
    for _ in range(40):anchor=anchor.variations[0]
    return store,m,game,anchor


@pytest.mark.parametrize('blocked',['none','explicit_analysis','missing_clocks','static_clocks','established_move','too_short'])
def test_longer_continuation_requires_live_evidence(tmp_path,blocked):
    store,m,game,anchor=recorded(tmp_path)
    node=anchor.variations[1]
    if blocked!='too_short':
        while node.variations:node=node.variations[0]
    if blocked=='explicit_analysis':m.lifecycle.mode='analysis'
    if blocked=='missing_clocks':m.lifecycle.clocks={}
    if blocked=='static_clocks':m.lifecycle.clocks={'white':390,'black':407}
    if blocked=='established_move':m.inferred_moves={}
    old=m.rec.verified[:]
    assert m._promote_inferred_correction(game,node,Observation.from_board(node.board()))==(blocked=='none')
    if blocked=='none':
        m.persist();saved=chess.pgn.read_game(io.StringIO(store.game(m.current_id)['pgn']))
        assert len(m.rec.verified)==47 and m.headers['Result']=='*'
        assert list(saved.mainline())[40].san()=='Bg3'
        anchor=saved
        for _ in range(40):anchor=anchor.variations[0]
        assert any(child.san()=='Qe2' for child in anchor.variations[1:])
        assert '41' not in m.move_clocks and not saved.errors
    else:assert m.rec.verified==old
    store.close()


def test_streamed_opponent_reply_and_next_white_move_repair_hover(tmp_path):
    store,m,game,anchor=recorded(tmp_path);gid=m.current_id
    m.analysis_cursor={'path':[0]*40,'fen':anchor.board().fen()}
    m.rewind_state={'anchor_ply':41,'cursor':40}
    now=[100.];m._clock=lambda:now[0]
    node=anchor.variations[1]
    for _ in range(3):
        obs=Observation.from_board(node.board())
        m.process(obs);now[0]+=.6;m.process(obs);now[0]+=.6
        node=node.variations[0] if node.variations else node
    assert m.current_id==gid and len(store.games())==1
    assert m.rec.verified[40:43]==['f2g3','d6f5','g3e5']
    assert len(m.rec.verified)>=43
    # The fixture already contains later recorded moves; reviewing earlier
    # frames may retain a cursor without shortening the promoted main line.
    assert len(m.rec.verified)==47
    assert not m.rec.board.is_game_over()
    store.close()
