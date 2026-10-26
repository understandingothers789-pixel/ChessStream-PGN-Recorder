"""Reported mate saved as analysis, followed by a duplicate opening replay."""
import io
from pathlib import Path
import chess
import chess.pgn
import pytest
from chessstream.domain import Observation,Settings,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store

FIXTURE=Path(__file__).parent/'fixtures/recordings/submitted-mate-variation.pgn'


def recorded(tmp_path):
    game=chess.pgn.read_game(io.StringIO(FIXTURE.read_text()))
    store=Store(tmp_path);m=GameManager(store,Settings());m._create(chess.Board(),utcnow())
    m.correct_line(' '.join(node.san() for node in game.mainline()))
    m.headers.update(White='Goomba',Black='Bowser')
    m.observe_context({'names':{'white':'Goomba','black':'Bowser'},'names_stable':True},utcnow())
    m.review_pgn=FIXTURE.read_text()
    m.inferred_moves={'25':{'uci':'g5f3','comment':'Inferred across capture gap'}}
    m.persist()
    anchor=game
    for _ in range(24):anchor=anchor.variations[0]
    mate=anchor.variations[1]
    while mate.variations:mate=mate.variations[0]
    return store,m,game,mate


@pytest.mark.parametrize('blocked',['none','explicit_analysis','established_suffix','completed','different_players'])
def test_mate_only_replaces_short_inferred_suffix(tmp_path,blocked):
    store,m,game,mate=recorded(tmp_path);old=m.rec.verified[:]
    if blocked=='explicit_analysis':m.lifecycle.mode='analysis'
    if blocked=='established_suffix':m.inferred_moves={}
    if blocked=='completed':m.headers['Result']='1-0'
    if blocked=='different_players':m.lifecycle.raw_names['black']='Other'
    obs=Observation.from_board(mate.board())
    result=m._promote_inferred_correction(game,mate,obs)
    assert result==(blocked=='none')
    if result:
        m.persist();saved=chess.pgn.read_game(io.StringIO(store.game(m.current_id)['pgn']))
        assert saved.end().board().is_checkmate() and len(m.rec.verified)==66
        assert m.headers['Result']=='0-1' and not saved.errors
        anchor=saved
        for _ in range(24):anchor=anchor.variations[0]
        assert anchor.board().san(anchor.variations[0].move)=='Nxe6'
        assert any(anchor.board().san(child.move)=='Nf3' for child in anchor.variations[1:])
        restored=GameManager(store,Settings());restored.recover(m.current_id)
        assert restored.rec.verified==m.rec.verified
    else:assert m.rec.verified==old
    store.close()


def test_same_players_recorded_opening_beats_clock_reset_but_other_opening_does_not(tmp_path):
    store,m,game,mate=recorded(tmp_path);gid=m.current_id
    m.lifecycle.reset_reads=3;m.lifecycle.reset_confirmed=True
    m.lifecycle.reset_board_seen=True;m.lifecycle.clock_running=True
    m.lifecycle.clocks={'white':590,'black':594};m.clock_reset_seen=10.
    board=chess.Board()
    for san in ('e4','c5','Nf3'):board.push_san(san)
    obs=Observation.from_board(board)
    decision=m.lifecycle.evaluate(m,obs)
    assert decision.action=='continue' and m.current_id==gid
    assert m.lifecycle.phase=='analysis / replay' and not m.lifecycle.reset_reads
    assert not m._analysis_boundary()
    # An unrelated opening from the same players is still a rematch candidate.
    m.lifecycle.reset_reads=3;m.lifecycle.reset_confirmed=True;m.lifecycle.reset_board_seen=True
    board=chess.Board();board.push_san('d4')
    decision=m.lifecycle.evaluate(m,Observation.from_board(board))
    assert m.lifecycle.phase!='analysis / replay'
    store.close()


def test_reported_mate_is_promoted_through_normal_analysis_processing(tmp_path):
    store,m,game,mate=recorded(tmp_path);gid=m.current_id
    path=[];node=mate.parent
    while node.parent is not None:
        path.append(node.parent.variations.index(node));node=node.parent
    path.reverse()
    m.analysis_cursor={'path':path,'fen':mate.parent.board().fen()}
    m.rewind_state={'anchor_ply':25,'cursor':24}
    clock=[100.];m._clock=lambda:clock[0]
    obs=Observation.from_board(mate.board())
    m.process(obs);clock[0]+=.6;m.process(obs)
    assert m.current_id==gid and m.rec.board.is_checkmate()
    assert len(m.rec.verified)==66 and len(store.games())==1
    assert m.headers['Result']=='0-1'
    store.close()
