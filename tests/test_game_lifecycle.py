"""Representative stream sequences: board evidence + independent metadata."""
from concurrent.futures import Future
from datetime import datetime,timedelta,timezone
import io

import chess
import chess.pgn
import pytest

from chessstream.capture import RecordingWorker
from chessstream.domain import Observation,Settings,Region,utcnow
from chessstream.games import GameManager
from chessstream.results import ContextStabilizer,EndMessage,EndMessageDetector,extract_context
from chessstream.storage import Store


PLAYED='e4 e5 Nf3 Nc6 Bc4 Bc5 d3 d6'
NAMES={'white':'Streamer','black':'OpponentA'}


def board_after(line):
    board=chess.Board()
    for san in line.split():board.push_san(san)
    return board


def setup(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());now=[100.]
    manager._clock=lambda:now[0]
    manager._create(chess.Board(),utcnow());manager.correct_line(PLAYED)
    manager.observe_context({'names':NAMES,'names_stable':True,'clocks':{'white':42,'black':78}},'baseline')
    manager.persist()
    return store,manager,now


def frame(manager,now,board,names=None,clocks=None,confidence=1.):
    now[0]+=1
    timestamp=(datetime(2026,10,20,tzinfo=timezone.utc)+timedelta(seconds=now[0])).isoformat()
    manager.observe_context({'names':names or {},'clocks':clocks or {}},timestamp)
    obs=Observation.from_board(board);obs.timestamp=timestamp
    if confidence<1:
        obs.probabilities[:]=1/13
    return manager.process(obs)


@pytest.mark.parametrize('clocks',[None,{'white':600,'black':600}])
def test_different_opponent_separates_even_a_legal_continuation_without_clocks(tmp_path,clocks):
    store,manager,now=setup(tmp_path);old=manager.current_id;prefix=manager.rec.verified[:]
    target=board_after(PLAYED+' O-O');names={**NAMES,'black':'OpponentB'}
    for _ in range(3):
        result=frame(manager,now,target,names,clocks)
        assert manager.current_id==old and manager.rec.verified==prefix
        assert result['lifecycle']['identity']=='pending'
    frame(manager,now,target,names,clocks)
    assert manager.current_id!=old and len(store.games())==2
    assert manager.headers['Black']=='OpponentB' and manager.headers['White']=='Streamer'
    assert manager.rec.initial_fen.split()[0]==target.board_fen() and manager.rec.verified==[]
    assert '[SetUp "1"]' in store.game(manager.current_id)['pgn']
    assert json_game(store,old).end().board().board_fen()==board_after(PLAYED).board_fen()
    assert store.game(old)['ended'] and manager.headers['Result']=='*'
    assert old in manager.separated_from
    store.close()


def json_game(store,gid):return chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))


@pytest.mark.parametrize('names',[NAMES,None])
def test_rematch_clock_reset_after_observed_start_keeps_independent_pgn(tmp_path,names):
    store,manager,now=setup(tmp_path);old=manager.current_id
    frame(manager,now,chess.Board(),names,{'white':180,'black':180})
    frame(manager,now,chess.Board(),names,{'white':180,'black':180})
    assert manager.current_id==old
    opening=board_after('d4')
    frame(manager,now,opening,names,{'white':179,'black':180})
    assert manager.current_id!=old and manager.rec.initial_fen==chess.STARTING_FEN
    assert manager.rec.verified==['d2d4']
    assert manager.move_clocks=={'1':179}
    assert manager.headers['White']==('Streamer' if names else 'Unknown')
    assert manager.lifecycle.summary(manager)['state']=='new game detected'
    store.close()


def test_single_ocr_error_missing_names_and_increments_never_split_or_edit_headers(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id;prefix=manager.rec.verified[:]
    frame(manager,now,manager.rec.board,{**NAMES,'black':'WrongOCR'})
    assert manager.rec.verified==prefix and manager.current_id==old
    frame(manager,now,manager.rec.board,NAMES)
    for clocks in ({'white':44,'black':81},{'white':46,'black':85},None):
        frame(manager,now,manager.rec.board,None,clocks)
    assert manager.current_id==old and manager.headers['Black']=='OpponentA'
    assert manager.lifecycle.reset_reads==0 and len(store.games())==1
    store.close()


def test_seek_clock_jump_and_earlier_moves_are_review_not_a_new_game(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id
    earlier=board_after('e4 e5 Nf3 Nc6')
    for _ in range(3):frame(manager,now,earlier,NAMES,{'white':590,'black':585})
    assert manager.current_id==old and manager.rec.verified==[m.uci() for m in json_game(store,old).mainline_moves()]
    assert manager.lifecycle.summary(manager)['state']=='analysis / replay'
    frame(manager,now,chess.Board(),NAMES,None)
    assert manager.current_id==old and len(store.games())==1
    store.close()


def test_completed_game_opening_review_preserves_result_and_can_be_confirmed_manually(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id
    manager.headers['Result']='1-0';manager.ended=utcnow();manager.persist()
    frame(manager,now,chess.Board(),NAMES,None)
    assert manager.current_id==old
    manager.set_game_mode('analysis');frame(manager,now,board_after('e4 e5 Nf3'),NAMES,None)
    assert manager.current_id==old and manager.headers['Result']=='1-0'
    manager.set_game_mode('new');new=manager.current_id
    assert new!=old and manager.rec.verified==[]
    manager.set_game_mode('undo')
    assert manager.current_id==old and manager.headers['Result']=='1-0' and store.game(new)
    store.close()


def test_no_metadata_unrelated_board_is_quarantined_then_starts_visible_fen(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id;prefix=manager.rec.verified[:]
    target=board_after('d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3 h6 Bh4 b6 cxd5 exd5')
    for _ in range(5):
        frame(manager,now,target)
        assert manager.current_id==old and manager.rec.verified==prefix
    frame(manager,now,target)
    assert manager.current_id!=old and manager.rec.verified==[]
    assert manager.rec.initial_fen.split()[0]==target.board_fen()
    store.close()


def test_midgame_start_defaults_to_fen_with_no_guessed_opening(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    board=board_after('e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6')
    manager.process(Observation.from_board(board))
    assert manager.rec.verified==[] and manager.rec.initial_fen.split()[0]==board.board_fen()
    assert '[SetUp "1"]' in store.game(manager.current_id)['pgn']
    assert manager.opening_ready(Observation.from_board(board))
    store.close()


def test_return_to_other_established_game_requires_its_identity_and_exact_board(tmp_path):
    store,manager,now=setup(tmp_path);first=manager.current_id;target=manager.rec.board.copy()
    manager._create(chess.Board(),utcnow());manager.correct_line('d4 d5 c4 e6 Nc3 Nf6')
    manager.observe_context({'names':{**NAMES,'black':'OpponentB'},'names_stable':True},'second-baseline')
    second=manager.current_id
    frame(manager,now,target,NAMES)
    frame(manager,now,target,NAMES)
    frame(manager,now,target,NAMES)
    assert manager.current_id==first and store.game(second) and len(store.games())==2
    store.close()


def test_replay_fragment_endpoint_does_not_switch_active_game_back_and_forth(tmp_path):
    store,manager,now=setup(tmp_path);long_id=manager.current_id
    long_board=manager.rec.board.copy()

    # Reproduce a short recording made while the same game is being replayed.
    manager._create(chess.Board(),utcnow())
    manager.correct_line('e4 e5 Nf3 Nc6')
    manager.headers.update({'White':'Streamer','Black':'OpponentA'})
    manager.persist();short_id=manager.current_id
    manager.recover(long_id)
    manager.observe_context({'names':NAMES,'names_stable':True},'replay-names')
    assert short_id!=long_id

    replay_endpoint=board_after('e4 e5 Nf3 Nc6')
    for board in (replay_endpoint,long_board,replay_endpoint,long_board,replay_endpoint):
        frame(manager,now,board,NAMES)
        assert manager.current_id==long_id
    assert store.game(short_id) and store.game(long_id)
    store.close()


def test_late_recovery_cannot_commit_while_an_identity_change_is_pending(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id;prefix=manager.rec.verified[:]
    board=manager.rec.board.copy();board.push_san('O-O')
    future=Future();future.set_result((manager.rec.serialize(),manager.rec.serialize()))
    manager._recovery_future=future
    manager._recovery_token=(old,manager.rec.initial_fen,tuple(prefix),board.board_fen(),manager.lifecycle.generation)
    frame(manager,now,board,{**NAMES,'black':'OpponentB'})
    assert manager._recovery_future is None and manager.rec.verified==prefix
    assert not manager.background_recovery(Observation.from_board(board))
    assert manager.rec.verified==prefix and manager.current_id==old
    store.close()


def test_split_preserves_clocks_variations_and_can_restore_original_after_restart(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id;original=manager.rec.verified[:]
    manager.move_clocks={'2':178,'6':164};manager.annotate(old,[0]*4,'Bb5 a6',comment='Retain branch')
    manager.persist();manager.split_game_at(4);second=manager.current_id
    assert len(list(json_game(store,old).mainline()))==4
    assert manager.move_clocks=={'2':164} and 'Retain branch' in store.game(second)['pgn']
    restored=GameManager(store,Settings());restored.recover(second);restored.set_game_mode('undo')
    assert restored.current_id==old and restored.rec.verified==original
    assert restored.move_clocks=={'2':178,'6':164} and store.game(second)
    store.close()


@pytest.mark.parametrize('orientation',['white','black'])
def test_layout_relative_metadata_without_clocks_survives_fullscreen_zoom_and_flips(orientation):
    for bx,by,size in ((20,60,400),(250,95,800),(0,40,600),(20,60,400)):
        lines=[('UpperPlayer (1500)',.99,(bx+20,by-size*.08,bx+210,by-size*.03)),
               ('LowerPlayer (1600)',.99,(bx+20,by+size*1.03,bx+210,by+size*1.08))]
        context=extract_context(lines,(bx,by,size,size),orientation)
        assert context['names'][orientation]=='LowerPlayer'
        assert context['names']['black' if orientation=='white' else 'white']=='UpperPlayer'
        assert context['clocks']=={}
    stabilizer=ContextStabilizer()
    for _ in range(2):assert not stabilizer.observe(context)['names']
    assert stabilizer.observe(context)['names']==context['names']
    stabilizer.observe({'names':{},'clocks':{}})
    assert not stabilizer.observe(context)['names']


def test_layout_change_invalidates_cached_ocr_without_changing_game(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id;board=manager.rec.board.copy()
    worker=RecordingWorker(manager,Region(0,0,800,800))
    detector=EndMessageDetector();detector.last_scan=10.;detector._pixels='old layout';detector.last_lines=['stale']
    worker._text_detector=detector;worker._context_stabilizer=ContextStabilizer()
    for _ in range(4):
        worker.layout_changed()
        assert detector.last_scan<0 and detector._pixels is None and detector.last_lines==[]
        frame(manager,now,board,NAMES)
        assert manager.current_id==old
    # Overlay and a visibility interruption do not cause a split.
    frame(manager,now,board,confidence=0.)
    frame(manager,now,board,NAMES)
    assert manager.current_id==old and len(store.games())==1
    store.close()


def test_result_then_different_opponent_on_reset_preserves_result_and_observed_opening(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id
    manager.declare_end(EndMessage('1-0','resignation','You Won by resignation',.99))
    names={**NAMES,'black':'OpponentB'}
    frame(manager,now,chess.Board(),names)
    frame(manager,now,chess.Board(),names)
    opening=board_after('d4');frame(manager,now,opening,names)
    frame(manager,now,opening,names)
    assert manager.current_id!=old and manager.rec.initial_fen==chess.STARTING_FEN
    assert manager.rec.verified==['d2d4'] and json_game(store,old).headers['Result']=='1-0'
    assert manager.headers['Result']=='*' and manager.headers['Black']=='OpponentB'
    assert manager.headers.get('Termination') is None
    store.close()


def test_game_after_completion_without_either_metadata_source_is_separate(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());now=[100.];manager._clock=lambda:now[0]
    manager._create(chess.Board(),utcnow());manager.correct_line('f3 e5 g4 Qh4#')
    manager.process(Observation.from_board(manager.rec.board));old=manager.current_id
    frame(manager,now,chess.Board())
    board=board_after('d4');frame(manager,now,board);frame(manager,now,board)
    assert manager.current_id!=old and manager.rec.verified==['d2d4']
    assert json_game(store,old).headers['Result']=='0-1' and manager.headers['Result']=='*'
    assert manager.headers['White']=='Unknown' and manager.move_clocks=={}
    store.close()


def test_clock_discontinuity_to_another_time_control_is_confirmed_with_live_ticks(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id
    frame(manager,now,chess.Board(),NAMES,{'white':300,'black':300})
    frame(manager,now,chess.Board(),NAMES,{'white':300,'black':300})
    frame(manager,now,board_after('c4'),NAMES,{'white':299,'black':300})
    assert manager.current_id!=old and manager.rec.verified==['c2c4']
    assert 'TimeControl' not in manager.headers  # Clock readings do not reveal increments.
    assert 'clocks reset' in manager.lifecycle.reason
    store.close()


def test_worker_never_invokes_recovery_before_quarantining_changed_player(tmp_path,monkeypatch):
    store,manager,now=setup(tmp_path);old=manager.current_id;prefix=manager.rec.verified[:]
    worker=RecordingWorker(manager,Region(0,0,800,800));calls=[]
    monkeypatch.setattr(manager,'background_recovery',lambda *args:calls.append(args))
    manager.observe_context({'names':{**NAMES,'black':'OpponentB'}},'new-ocr-frame')
    target=manager.rec.board.copy();target.push_san('O-O')
    result=worker.process_observation(Observation.from_board(target),2)
    assert not calls and result['lifecycle']['state']=='uncertain transition'
    assert manager.current_id==old and manager.rec.verified==prefix
    store.close()


def test_explicit_continue_cancels_a_pending_split_without_changing_saved_moves(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id
    target=manager.rec.board.copy();target.push_san('O-O')
    frame(manager,now,target,{**NAMES,'black':'WrongOCR'})
    manager.set_game_mode('continue');frame(manager,now,target,{**NAMES,'black':'WrongOCR'})
    assert manager.current_id==old and len(store.games())==1
    assert manager.snapshot()['pending_moves']==['O-O']
    manager.set_game_mode('auto')
    store.close()


def test_consistent_new_opponent_splits_even_when_the_board_is_identical(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id;board=manager.rec.board.copy()
    for _ in range(6):frame(manager,now,board,{**NAMES,'black':'OpponentB'})
    assert manager.current_id!=old and not manager.rec.verified
    assert manager.headers['Black']=='OpponentB' and json_game(store,old).headers['Black']=='OpponentA'
    store.close()


def test_restart_reuses_only_an_unambiguous_exact_game_with_matching_players(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id;board=manager.rec.board.copy()
    restarted=GameManager(store,Settings())
    restarted.observe_context({'names':NAMES,'names_stable':True},'restart names')
    restarted.process(Observation.from_board(board))
    assert restarted.current_id==old
    other=GameManager(store,Settings())
    other.observe_context({'names':{**NAMES,'black':'OpponentB'},'names_stable':True},'other game names')
    other.process(Observation.from_board(board))
    assert other.current_id!=old and not other.rec.verified and other.headers['Black']=='OpponentB'
    assert len(store.games())==2
    store.close()


def test_large_increment_on_both_clocks_with_two_skipped_plies_does_not_split(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id
    board=manager.rec.board.copy();board.push_san('O-O');board.push_san('Nf6')
    frame(manager,now,board,NAMES,{'white':71,'black':107})
    frame(manager,now,board,NAMES,{'white':70,'black':107})
    assert manager.current_id==old and len(store.games())==1
    assert manager.lifecycle.reset_reads==0
    assert manager.snapshot()['fen'].split()[0]==board.board_fen() or manager.snapshot()['preview_fen'].split()[0]==board.board_fen()
    store.close()


def test_pending_identity_survives_restart_and_cannot_append_before_fresh_metadata(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id;prefix=manager.rec.verified[:]
    board=manager.rec.board.copy();board.push_san('O-O')
    frame(manager,now,board,{**NAMES,'black':'OpponentB'})
    restarted=GameManager(store,Settings());restarted.recover(old)
    restarted.process(Observation.from_board(board))
    assert restarted.current_id==old and restarted.rec.verified==prefix
    assert restarted.lifecycle.pending_restart
    restarted.set_game_mode('continue');restarted.process(Observation.from_board(board))
    assert not restarted.lifecycle.pending_restart and restarted.snapshot()['pending_moves']==['O-O']
    store.close()


def test_result_popup_cannot_be_attributed_to_old_pgn_before_board_processing(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id
    target=manager.rec.board.copy();target.push_san('O-O')
    names={**NAMES,'black':'OpponentB'}
    manager.observe_context({'names':names},'first new opponent OCR')
    result=EndMessage('1-0','resignation','You Won by resignation',.99)
    assert not manager.declare_end(result,Observation.from_board(target))
    assert manager.headers['Result']=='*' and not manager.terminal_message
    for _ in range(4):frame(manager,now,target,names)
    assert manager.current_id!=old
    assert manager.declare_end(result,Observation.from_board(target))
    assert manager.headers['Result']=='1-0' and json_game(store,old).headers['Result']=='*'
    store.close()


def test_explicit_analysis_mode_preserves_the_played_result(tmp_path):
    store,manager,now=setup(tmp_path);old=manager.current_id
    manager.set_game_mode('analysis')
    assert not manager.declare_end(EndMessage('1-0','checkmate','Checkmate',.99),Observation.from_board(manager.rec.board))
    assert manager.current_id==old and manager.headers['Result']=='*' and manager.terminal_message is None
    store.close()
