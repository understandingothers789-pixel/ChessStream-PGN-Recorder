"""Combined worker/manager/storage faults; optional sources cannot invent history."""
import io
import time
import json
import chess
import chess.pgn
import numpy as np
import pytest
from chessstream.capture import RecordingWorker
from chessstream.domain import Observation,Settings,Region,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store


def setup(tmp_path):
    store=Store(tmp_path);m=GameManager(store,Settings(audio_cues=True,confirm_on_reply=False))
    m._create(chess.Board(),utcnow());clock=[100.];m._clock=lambda:clock[0]
    w=RecordingWorker(m,Region(0,0,500,500))
    return store,m,w,clock


def frame(w,clock,board):
    clock[0]+=.6
    return w.process_observation(Observation.from_board(board),2)


def converge(w,clock,board):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        if w.manager.rec.board.fen()==board.fen():return
        time.sleep(.01)
        frame(w,clock,board)
    assert w.manager.rec.board.fen()==board.fen(),w.manager.last_message


def assert_saved(store,m,board):
    row=store.game(m.current_id);game=chess.pgn.read_game(io.StringIO(row['pgn']))
    assert not game.errors
    assert game.end().board().fen()==board.fen()==m.rec.board.fen()
    assert [x.uci() for x in game.mainline_moves()]==m.rec.verified
    assert json.loads(row['state'])['verified']==m.rec.verified


def test_failed_audio_and_transient_ocr_do_not_interrupt_visual_recording(tmp_path):
    store,m,w,clock=setup(tmp_path)
    class BrokenAudio:
        def poll(self,**kwargs):raise OSError('simulated device disconnect')
        def stop(self):raise OSError('simulated cleanup failure')
    w.audio=BrokenAudio();board=chess.Board();gid=m.current_id
    m.observe_context({'names':{'white':'Streamer','black':'Opponent'},'names_stable':True},'baseline')
    for index,san in enumerate(('e4','e5','Nf3','Nc6')):
        if index==1:
            m.observe_context({'names':{'white':'Strearner','black':'Opponent'},'clocks':{'white':599,'black':600}},'bad OCR')
        if index>1:
            m.observe_context({'names':{'white':'Streamer','black':'Opponent'},'names_stable':True,'clocks':{'white':590-index,'black':589-index}},str(index))
        board.push_san(san);snap=frame(w,clock,board)
    assert w.audio is None and 'visual recording continues' in snap['audio_cues']['status']
    converge(w,clock,board)
    assert m.current_id==gid and len(store.games())==1
    assert_saved(store,m,board)
    m.cancel_background_recovery();m.cancel_saved_join();store.close()


@pytest.mark.parametrize('bad',['nan','infinity','shape','negative','unnormalized','quality'])
def test_bad_vision_and_false_audio_preserve_prefix_then_recover(tmp_path,bad):
    store,m,w,clock=setup(tmp_path);board=chess.Board();board.push_san('e4');frame(w,clock,board)
    before=store.game(m.current_id)['pgn'];obs=Observation.from_board(board)
    if bad=='nan':obs.probabilities[0,0]=np.nan
    if bad=='infinity':obs.probabilities[0,0]=np.inf
    if bad=='shape':obs.probabilities=obs.probabilities[:63]
    if bad=='negative':obs.probabilities[0,0]=-.1
    if bad=='unnormalized':obs.probabilities[:]=0
    if bad=='quality':obs.quality=float('nan')
    m._audio_evidence=(m.current_id,board.board_fen(),clock[0])
    snap=w.process_observation(obs,2)
    assert 'Recognition error' in snap['status'] and m._audio_evidence is None
    assert store.game(m.current_id)['pgn']==before
    board.push_san('e5');frame(w,clock,board)
    assert_saved(store,m,board)
    m.cancel_background_recovery();store.close()


@pytest.mark.parametrize('failure',['board','illegal_move'])
def test_broken_reconstructor_is_rolled_back_before_overwriting_pgn(tmp_path,failure):
    store,m,w,clock=setup(tmp_path);board=chess.Board();board.push_san('e4');frame(w,clock,board)
    before=store.game(m.current_id)['pgn']
    if failure=='board':m.rec.board.remove_piece_at(chess.A8)
    else:m.rec.verified.append('e7e4')
    m.persist()
    assert store.game(m.current_id)['pgn']==before
    assert 'consistency check' in m.last_message
    assert store.query("SELECT * FROM audit WHERE action='recording integrity recovery'")
    assert_saved(store,m,board)
    board.push_san('e5');frame(w,clock,board);assert_saved(store,m,board)
    m.cancel_background_recovery();store.close()


def test_audio_cannot_authorize_disappearing_piece_and_later_frames_recover(tmp_path):
    store,m,w,clock=setup(tmp_path);board=chess.Board()
    for san in ('e4','e5','Nf3','Nc6'):board.push_san(san);frame(w,clock,board)
    prefix=m.rec.verified[:];gid=m.current_id
    wrong=board.copy();wrong.remove_piece_at(chess.D1)
    class FalseAudio:
        def poll(self,**kwargs):return ([{'at':clock[0],'kind':'move','score':1.}],{'status':'false cue','count':1})
    w.audio=FalseAudio()
    frame(w,clock,wrong)
    assert m.rec.verified==prefix and m.current_id==gid
    w.audio=None;board.push_san('Bb5');frame(w,clock,board)
    converge(w,clock,board)
    assert_saved(store,m,board)
    m.cancel_background_recovery();m.cancel_saved_join();store.close()


def test_invalid_frame_and_corrupt_move_list_recover_together(tmp_path):
    store,m,w,clock=setup(tmp_path)
    before=store.game(m.current_id)['pgn']
    m.rec.verified.append('a2a5')
    obs=Observation.from_board(chess.Board());obs.probabilities[:]=np.nan
    snapshot=w.process_observation(obs,2)
    assert snapshot['pipeline_health']['pgn']=='checkpoint restored'
    assert not m.rec.verified and store.game(m.current_id)['pgn']==before
    store.close()


def test_integrity_check_does_not_read_another_threads_partial_edit(tmp_path):
    import threading
    store,m,w,clock=setup(tmp_path);started=threading.Event();done=threading.Event();outcome=[]
    def check():
        started.set()
        outcome.append(m.check_recording_integrity());done.set()
    with m.lock:
        original=m.rec.board.copy()
        m.rec.board.remove_piece_at(chess.A1)
        thread=threading.Thread(target=check);thread.start()
        assert started.wait(1)
        held=not done.wait(.05)
        m.rec.board=original
    thread.join(2)
    assert held and outcome==[True]
    assert not store.query("SELECT * FROM audit WHERE action='recording integrity recovery'")
    store.close()


def test_manager_entry_point_rejects_invalid_recognition_output(tmp_path):
    store,m,w,clock=setup(tmp_path);before=store.game(m.current_id)['pgn']
    obs=Observation.from_board(chess.Board());obs.probabilities[:]=np.nan
    snapshot=m.process(obs)
    assert 'Recognition error' in snapshot['status']
    assert not m.rec.verified and store.game(m.current_id)['pgn']==before
    store.close()


def test_failed_pgn_file_write_keeps_database_and_can_be_retried(tmp_path,monkeypatch):
    import chessstream.storage as storage
    store,m,w,clock=setup(tmp_path);real_write=storage.atomic_text
    m.rec.board.push_san('e4');m.rec.verified.append('e2e4')
    def fail(*args,**kwargs):raise OSError('simulated full export disk')
    with monkeypatch.context() as patch:
        patch.setattr(storage,'atomic_text',fail)
        with pytest.raises(OSError):m.persist()
    assert_saved(store,m,m.rec.board)
    m.persist()
    row=store.game(m.current_id)
    assert (store.root/'pgn'/(m.current_id+'.pgn')).read_text().strip()==row['pgn'].strip()
    store.close()


@pytest.mark.parametrize('change',['updated','deleted','became_active'])
def test_library_join_rechecks_sources_inside_manager_lock(tmp_path,change):
    store,m,w,clock=setup(tmp_path);first=store.game(m.current_id)
    m._create(chess.Board(),utcnow());second=store.game(m.current_id)
    m._create(chess.Board(),utcnow());active=m.current_id
    if change=='updated':
        with store.transaction() as db:db.execute('UPDATE games SET pgn=? WHERE id=?',(first['pgn']+'\n',first['id']))
    elif change=='deleted':
        with store.transaction() as db:db.execute('DELETE FROM games WHERE id=?',(first['id'],))
    else:m.recover(first['id'],persist=False)
    before=len(store.games())
    with pytest.raises(ValueError):m.combine_games([first,second],first['pgn'],activate=False)
    assert len(store.games())==before
    assert not store.query("SELECT * FROM audit WHERE action='PGNs combined'")
    store.close()
