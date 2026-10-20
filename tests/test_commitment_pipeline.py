"""Full recording/analysis/background workflows for the October 20 handoff."""
from concurrent.futures import Future
from threading import Event
import io
import json
import os
import zipfile
import chess
import chess.pgn
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from chessstream.commitment import assess_search
from chessstream.domain import Observation,Settings,Region,utcnow
from chessstream.games import GameManager
from chessstream.reconstruction import Reconstructor,LegalSearcher,SearchResult,Branch
from chessstream.results import extract_context
from chessstream.storage import Store
from chessstream.capture import RecordingWorker
from chessstream.diagnostics import export_diagnostics


def played(line):
    board=chess.Board()
    for san in line.split():board.push_san(san)
    return board


def test_ambiguous_analysis_jump_stays_unsaved_but_observed_single_moves_can_branch(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());now=[0.]
    manager._clock=lambda:now[0];manager._create(chess.Board(),utcnow())
    manager.correct_line('e4 e5 Bc4 Bc5 d3 d6');prefix=manager.rec.verified[:]
    manager.set_game_mode('analysis')
    manager.process(Observation.from_board(chess.Board()))
    target=Observation.from_board(played('Nf3 Nf6 Nc3 Nc6'))
    for now[0] in (1.,2.,8.):manager.process(target)
    assert manager.rec.verified==prefix and not manager.review_pgn
    assert not store.query("SELECT * FROM audit WHERE action='analysis continuation recorded'")
    target=Observation.from_board(played('Nf3'))
    for now[0] in (9.,10.):manager.process(target)
    game=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert manager.rec.verified==prefix
    assert len(game.variations)==2 and game.variations[1].san()=='Nf3'
    store.close()


def test_background_recovery_cannot_apply_after_a_b_a_observations(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    manager._create(chess.Board(),utcnow())
    a=Observation.from_board(played('e4 e5'))
    manager.note_evidence(a)
    pending=Reconstructor(played('e4 e5')).serialize()
    pending['initial_fen']=chess.STARTING_FEN;pending['verified']=['e2e4','e7e5']
    task=Future();task.set_result((manager.rec.serialize(),pending))
    manager._recovery_future=task;manager._recovery_token=manager.recovery_token(a)
    manager.note_evidence(Observation.from_board(played('d4')))
    manager.note_evidence(a)
    manager.background_recovery(a)
    assert not manager.rec.verified and manager._recovery_future is None
    store.close()


@pytest.mark.parametrize('change',['result','stop'])
def test_background_recovery_cannot_append_after_result_edit_or_stop(tmp_path,change):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    manager._create(chess.Board(),utcnow())
    target=Observation.from_board(played('e4 e5'));manager.note_evidence(target)
    recovered=Reconstructor(chess.Board());recovered.board=played('e4 e5')
    recovered.verified=['e2e4','e7e5'];recovered.history+=[played('e4').board_fen(),recovered.board.board_fen()]
    recovered.branches=[Branch(recovered.board.fen(),())]
    task=Future();task.set_result((manager.rec.serialize(),recovered.serialize()))
    manager._recovery_future=task;manager._recovery_token=manager.recovery_token(target)
    if change=='result':manager.edit(manager.current_id,manager.name,{**manager.headers,'Result':'1-0'})
    else:manager.finish()
    manager.background_recovery(target)
    assert not manager.rec.verified and manager._recovery_future is None
    assert manager.ended
    store.close()


def test_unrelated_preserved_pgn_cannot_become_checkpoint_parent(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    manager._create(chess.Board(),utcnow());manager.correct_line('d4 d5 c4 e6 Nf3 Nf6')
    archived_id=manager.current_id;manager.finish('preserved • older recording')
    original=store.game(archived_id)['pgn']
    # A newly seen game resembles an old game with unread names. There was
    # no witnessed split connecting these records, even in the same session.
    target=played('d4 d5 c4 e6 Nf3')
    manager._create(target,utcnow(),note='Recording started from a visible midgame FEN. Temporary visible board FEN segment.')
    active=manager.current_id
    assert manager._resume_latest_game_at_position(Observation.from_board(target))
    assert manager.current_id==active and len(store.games())==2
    target.push_san('Nf6');manager.process(Observation.from_board(target))
    assert manager.current_id==active and manager.rec.verified==['g8f6']
    assert store.game(archived_id)['pgn']==original
    store.close()


def test_old_library_and_missing_opponent_cannot_change_two_game_recording(tmp_path):
    from datetime import datetime,timedelta,timezone
    outcomes=[]
    for populated in (False,True):
        store=Store(tmp_path/str(populated));manager=GameManager(store,Settings(confirm_on_reply=False))
        tick=[100.];manager._clock=lambda:tick[0]
        second=played('d4 d5 c4 e6 Nc3 Nf6')
        old_id=None
        if populated:
            manager._create(chess.Board(),utcnow());manager.correct_line('d4 d5 c4 e6 Nc3 Nf6')
            manager.headers.update(White='Streamer',Black='Unknown');manager.finish('preserved • old capture')
            old_id=manager.current_id;old_pgn=store.game(old_id)['pgn']
        manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5 Nf3 Nc6 Bc4 Bc5 d3 d6')
        manager.observe_context({'names':{'white':'Streamer','black':'OpponentA'},'names_stable':True,
                                 'clocks':{'white':42,'black':78}},'baseline')
        first=manager.current_id;first_line=manager.rec.verified[:]
        worker=RecordingWorker(manager,Region(0,0,500,500))
        def frame(board,names,clocks=None):
            tick[0]+=1
            stamp=(datetime(2026,10,20,tzinfo=timezone.utc)+timedelta(seconds=tick[0])).isoformat()
            manager.observe_context({'names':names,'names_stable':True,'clocks':clocks or {}},stamp)
            obs=Observation.from_board(board);obs.timestamp=stamp
            return worker.process_observation(obs,2)
        for _ in range(3):
            frame(second,{'white':'Streamer'})
            assert manager.current_id==first and manager.rec.verified==first_line
        # The next game's independent identity and fresh clocks establish
        # the boundary. A shared streamer never identifies an archived game.
        for _ in range(3):frame(second,{'white':'Streamer','black':'OpponentB'},{'white':599,'black':600})
        assert manager.current_id!=first and manager.current_id!=old_id
        second_id=manager.current_id
        second.push_san('Nf3')
        frame(second,{'white':'Streamer','black':'OpponentB'},{'white':598,'black':600})
        assert manager.current_id==second_id
        outcomes.append((manager.headers,manager.rec.initial_fen,manager.rec.verified,
                         chess.pgn.read_game(io.StringIO(store.game(first)['pgn'])).end().board().fen()))
        if populated:assert store.game(old_id)['pgn']==old_pgn
        manager.cancel_background_recovery();store.close()
    assert outcomes[0]==outcomes[1]


def test_confirmed_separate_game_is_not_reopened_as_archive_during_missing_ocr(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5 Nf3 Nc6')
    first=manager.current_id;old=manager.rec.board.copy()
    manager.observe_context({'names':{'white':'Streamer','black':'SameOpponent'},'names_stable':True},'first')
    manager.start_separate_game(Observation.from_board(played('d4')),'observed rematch')
    manager.observe_context({'names':{'white':'Streamer','black':'SameOpponent'},'names_stable':True},'second')
    assert first in manager.separated_from
    assert manager.lifecycle._return_game(manager,Observation.from_board(old)) is None
    store.close()


@pytest.mark.parametrize('completed',[False,True])
def test_startup_opening_with_same_names_is_not_enough_to_reuse_old_game(tmp_path,completed):
    store=Store(tmp_path);old=GameManager(store,Settings(confirm_on_reply=False))
    old._create(chess.Board(),utcnow());old.correct_line('e4 e5 Nf3 Nc6')
    names={'white':'Streamer','black':'Opponent'}
    old.observe_context({'names':names,'names_stable':True},'old names')
    if completed:old.edit(old.current_id,old.name,{**old.headers,'Result':'1-0'})
    else:old.finish()
    original=store.game(old.current_id)['pgn']
    new=GameManager(store,Settings(confirm_on_reply=False))
    new.observe_context({'names':names,'names_stable':True},'new names')
    new.process(Observation.from_board(played('e4')))
    assert new.current_id!=old.current_id and new.rec.verified==['e2e4']
    assert store.game(old.current_id)['pgn']==original
    store.close()


def test_malformed_old_state_cannot_prevent_fresh_recording(tmp_path):
    store=Store(tmp_path);old=GameManager(store,Settings())
    old._create(chess.Board(),utcnow());old.correct_line('e4 e5 Nf3 Nc6')
    names={'white':'Streamer','black':'Opponent'}
    old.observe_context({'names':names,'names_stable':True},'old names')
    with store.transaction() as db:
        db.execute('UPDATE games SET state=? WHERE id=?',(json.dumps({'initial_fen':'damaged FEN','verified':[]}),old.current_id))
    new=GameManager(store,Settings())
    new.observe_context({'names':names,'names_stable':True},'new names')
    target=played('d4 d5 c4 e6 Nc3 Nf6')
    new.process(Observation.from_board(target))
    assert new.current_id!=old.current_id and new.rec.board.board_fen()==target.board_fen()
    store.close()


def test_fen_trace_covers_unstable_held_and_repeated_frames_without_screenshots(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5')
    worker=RecordingWorker(manager,Region(0,0,500,500))
    target=Observation.from_board(played('e4 e5 Nf3'))
    for index,stability in enumerate((1,2,2,2)):
        target.timestamp=f'2026-10-20T00:00:0{index}+00:00'
        worker.process_observation(target,stability)
    rows=store.query('SELECT * FROM board_trace ORDER BY id')
    assert sum(row['comparisons'] for row in rows)==4
    assert json.loads(rows[0]['detail'])['stable'] is False
    assert rows[-1]['comparisons']==3
    detail=json.loads(rows[-1]['detail'])
    assert detail['observed_placement']==target.placement()
    assert chess.Board(detail['accepted_fen']).board_fen()==target.placement()
    assert not store.screenshots() and not list(store.images.rglob('*.png'))
    bundle=export_diagnostics(store,tmp_path/'diagnostics.zip')
    with zipfile.ZipFile(bundle) as archive:
        report=json.loads(archive.read('diagnostics.json'))
        assert len(report['board_trace'])==len(rows)
        assert not any(path.endswith('.png') for path in archive.namelist())
    # Verify retention at its boundary without 10,000 separate fsyncs.
    with store.transaction() as db:
        db.executemany('INSERT INTO board_trace(session_id,game_id,first_seen,last_seen,comparisons,detail) VALUES(?,?,?,?,?,?)',
            [(manager.session_id,manager.current_id,'a','a',1,'{}')]*10_000)
    store.trace_board(manager.session_id,manager.current_id,'b',{'different':True})
    assert store.query('SELECT COUNT(*) AS n FROM board_trace')[0]['n']==10_000
    store.close()


def test_search_cancellation_is_not_unique_evidence_and_preserves_source():
    source=chess.Board();before=source.fen();checks=[0]
    def canceled():
        checks[0]+=1
        return checks[0]>=2
    target=Observation.from_board(played('d4 d5 c4 e6 Nc3 Nf6'))
    result=LegalSearcher(9,600000,5000).search(source,target,cancelled=canceled)
    assert not result.exhaustive and result.stop_reason=='canceled'
    assert result.nodes<=128 and source.fen()==before
    assert not assess_search(source,result,target).automatic


def test_hypothesis_limit_retains_prior_evidence_instead_of_pruning_to_a_winner():
    rec=Reconstructor(chess.Board(),LegalSearcher(4,path_limit=8))
    first=played('Nf3 Nf6 Nc3 Nc6')
    rec.observe(Observation.from_board(first))
    assert len(rec.branches)==4 and not rec.verified
    previous=[(branch.root_fen,branch.moves) for branch in rec.branches]
    for san in 'a3 a6 h3 h6'.split():first.push_san(san)
    rec.observe(Observation.from_board(first))
    assert rec.incomplete and not rec.verified
    assert [(branch.root_fen,branch.moves) for branch in rec.branches]==previous


@pytest.mark.parametrize('name',['Python','Codex','Slowkaru','Candidate'])
def test_legitimate_usernames_are_not_rejected_by_their_vocabulary(name):
    board=(200,180,700,700)
    for text in (name,name+' (1500)'):
        lines=[(text,.99,(230,90,460,115))]
        assert extract_context(lines,board,'white')['names']=={'black':name}
    assert not extract_context([('Board',.99,(230,90,460,115))],board,'white')['names']


def join_setup(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5')
    old=store.game(manager.current_id);manager.finish()
    manager._create(played('e4 e5 Nf3'),utcnow(),note='Manually selected fragment')
    manager.correct_line('Nc6')
    manager.last_observation=Observation.from_board(manager.rec.board)
    manager.note_evidence(manager.last_observation)
    return store,manager,old


@pytest.mark.parametrize('stale',[False,True,'stop'])
def test_join_previous_search_does_not_block_capture_and_discards_stale_results(tmp_path,monkeypatch,stale):
    import chessstream.saved_joins as joins
    store,manager,old=join_setup(tmp_path);current=manager.current_id
    originals={row['id']:row['pgn'] for row in store.games()}
    entered=Event();release=Event();real_join=joins.join_recordings
    def slow_join(*args,**kwargs):
        entered.set()
        assert release.wait(3)
        return real_join(*args,**kwargs)
    monkeypatch.setattr(joins,'join_recordings',slow_join)
    assert manager.join_previous_recording(background=True) and entered.wait(1)
    future=manager._saved_join_future
    try:
        worker=RecordingWorker(manager,Region(0,0,500,500))
        # This returns while the background search is explicitly blocked.
        worker.process_observation(manager.last_observation,2)
        assert not future.done() and manager.current_id==current
        if stale=='stop':manager.finish()
        elif stale:
            manager.note_evidence(Observation.from_board(played('d4')))
            manager.note_evidence(manager.last_observation)
        release.set();future.result(timeout=3);manager.poll_saved_join()
        if stale:
            assert manager.current_id==current and len(store.games())==2
        else:
            assert manager.current_id not in originals and len(store.games())==3
        assert all(store.game(gid)['pgn']==pgn for gid,pgn in originals.items())
    finally:
        release.set();manager.cancel_saved_join();store.close()


def test_live_checkpoint_join_respects_live_budget_instead_of_expanding_to_five_seconds(tmp_path,monkeypatch):
    store,manager,old=join_setup(tmp_path)
    real=LegalSearcher.search;budgets=[]
    def traced(searcher,*args,**kwargs):
        budgets.append((searcher.time_limit_ms,searcher.node_limit))
        return real(searcher,*args,**kwargs)
    monkeypatch.setattr(LegalSearcher,'search',traced)
    result=manager._join_checkpoint(old['id'],manager.current_id,manager.last_observation)
    assert result and budgets
    assert all(milliseconds<=75 and nodes<=8000 for milliseconds,nodes in budgets)
    store.close()


def test_failed_checkpoint_join_fallback_also_uses_remaining_live_budget(tmp_path,monkeypatch):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5')
    original_id=manager.current_id
    manager._start_from_visible(Observation.from_board(played('e4 e5 Nf3')),'fullscreen reacquisition')
    checkpoint_id=manager.current_id;original=store.game(original_id)['pgn']
    def failed(*args,**kwargs):raise ValueError('No complete segment join')
    monkeypatch.setattr(manager,'_join_checkpoint',failed)
    real=LegalSearcher.search;budgets=[]
    def traced(searcher,*args,**kwargs):
        budgets.append((searcher.time_limit_ms,searcher.node_limit))
        return real(searcher,*args,**kwargs)
    monkeypatch.setattr(LegalSearcher,'search',traced)
    manager._resume_latest_game_at_position(Observation.from_board(played('e4 e5 Nf3 Nc6')))
    assert budgets and all(ms<=75 and nodes<=8000 for ms,nodes in budgets)
    assert manager.current_id==checkpoint_id and store.game(original_id)['pgn']==original
    store.close()


def test_incomplete_pending_move_cannot_be_promoted_by_a_result_popup(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    manager._create(chess.Board(),utcnow())
    board=played('e4');manager.process(Observation.from_board(board))
    manager.rec.incomplete=True
    assert not manager._confirm_terminal_pending(Observation.from_board(board))
    assert not manager.rec.verified
    store.close()


def test_same_player_gap_hold_allows_deeper_recovery_without_splitting_or_stalling(tmp_path,monkeypatch):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5')
    manager.observe_context({'names':{'white':'Streamer','black':'Opponent'},'names_stable':True},'baseline')
    gid=manager.current_id
    # Reproduce a short live classification search exhausting its budget.
    # The deeper worker still has sufficient evidence for a unique two-ply gap.
    monkeypatch.setattr(manager.lifecycle,'_linked',lambda *_:False)
    target=Observation.from_board(played('e4 e5 Nf3 Nc6'))
    worker=RecordingWorker(manager,Region(0,0,500,500))
    worker.process_observation(target,2)
    assert manager.lifecycle.phase=='unresolved move gap' and manager._recovery_future
    manager._recovery_future.result(timeout=3)
    worker.process_observation(target,2)
    worker.process_observation(target,2)
    assert manager.current_id==gid and len(store.games())==1
    assert manager.rec.board.board_fen()==target.placement() and len(manager.rec.verified)==4
    assert manager.lifecycle.phase=='game in progress'
    manager.cancel_background_recovery();store.close()


def test_library_join_started_before_capture_cannot_take_over_the_new_recording(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    import chessstream.gui as gui
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui,'windows',lambda:[])
    window=gui.MainWindow(tmp_path);manager=window.manager
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5')
    first=window.store.game(manager.current_id)
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5 Nf3')
    second=window.store.game(manager.current_id)
    callbacks=[]
    monkeypatch.setattr(window,'selected_games',lambda:[first,second])
    monkeypatch.setattr(window,'background',lambda fn,done:callbacks.append((fn,done)))
    window.join_selected()
    assert callbacks
    manager._create(chess.Board(),utcnow());manager.correct_line('d4')
    live_id=manager.current_id
    class ActiveWorker:
        def isRunning(self):return True
    window.worker=ActiveWorker()
    fn,done=callbacks.pop();done(fn())
    assert manager.current_id==live_id and manager.rec.verified==['d2d4']
    assert any(row['status']=='combined' for row in window.store.games())
    window.worker=None;window.close();window.deleteLater();app.processEvents()


def test_fen_constraints_distinguish_supplied_rights_from_unknown_screenshot_history():
    from chessstream.gap_join import join_recordings
    source=chess.Board('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1')
    target=source.copy();target.castling_rights=0
    def row(gid,board):
        game=chess.pgn.Game();game.setup(board)
        return {'id':gid,'started':gid,'pgn':str(game)}
    earlier=row('a',source);later=row('b',target)
    searcher=LegalSearcher(1,2000,30)
    with pytest.raises(ValueError):
        join_recordings([earlier,later],searcher,deep_search=False)
    later['state']=json.dumps({'history_unknown':True})
    result=chess.pgn.read_game(io.StringIO(join_recordings([earlier,later],searcher,deep_search=False)))
    assert result.end().board().castling_rights==source.castling_rights
    later['status']='imported'
    with pytest.raises(ValueError):
        join_recordings([earlier,later],searcher,deep_search=False)

    source=chess.Board('7k/8/8/3pP3/8/8/8/K7 w - d6 0 1')
    target=source.copy();target.ep_square=None
    exact=searcher.search(source,Observation.from_board(target),target_turn=target.turn,target_ep_square=None)
    assert not exact.paths  # Equal placement is not equal en-passant history.


def test_incomplete_buffered_transition_does_not_seed_a_new_game_history(tmp_path,monkeypatch):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    manager._create(chess.Board(),utcnow())
    start=Observation.from_board(chess.Board());end=Observation.from_board(played('e4'))
    manager.lifecycle.frames.extend([(start,{}),(end,{})])
    monkeypatch.setattr(LegalSearcher,'search',lambda *a,**k:
                        SearchResult(paths=[(chess.Move.from_uci('e2e4'),)],exhaustive=False,shortest_proven=True))
    manager.start_separate_game(end)
    assert manager.rec.initial_fen.split()[0]==end.placement() and not manager.rec.verified
    store.close()


def test_buffered_intermediate_frames_can_prove_repeated_piece_moves():
    from chessstream.recovery import recover_gap
    frames=[Observation.from_board(played(line)) for line in ('','Nf3','Nf3 e5')]
    target=Observation.from_board(played('Nf3 e5 Ng5'))
    result=recover_gap([Reconstructor(chess.Board()).serialize()],target,4,60000,350,frames)
    assert result and result[1]['verified']==['g1f3','e7e5','f3g5']


def test_bare_screenshot_join_uses_established_turn_instead_of_the_default_white_root():
    from chessstream.gap_join import join_recordings
    beginning=chess.pgn.Game()
    target=played('e4')
    white_root=chess.Board(f'{target.board_fen()} w - - 0 1')
    roots=[chess.Board(f'{target.board_fen()} {turn} - - 0 1').fen() for turn in ('w','b')]
    later=chess.pgn.Game();later.setup(white_root)
    state=Reconstructor(white_root,roots=roots).serialize()
    rows=[{'id':'a','started':'a','pgn':str(beginning)},
          {'id':'b','started':'b','pgn':str(later),'state':json.dumps(state)}]
    original=rows[1]['pgn']
    result=chess.pgn.read_game(io.StringIO(join_recordings(rows,LegalSearcher(2),deep_search=False)))
    assert list(result.mainline_moves())==[chess.Move.from_uci('e2e4')]
    assert result.end().board().turn==chess.BLACK and rows[1]['pgn']==original


def test_long_unresolved_history_stops_growing_without_erasing_legacy_evidence():
    legacy=played('Nf3 Nf6 Ng1 Ng8 '*8+'Nf3')
    moves=tuple(move.uci() for move in legacy.move_stack)
    rec=Reconstructor(chess.Board())
    rec.branches=[Branch(chess.STARTING_FEN,moves)]
    rec.observe(Observation.from_board(legacy))
    assert rec.incomplete and not rec.verified and rec.branches[0].moves==moves
