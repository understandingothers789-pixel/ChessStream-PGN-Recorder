"""Short-gap continuity, concurrent recovery and exact shortest-path checks."""
from threading import Event
import io
import json
import random
import chess
import chess.pgn
import numpy as np
import pytest
from chessstream.capture import RecordingWorker
from chessstream.domain import Observation,Settings,Region,utcnow
from chessstream.games import GameManager
from chessstream.recovery import RecentFrames,PositionHistory,recover_gap
from chessstream.reconstruction import LegalSearcher,Reconstructor
from chessstream.reachability import forward_material_possible,TravelBound
from chessstream.storage import Store


def played(line,fen=chess.STARTING_FEN):
    board=chess.Board(fen)
    for san in line.split():board.push_san(san)
    return board


def test_missing_first_pair_is_recovered_without_guessing_a_longer_opening(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());now=[0.];manager._clock=lambda:now[0]
    worker=RecordingWorker(manager,Region(0,0,500,500),preview_only=True)
    board=played('e4 c5')
    snapshot=worker.process_observation(Observation.from_board(board),2)
    assert snapshot['recording_started_automatically']
    assert manager.rec.initial_fen==chess.STARTING_FEN and manager.rec.verified==['e2e4']
    for san in 'Nf3 Nc6'.split():
        now[0]+=1;board.push_san(san);worker.process_observation(Observation.from_board(board),2)
    now[0]+=1;worker.process_observation(Observation.from_board(board),2)
    game=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert [node.san() for node in game.mainline()]==['e4','c5','Nf3','Nc6']
    assert 'FEN' not in game.headers and game.end().board().fen()==board.fen()
    assert len(store.games())==1 and not store.screenshots()
    store.close()


def test_new_opponent_seen_after_first_pair_keeps_both_opening_moves(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());now=[0.];manager._clock=lambda:now[0]
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5 Nf3 Nc6')
    manager.observe_context({'names':{'white':'Streamer','black':'OpponentA'},'names_stable':True},'old')
    old_id=manager.current_id;original=store.game(old_id)['pgn']
    target=Observation.from_board(played('d4 d5'))
    for index in range(3):
        now[0]+=1
        manager.observe_context({'names':{'white':'Streamer','black':'OpponentB'},'names_stable':True},str(index))
        manager.process(target)
    assert manager.current_id!=old_id and manager.checkpoint_source_id is None
    assert manager.rec.initial_fen==chess.STARTING_FEN and manager.rec.verified==['d2d4','d7d5']
    assert set(manager.inferred_moves)=={'1','2'}
    assert store.game(old_id)['pgn']==original
    store.close()


def test_old_first_pair_fen_can_gain_prefix_with_its_moves_clocks_and_backup(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    visible=played('e4 c5')
    roots=[chess.Board(f'{visible.board_fen()} {turn} - - 0 1').fen() for turn in ('w','b')]
    manager._create(chess.Board(roots[0]),utcnow(),roots=roots,note='Recording began midgame. Earlier moves were unavailable.')
    manager.correct_line('Nf3 Nc6');manager.move_clocks={'1':590};manager.persist()
    gid=manager.current_id;original=store.game(gid)['pgn']
    manager.recover(gid)
    assert manager.rec.initial_fen==chess.STARTING_FEN
    assert manager.rec.verified==['e2e4','c7c5','g1f3','b8c6'] and manager.move_clocks=={'3':590}
    audit=store.query("SELECT detail FROM audit WHERE action='opening prefix backfilled'")
    assert json.loads(audit[-1]['detail'])['previous_recording']['pgn']==original
    store.close()


def test_imported_fen_with_midgame_comment_is_not_automatically_rebased(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    manager._create(played('e4 c5'),utcnow(),note='Recording began midgame. Imported user history.')
    gid=manager.current_id
    with store.transaction() as db:db.execute("UPDATE games SET status='imported' WHERE id=?",(gid,))
    original=store.game(gid)['pgn'];manager.recover(gid)
    assert manager.rec.initial_fen==played('e4 c5').fen() and not manager.rec.verified
    assert not store.query("SELECT * FROM audit WHERE action='opening prefix backfilled'")
    assert store.game(gid)['pgn']==original
    store.close()


def test_missing_names_and_search_miss_do_not_split_a_possible_forward_gap(tmp_path,monkeypatch):
    import chessstream.recovery as recovery
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False));now=[0.]
    manager._clock=lambda:now[0];manager._create(chess.Board(),utcnow())
    opening='e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6'
    manager.correct_line(opening);gid=manager.current_id;prefix=manager.rec.verified[:]
    target=Observation.from_board(played(opening+' Nc3 d6 Be3 e6 f3 Be7 Qd2 O-O'))
    monkeypatch.setattr(manager.lifecycle,'_linked',lambda *_:False)
    monkeypatch.setattr(recovery,'recover_gap',lambda *args:None)
    worker=RecordingWorker(manager,Region(0,0,500,500))
    for now[0] in (0.,1.,6.,15.,60.):worker.process_observation(target,2)
    assert manager.current_id==gid and len(store.games())==1 and manager.rec.verified==prefix
    assert manager.lifecycle.phase=='unresolved move gap' and not manager.ended
    manager.cancel_background_recovery();store.close()


def test_inferred_capture_can_be_corrected_during_boundary_grace_period(tmp_path,monkeypatch):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False));now=[0.]
    manager._clock=lambda:now[0];manager._create(chess.Board(),utcnow());manager.correct_line('e4 d5 exd5')
    manager.inferred_moves={'3':{'uci':'e4d5','comment':'Inferred: earlier capture reading'}};manager.persist()
    gid=manager.current_id;original=store.game(gid)['pgn']
    monkeypatch.setattr(manager.lifecycle,'_linked',lambda *_:False)
    target=played('e4 d5 Nf3');worker=RecordingWorker(manager,Region(0,0,500,500))
    worker.process_observation(Observation.from_board(target),2)
    assert manager._recovery_future and manager.current_id==gid
    manager._recovery_future.result(timeout=3);now[0]=1.
    worker.process_observation(Observation.from_board(target),2)
    assert manager.current_id==gid and manager.rec.verified==['e2e4','d7d5','g1f3']
    assert manager.rec.board.fen()==target.fen() and len(store.games())==1
    audit=store.query("SELECT detail FROM audit WHERE action='background gap recovered'")
    assert json.loads(audit[-1]['detail'])['previous_recording']['pgn']==original
    manager.cancel_background_recovery();store.close()


def test_position_history_outlives_pixel_churn_and_recovers_order_from_intermediates():
    source=chess.Board();history=PositionHistory();pixels=RecentFrames(12)
    image=np.zeros((20,20,3),np.uint8);boards=[source,played('e4 e5'),played('e4 e5 Nf3 Nc6'),played('e4 e5 Nf3 Nc6 Bc4 Bc5')]
    for board in boards:
        for index in range(20):
            image[:]=index
            obs=Observation.from_board(board);pixels.add(image,obs);pixels.mark('game',True)
            history.add(obs,'game')
    assert len(history.positions)==4 and len(pixels.frames)==12
    assert all(obs.placement()==boards[-1].board_fen() for obs in pixels.observations('game'))
    state=Reconstructor(source).serialize()
    result=recover_gap([state],Observation.from_board(boards[-1]),6,60000,500,history.observations('game'))
    assert result and Reconstructor.restore(result[1]).verified==['e2e4','e7e5','g1f3','b8c6','f1c4','f8c5']
    # History is bounded, copies distributions and isolates game identities.
    mutable=Observation.from_board(source);original=mutable.probabilities.copy()
    history.add(mutable,'other');mutable.probabilities[:]=0
    assert np.array_equal(history.observations('other')[0].probabilities,original)
    bounded=PositionHistory(3)
    for board in boards:bounded.add(Observation.from_board(board),'game')
    assert len(bounded.positions)==3 and bounded.observations('missing')==[]


def pending_recovery(tmp_path,monkeypatch):
    import chessstream.recovery as recovery
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    manager._create(chess.Board(),utcnow());manager.correct_line('e4');manager.rec.status='unmatched position'
    target=Observation.from_board(played('e4 e5 Nf3'));entered=Event();release=Event();real=recovery.recover_gap
    def delayed(*args,**kwargs):
        entered.set()
        assert release.wait(3)
        return real(*args,**kwargs)
    monkeypatch.setattr(recovery,'recover_gap',delayed)
    worker=RecordingWorker(manager,Region(0,0,500,500));worker.process_observation(target,2)
    assert entered.wait(1)
    return store,manager,worker,release,manager._recovery_future


def test_gap_search_finishes_while_new_observed_moves_arrive(tmp_path,monkeypatch):
    store,manager,worker,release,future=pending_recovery(tmp_path,monkeypatch);gid=manager.current_id
    try:
        for line in ('e4 e5 Nf3 Nc6','e4 e5 Nf3 Nc6 Bc4'):
            worker.process_observation(Observation.from_board(played(line)),2)
            assert manager._recovery_future is future and not future.done()
        release.set();future.result(timeout=3)
        target=played('e4 e5 Nf3 Nc6 Bc4');worker.process_observation(Observation.from_board(target),2)
        assert manager.current_id==gid and manager.rec.board.fen()==target.fen()
        assert manager.rec.verified==['e2e4','e7e5','g1f3','b8c6','f1c4']
        audit=store.query("SELECT detail FROM audit WHERE action='background gap recovered'")
        assert json.loads(audit[-1]['detail'])['catchup_frames']==2
    finally:
        release.set();manager.cancel_background_recovery();store.close()


def test_ambiguous_gap_histories_continue_pending_without_starting_another_pgn(tmp_path,monkeypatch):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5');gid=manager.current_id
    target=played('e4 e5 Nf3 Nf6 Nc3 Nc6');manager.rec.status='unmatched position'
    assert manager.background_recovery(Observation.from_board(target))
    manager._recovery_future.result(timeout=3);manager.background_recovery(Observation.from_board(target))
    assert manager.current_id==gid and len(store.games())==1
    assert manager.rec.verified==['e2e4','e7e5'] and len(manager.rec.branches)==4
    assert all(branch.board().board_fen()==target.board_fen() for branch in manager.rec.branches)
    target.push_san('d3')
    manager.process(Observation.from_board(target))
    assert len(manager.rec.branches)==4 and all(branch.moves[-1]=='d2d3' for branch in manager.rec.branches)
    # Exact transpositions cannot disclose earlier order. Explicitly selecting
    # the known actual line remains possible, including the later observed move.
    expected=('g1f3','g8f6','b1c3','b8c6','d2d3')
    chosen=next(index for index,branch in enumerate(manager.rec.branches) if branch.moves==expected)
    manager.choose(chosen)
    assert manager.rec.board.fen()==target.fen() and len(manager.rec.verified)==7
    manager.cancel_background_recovery();store.close()


def test_unknown_turn_recovery_uses_next_legal_move_instead_of_a_roundtrip():
    visible=played('e4');roots=[chess.Board(f'{visible.board_fen()} {turn} - - 0 1').fen() for turn in ('w','b')]
    state=Reconstructor(chess.Board(roots[0]),roots=roots).serialize()
    target=played('e4 c5 Nf3')
    result=recover_gap([state],Observation.from_board(target),6,60000,350,
                       [Observation.from_board(visible),Observation.from_board(played('e4 c5'))])
    assert result
    rec=Reconstructor.restore(result[1])
    assert chess.Board(rec.initial_fen).turn==chess.BLACK and rec.verified==['c7c5','g1f3']
    assert rec.board.board_fen()==target.board_fen() and not rec.gap_requires_confirmation


def test_unknown_turn_stays_pending_until_a_later_frame_distinguishes_it():
    visible=played('e4');roots=[chess.Board(f'{visible.board_fen()} {turn} - - 0 1').fen() for turn in ('w','b')]
    state=Reconstructor(chess.Board(roots[0]),roots=roots).serialize()
    middle=Observation.from_board(played('e4 c5 Nf3'))
    result=recover_gap([state],middle,6,60000,350)
    assert result
    pending=Reconstructor.restore(result[1])
    assert not pending.verified and len(pending.branches)==2
    final=Observation.from_board(played('e4 c5 Nf3 Nc6'))
    result=recover_gap([state],final,6,60000,350,[Observation.from_board(visible),middle])
    assert result
    recovered=Reconstructor.restore(result[1])
    assert chess.Board(recovered.initial_fen).turn==chess.BLACK
    assert recovered.verified==['c7c5','g1f3','b8c6']


def test_reachability_cache_refreshes_when_background_work_finds_pending_endpoints(tmp_path,monkeypatch):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5')
    # The future position is five plies from the accepted prefix but one ply
    # from the newly retained endpoints. A negative cache entry must expire.
    endpoint=Observation.from_board(played('e4 e5 Nf3 Nf6 Nc3 Nc6'))
    target=Observation.from_board(played('e4 e5 Nf3 Nf6 Nc3 Nc6 d3'))
    monkeypatch.setattr(manager,'_find_history_path',lambda *args,**kwargs:None)
    assert manager.lifecycle._linked(manager,target) is False
    result=recover_gap([manager.rec.serialize()],endpoint,6,60000,350)
    assert result
    manager.rec=Reconstructor.restore(result[1],manager.searcher())
    assert manager.rec.verified==['e2e4','e7e5']
    assert manager.lifecycle._linked(manager,target) is True
    store.close()


def test_retry_budgets_grow_then_stop_repeating_identical_failed_work(tmp_path,monkeypatch):
    import chessstream.recovery as recovery
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False));now=[0.]
    manager._clock=lambda:now[0];manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5')
    manager.rec.status='unmatched position';target=Observation.from_board(played('e4 e5 Nf3 Nf6 Nc3 Nc6'))
    monkeypatch.setattr(manager.lifecycle,'_linked',lambda *_:False);calls=[]
    def miss(states,obs,depth,nodes,ms,*args):
        calls.append((depth,nodes,ms));return None
    monkeypatch.setattr(recovery,'recover_gap',miss)
    for now[0] in (0.,4.,8.,12.,16.):
        manager.background_recovery(target)
        if manager._recovery_future:manager._recovery_future.result(timeout=2)
    assert [call[0] for call in calls]==[6,8,10]
    assert all(nodes<=300000 and ms<=1500 for _,nodes,ms in calls)
    manager.settings.search_ms+=50;now[0]=20.;manager.background_recovery(target)
    manager._recovery_future.result(timeout=2)
    assert len(calls)==4
    manager.cancel_background_recovery();store.close()


@pytest.mark.parametrize('interruption',['rewind','opponent','weak-frame'])
def test_advancing_recovery_still_rejects_interruptions(tmp_path,monkeypatch,interruption):
    store,manager,worker,release,future=pending_recovery(tmp_path,monkeypatch)
    try:
        if interruption=='opponent':
            manager.headers.update(White='Streamer',Black='OpponentA')
            manager.observe_context({'names':{'white':'Streamer','black':'OpponentB'},'names_stable':True},'new')
        target=Observation.from_board(played('e4' if interruption=='rewind' else 'e4 e5 Nf3 Nc6'))
        if interruption=='weak-frame':
            weak=Observation.from_board(played('d4'));weak.probabilities[:]=1/13
            manager.observe_frame(weak)
        worker.process_observation(target,2)
        release.set();future.result(timeout=3);worker.process_observation(target,2)
        assert not store.query("SELECT * FROM audit WHERE action='background gap recovered'")
    finally:
        release.set();manager.cancel_background_recovery();store.close()


@pytest.mark.parametrize('ambiguous',[False,True])
def test_checkpoint_automatically_retries_only_recorded_parent_and_keeps_sources(tmp_path,monkeypatch,ambiguous):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5')
    parent=manager.current_id
    line='e4 e5 '+('Nf3 Nf6 Nc3 Nc6' if ambiguous else 'Nf3 Nc6')
    target=Observation.from_board(played(line));manager._start_from_visible(target,'fullscreen checkpoint')
    checkpoint=manager.current_id;sources={gid:store.game(gid)['pgn'] for gid in (parent,checkpoint)}
    monkeypatch.setattr(manager,'_resume_latest_game_at_position',lambda *_:False)
    worker=RecordingWorker(manager,Region(0,0,500,500));worker.process_observation(target,2)
    assert manager._saved_join_future
    manager._saved_join_future.result(timeout=5);worker.process_observation(target,2)
    if ambiguous:
        assert manager.current_id==checkpoint and len(store.games())==2
        for _ in range(3):worker.process_observation(target,2)
        assert len(store.query("SELECT * FROM audit WHERE action='checkpoint background join queued'"))==1
    else:
        assert manager.current_id not in sources and len(store.games())==3
        assert manager.rec.initial_fen==chess.STARTING_FEN
        assert manager.rec.verified==['e2e4','e7e5','g1f3','b8c6']
    assert all(store.game(gid)['pgn']==pgn for gid,pgn in sources.items())
    manager.cancel_saved_join();manager.cancel_background_recovery();store.close()


def test_pawn_matching_and_material_checks_handle_captures_and_promotions():
    source=chess.Board('7k/8/8/8/8/8/P6P/K7 w - - 0 1')
    target=chess.Board('7k/8/8/8/8/PP6/8/K7 w - - 0 1')
    assert not forward_material_possible(source,target)  # a2 cannot supply BOTH a3 and b3
    assert forward_material_possible(played('e4 d5'),played('e4 d5 exd5'))
    promotion=chess.Board('7k/P7/8/8/8/8/8/7K w - - 0 1');after=played('a8=Q+',promotion.fen())
    assert forward_material_possible(promotion,after)
    assert not forward_material_possible(after,promotion)


@pytest.mark.parametrize('fen,line',[
    (chess.STARTING_FEN,'Nf3 Nf6 Nc3 Nc6'),
    (played('e4 e5 Nf3 Nc6 Bc4 Bc5').fen(),'O-O Nf6 d3 d6'),
    ('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1','exd6 Kd7 Ke2'),
    ('7k/P7/8/8/8/8/8/7K w - - 0 1','a8=Q+ Kh7 Qa7+'),
])
def test_travel_bound_preserves_every_shortest_path_and_special_moves(fen,line):
    source=chess.Board(fen);target=Observation.from_board(played(line,fen))
    results=[LegalSearcher(6,300000,3000,path_limit=256,travel_bound=enabled).search(source,target)
             for enabled in (False,True)]
    assert all(result.exhaustive for result in results)
    assert {tuple(move.uci() for move in path) for path in results[0].paths}=={
        tuple(move.uci() for move in path) for path in results[1].paths}
    assert results[0].depth==results[1].depth and results[1].paths


def test_travel_bound_never_overstates_needed_turns_along_legal_sequences():
    randomizer=random.Random(20261023)
    for _ in range(24):
        source=chess.Board();positions=[source.copy()]
        for _ in range(8):
            choices=list(source.legal_moves)
            if not choices:break
            source.push(randomizer.choice(choices));positions.append(source.copy(stack=False))
        bound=TravelBound(positions[-1])
        for index,state in enumerate(positions):
            remaining=len(positions)-1-index
            white=(remaining+int(state.turn==chess.WHITE))//2
            assert bound.possible(state,white,remaining-white)
