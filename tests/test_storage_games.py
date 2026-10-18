from datetime import datetime,timezone,timedelta
import io
import json
import chess
import chess.pgn
import numpy as np
from chessstream.domain import Settings,Observation,utcnow
from chessstream.storage import Store
from chessstream.games import GameManager


def test_retention_restart_and_pgn_independence(tmp_path):
    s=Store(tmp_path);m=GameManager(s,Settings());b=chess.Board()
    m.process(Observation.from_board(b));b.push_san('e4');m.process(Observation.from_board(b))
    gid=m.current_id;sid=m.session_id;old='2025-01-01T00:00:00.000+00:00'
    image=np.zeros((80,80,3),np.uint8)
    s.save_screenshot(sid,gid,image,old)
    s.save_screenshot(sid,gid,image,utcnow())
    assert s.run_retention()==[]
    job=s.schedule_deletion('2025-02-01T00:00:00+00:00',{'before':'2026-01-01T00:00:00.000+00:00'})
    s.close();s=Store(tmp_path)
    assert s.run_retention()[0]['count']==1
    assert len(s.screenshots())==1
    assert 'e4' in s.game(gid)['pgn']
    assert s.run_retention()==[]
    s.delete_screenshots({})
    assert len(s.screenshots())==0
    assert s.game(gid)
    assert (tmp_path/'pgn'/f'{gid}.pgn').exists()
    s.close()


def test_filters_dedupe_and_delete_data_only(tmp_path):
    s=Store(tmp_path);m=GameManager(s,Settings());m.process(Observation.from_board(chess.Board()))
    gid=m.current_id;image=np.zeros((80,80,3),np.uint8)
    assert s.save_screenshot(m.session_id,gid,image,utcnow(),deduplicate=True)
    assert not s.save_screenshot(m.session_id,gid,image,utcnow(),deduplicate=True)
    assert s.deletion_estimate({'game_id':gid})['count']==1
    s.delete_game(gid)
    assert len(s.screenshots())==1
    assert s.screenshots()[0]['game_id'] is None
    s.close()


def test_midgame_setup_and_side_inference(tmp_path):
    s=Store(tmp_path);m=GameManager(s,Settings());b=chess.Board()
    for san in 'e4 e5 Nf3 Nc6'.split():b.push_san(san)
    m.process(Observation.from_board(b));b.push_san('Bb5');m.process(Observation.from_board(b))
    row=s.game(m.current_id);game=chess.pgn.read_game(io.StringIO(row['pgn']))
    assert game.headers['SetUp']=='1'
    assert game.headers['FEN'].split()[1]=='w'
    assert list(game.mainline_moves())==[chess.Move.from_uci('f1b5')]
    s.close()


def test_terminal_and_back_to_back(tmp_path):
    s=Store(tmp_path);m=GameManager(s,Settings());b=chess.Board()
    m.process(Observation.from_board(b))
    for san in 'f3 e5 g4 Qh4#'.split():
        b.push_san(san);m.process(Observation.from_board(b))
    old=m.current_id
    assert m.headers['Result']=='0-1'
    m.process(Observation.from_board(chess.Board()))
    assert m.current_id!=old
    assert len(s.games())==2
    assert s.game(old)['plies']==4
    s.close()


def test_nonterminal_reset_and_opening_review(tmp_path):
    s=Store(tmp_path);m=GameManager(s,Settings());b=chess.Board()
    m.process(Observation.from_board(b))
    for san in 'e4 e5 Nf3 Nc6'.split():
        b.push_san(san);m.process(Observation.from_board(b))
    old=m.current_id
    reset=chess.Board();m.process(Observation.from_board(reset))
    reset.push_san('e4');m.process(Observation.from_board(reset))
    assert m.current_id==old # Can still be a rewind.
    reset.push_san('c5');m.process(Observation.from_board(reset))
    assert m.current_id!=old
    assert m.rec.verified==['e2e4','c7c5']
    assert s.game(old)['plies']==4
    s.close()


def test_manual_correction_is_atomic_and_recoverable(tmp_path):
    import pytest
    s=Store(tmp_path);m=GameManager(s,Settings());b=chess.Board();m.process(Observation.from_board(b))
    for san in 'e4 e5 Nf3'.split():b.push_san(san);m.process(Observation.from_board(b))
    before=m.rec.board.fen()
    with pytest.raises(ValueError):m.correct_line('Qh9',1)
    assert m.rec.board.fen()==before
    m.correct_line('Bc4',1)
    assert m.rec.verified==['e2e4','e7e5','f1c4']
    recovered=GameManager(s,Settings());recovered.recover(m.current_id)
    assert recovered.rec.verified==m.rec.verified
    assert s.query("SELECT * FROM audit WHERE action='manual legal SAN correction'")
    s.close()


def test_manual_result_overrides_automatic_result_and_freezes_finished_game(tmp_path):
    s=Store(tmp_path);m=GameManager(s,Settings());b=chess.Board();m.process(Observation.from_board(b))
    for san in 'f3 e5 g4 Qh4#'.split():b.push_san(san);m.process(Observation.from_board(b))
    headers=dict(m.headers);headers['Result']='1/2-1/2';m.edit(m.current_id,m.name,headers)
    m.process(Observation.from_board(b));assert m.headers['Result']=='1/2-1/2'
    restored=GameManager(s,Settings());restored.recover(m.current_id)
    assert restored.result_override
    s.close()


def test_time_range_boundaries_cancellation_and_path_guard(tmp_path):
    import pytest
    s=Store(tmp_path/'data');sid=s.session();image=np.zeros((80,80,3),np.uint8)
    for hour in [10,12,14]:s.save_screenshot(sid,None,image,f'2026-10-18T{hour}:00:00.000+00:00')
    assert s.delete_screenshots({'after':'2026-10-18T12:00:00.000+00:00','before':'2026-10-18T14:00:00.000+00:00'})['count']==1
    job=s.schedule_deletion('2020-01-01T00:00:00+00:00',{});s.cancel_deletion(job)
    assert s.run_retention()==[] and len(s.screenshots())==2
    with pytest.raises(ValueError):s.delete_screenshots({'game-id':'typo'})
    outside=tmp_path/'outside.png';outside.write_bytes(b'keep this file')
    with s.transaction() as db:db.execute("UPDATE screenshots SET path='../outside.png' WHERE deleted=0")
    with pytest.raises(ValueError):s.delete_screenshots({})
    assert outside.read_bytes()==b'keep this file'
    s.close()


def test_opt_in_age_retention_has_strict_cutoff(tmp_path):
    s=Store(tmp_path);sid=s.session();image=np.zeros((80,80,3),np.uint8)
    for date in ['2026-10-16T23:59:59.000+00:00','2026-10-17T00:00:00.000+00:00','2026-10-18T00:00:00.000+00:00']:
        s.save_screenshot(sid,None,image,date)
    result=s.run_retention(days=1,now=datetime(2026,10,18,tzinfo=timezone.utc))
    assert result[0]['count']==1
    assert len(s.screenshots())==2
    s.close()


def test_one_click_initial_orientation_correction_repairs_provisional_fen(tmp_path):
    s=Store(tmp_path);m=GameManager(s,Settings())
    m.process(Observation.from_board(chess.Board()).flipped());gid=m.current_id
    assert m.rec.board.board_fen()!=chess.Board().board_fen()
    m.process(Observation.from_board(chess.Board()))
    assert m.current_id==gid and len(s.games())==1
    assert m.rec.initial_fen==chess.STARTING_FEN
    assert not m.rec.verified
    s.close()


def test_finishing_game_preserves_uncertainty_in_library_status(tmp_path):
    s=Store(tmp_path);m=GameManager(s,Settings());b=chess.Board();b.push_san('e4');b.push_san('e5')
    m.process(Observation.from_board(b));assert len(m.rec.branches)==2
    m.headers['Result']='1-0';m.finish()
    game=s.game(m.current_id)
    assert 'unresolved' in game['status']
    assert 'Unresolved observations' in game['pgn']
    s.close()
