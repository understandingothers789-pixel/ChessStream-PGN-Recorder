"""Essential recording, gap, ambiguity, result and PGN export regressions."""
import io
import json
import pytest
import chess
import chess.pgn
from chessstream.domain import Settings,Observation
from chessstream.storage import Store
from chessstream.games import GameManager,export_pgn
from chessstream.reconstruction import LegalSearcher
from chessstream.gap_join import join_recordings,AmbiguousGapError
from chessstream.capture import should_save_screenshot

PREFIX='e4 e6 d4 d5 e5 c5 Bb5+ Bd7 a4 cxd4'


def record(store,settings,line):
    manager=GameManager(store,settings);board=chess.Board()
    manager.process(Observation.from_board(board))
    for san in line.split():board.push_san(san);manager.process(Observation.from_board(board))
    return manager,board


def test_queen_capture_gap_resumes_latest_with_or_without_pending_move_and_labels_inference(tmp_path):
    for pending in (False,True):
        store=Store(tmp_path/str(pending));settings=Settings(confirm_on_reply=pending)
        first,board=record(store,settings,PREFIX);gid=first.current_id;first.finish()
        board.push_san('Qxd4');resumed=GameManager(store,settings)
        resumed.recover(gid);assert resumed._resume_latest_game_at_position(Observation.from_board(board))
        resumed.process(Observation.from_board(board))
        assert resumed.current_id==gid and len(store.games())==1
        board.push_san('Ne7');resumed.process(Observation.from_board(board))
        if pending:resumed.choose(0)
        game=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
        nodes=list(game.mainline())
        assert not game.errors and game.end().board().fen()==board.fen()
        assert 'Inferred across capture gap' in nodes[10].comment
        assert all('Inferred across capture gap' not in node.comment for node in nodes[:10])
        restored=GameManager(store,settings);restored.recover(gid)
        assert restored.inferred_moves['11']['uci']=='d1d4'
        store.close()


def test_live_multi_move_gap_keeps_one_game_and_hovers_remain_provisional(tmp_path):
    store=Store(tmp_path);manager,board=record(store,Settings(),'e4 e5 Nf3 Nc6 Bc4 Bc5 d4 Bxd4 c3 Bb6')
    gid=manager.current_id
    for san in 'Ng5 Nh6 Qf3'.split():board.push_san(san)
    manager.process(Observation.from_board(board))
    assert manager.current_id==gid and manager.snapshot()['pending_moves']==['Qf3']
    assert manager.rec.verified[-2:]==['f3g5','g8h6']
    for _ in range(3):manager.process(Observation.from_board(board))
    assert manager.snapshot()['pending_moves']==['Qf3']
    assert len(store.games())==1
    assert 'Inferred across capture gap' in store.game(gid)['pgn']
    rewind=chess.Board()
    for san in 'e4 e5 Nf3'.split():rewind.push_san(san)
    restored=GameManager(store,Settings());restored.recover(gid);restored.process(Observation.from_board(rewind))
    assert restored.current_id==gid and restored.rec.verified==manager.rec.verified
    assert 'Review position' in restored.last_message
    store.close()


def test_live_fen_checkpoint_reconnects_to_preserved_game_after_window_transition(tmp_path):
    store=Store(tmp_path);settings=Settings(confirm_on_reply=False)
    manager,board=record(store,settings,'e4 e5 Nf3 Nc6 Bb5 a6')
    original_id=manager.current_id
    checkpoint=Observation.from_board(board)
    manager._start_from_visible(checkpoint,'simulated fullscreen board reacquisition')
    checkpoint_id=manager.current_id
    assert checkpoint_id!=original_id
    sources={gid:store.game(gid)['pgn'] for gid in (original_id,checkpoint_id)}
    # Window/layout changes can make OCR briefly report a clock jump. A legal
    # midgame continuation should still reconnect to the preserved PGN.
    manager.clocks_recently_reset=lambda:True
    board.push_san('Ba4');board.push_san('Nf6')
    assert manager._resume_latest_game_at_position(Observation.from_board(board))
    assert manager.current_id not in sources
    assert manager.rec.verified[-2:]==['b5a4','g8f6']
    assert manager.store.game(checkpoint_id)['status'].startswith('reconnected • see ')
    assert chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn'])).end().board().board_fen()==board.board_fen()
    assert all(store.game(gid)['pgn']==pgn for gid,pgn in sources.items())
    store.close()


def test_live_fen_checkpoint_is_joined_into_main_pgn_and_becomes_active(tmp_path):
    store=Store(tmp_path);settings=Settings(confirm_on_reply=False)
    manager,board=record(store,settings,'e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6')
    original_id=manager.current_id
    checkpoint=Observation.from_board(board)
    manager._start_from_visible(checkpoint,'simulated fullscreen reacquisition')
    checkpoint_id=manager.current_id
    sources={gid:store.game(gid)['pgn'] for gid in (original_id,checkpoint_id)}
    for san in 'O-O Be7'.split():
        board.push_san(san);manager.process(Observation.from_board(board))
    board.push_san('Re1')
    assert manager._resume_latest_game_at_position(Observation.from_board(board))
    assert manager.current_id not in sources
    combined=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert not combined.errors
    assert [node.san() for node in combined.mainline()]==[
        'e4','e5','Nf3','Nc6','Bb5','a6','Ba4','Nf6','O-O','Be7','Re1']
    assert combined.end().board().board_fen()==board.board_fen()
    assert 'Earlier moves are not included' not in store.game(manager.current_id)['pgn']
    assert 'saved moves remain unchanged' not in store.game(manager.current_id)['pgn']
    assert all(store.game(gid)['pgn']==pgn for gid,pgn in sources.items())
    assert store.game(checkpoint_id)['status'].startswith('reconnected • see ')
    assert 'latest PGN' in manager.last_message or 'Joined the saved PGNs' in manager.last_message
    store.close()


def test_screenshot_images_are_opt_in_but_memory_capture_is_unaffected():
    obs=Observation.from_board(chess.Board())
    settings=Settings()
    assert not settings.save_screenshots
    assert not should_save_screenshot(settings,False,True,False,obs,2)
    settings.save_screenshots=True
    assert should_save_screenshot(settings,False,True,False,None,0)
    assert not should_save_screenshot(settings,False,False,False,obs,2)
    assert not should_save_screenshot(settings,True,True,False,obs,2)
    assert not should_save_screenshot(settings,False,True,True,None,2)
    assert should_save_screenshot(settings,False,True,True,obs,2)


def test_resumed_equal_shortest_lines_are_preserved_not_arbitrarily_selected(tmp_path):
    store=Store(tmp_path);first,board=record(store,Settings(),'');first.finish()
    for san in 'Nf3 Nf6 Nc3 Nc6'.split():board.push_san(san)
    resumed=GameManager(store,Settings());resumed.recover(first.current_id)
    assert resumed._resume_latest_game_at_position(Observation.from_board(board))
    resumed.process(Observation.from_board(board))
    assert resumed.current_id==first.current_id and len(store.games())==1
    assert len(resumed.rec.branches)>1
    assert all(b.board().board_fen()==board.board_fen() for b in resumed.rec.branches)
    # The screenshot is insufficient to establish the four move order.
    assert 'Equal shortest legal paths reached this position' not in store.game(first.current_id)['pgn']
    target=chess.pgn.Game();target.setup(board)
    rows=[dict(id='a',started='2026-10-19T10:00:00',pgn=export_pgn(chess.STARTING_FEN,[],{'Result':'*'})),
          dict(id='b',started='2026-10-19T10:04:00',pgn=str(target))]
    with pytest.raises(AmbiguousGapError) as error:
        join_recordings(rows,LegalSearcher())
    assert len(error.value.alternatives)>1
    store.close()


def test_terminal_game_and_unrelated_opening_remain_separate(tmp_path):
    store=Store(tmp_path/'mate');manager,board=record(store,Settings(confirm_on_reply=False),'f3 e5 g4 Qh4#')
    gid=manager.current_id;assert manager.headers['Result']=='0-1'
    manager.process(Observation.from_board(chess.Board()))
    assert manager.current_id==gid and len(store.games())==1
    manager.force_new();assert manager.current_id!=gid and len(store.games())==2
    store.close()
    store=Store(tmp_path/'reset');first,_=record(store,Settings(confirm_on_reply=False),'e4')
    other=chess.Board();other.push_san('d4')
    second=GameManager(store,Settings());second.process(Observation.from_board(other))
    assert second.current_id!=first.current_id and len(store.games())==2
    store.close()


def test_join_saved_segments_fills_qxd4_and_preserves_clocks_and_variations():
    source=chess.Board();moves=[]
    for san in PREFIX.split():move=source.parse_san(san);moves.append(move.uci());source.push(move)
    target=source.copy();target.push_san('Qxd4')
    later=chess.pgn.Game();later.setup(chess.Board(f'{target.board_fen()} b - - 0 1'));node=later
    for san in 'Ne7 Nf3 Nbc6 Qf4'.split():
        move=target.parse_san(san);node=node.add_variation(move);target.push(move)
    later.variations[0].set_clock(444)
    later.add_variation(chess.Move.from_uci('g8f6')).comment='Review alternative'
    rows=[dict(id='a',started='2026-10-19T10:00:00',pgn=export_pgn(chess.STARTING_FEN,moves,{'White':'YO MAMA','Result':'*'})),
          dict(id='b',started='2026-10-19T10:04:00',pgn=str(later),
               state=json.dumps({'history_unknown':True}))]
    original=[row['pgn'] for row in rows]
    joined=chess.pgn.read_game(io.StringIO(join_recordings(rows,LegalSearcher())))
    nodes=list(joined.mainline())
    assert not joined.errors and len(nodes)==15 and joined.end().board().fen()==target.fen()
    assert nodes[10].san()=='Qxd4' and 'Inferred across recording gap' in nodes[10].comment
    assert nodes[11].clock()==444 and len(nodes[10].variations)==2
    assert [row['pgn'] for row in rows]==original


def test_layout_ocr_changes_do_not_replace_verified_or_pending_game(tmp_path):
    store=Store(tmp_path);manager,board=record(store,Settings(),'e4 c5 d3 Nc6 c3')
    gid=manager.current_id;prefix=manager.rec.verified[:]
    manager.pending_identity={'white':'OCR layout changed'}
    manager.clocks_recently_reset=lambda:True
    for _ in range(3):manager.process(Observation.from_board(board))
    assert manager.current_id==gid and manager.rec.verified==prefix
    assert manager.snapshot()['pending_moves']==['c3'] and len(store.games())==1
    manager.finish();resumed=GameManager(store,Settings())
    resumed.recover(gid)
    resumed.pending_identity={'white':'another OCR reading'}
    resumed.process(Observation.from_board(board))
    assert resumed.current_id==gid and resumed.rec.verified==prefix
    store.close()


def test_small_unresolved_difference_preserves_main_pgn_after_timeout(tmp_path):
    store=Store(tmp_path);manager,board=record(store,Settings(),'e4 e5 Nf3 Nc6 Bb5')
    gid=manager.current_id;prefix=manager.rec.verified[:]
    wrong=board.copy();wrong.remove_piece_at(chess.A2)
    manager._find_history_path=lambda obs:None
    manager._resume_latest_game_at_position=lambda obs:False
    now=[0.];manager._clock=lambda:now[0]
    obs=Observation.from_board(wrong)
    manager._track_unresolved_position(obs,'unmatched position')
    now[0]=100.;manager._track_unresolved_position(obs,'unmatched position')
    assert manager.current_id==gid and manager.rec.verified==prefix and len(store.games())==1
    assert 'preserved' in manager.last_message
    store.close()


def test_combine_overlapping_recordings_saves_active_game_and_retains_sources(tmp_path):
    store=Store(tmp_path);settings=Settings(confirm_on_reply=False)
    first,board=record(store,settings,'e4 e5 Nf3');first.finish()
    first_id=first.current_id
    # A duplicate full prefix followed by new play must not require a backward gap.
    second=GameManager(store,settings);second._create(chess.Board(),Observation.from_board(board).timestamp)
    board=chess.Board()
    for san in 'e4 e5 Nf3 Nc6 Bb5'.split():
        board.push_san(san);second.rec.board.push_san(san)
        second.rec.verified.append(second.rec.board.peek().uci());second.rec.history.append(board.board_fen())
    from chessstream.reconstruction import Branch
    second.rec.branches=[Branch(board.fen(),())];second.persist()
    second_id=second.current_id
    rows=[store.game(first_id),store.game(second_id)]
    combined_id=second.combine_games(rows)
    game=chess.pgn.read_game(io.StringIO(store.game(combined_id)['pgn']))
    assert [node.san() for node in game.mainline()]==['e4','e5','Nf3','Nc6','Bb5']
    assert second.current_id==combined_id and len(store.games())==3
    assert store.game(first_id)['status'].startswith('combined source')
    fresh=GameManager(store,settings);fresh.recover(combined_id);fresh.process(Observation.from_board(board))
    assert fresh.current_id==combined_id
    store.close()


def test_combine_older_recordings_does_not_replace_a_live_game(tmp_path):
    store=Store(tmp_path);settings=Settings(confirm_on_reply=False)
    first,board=record(store,settings,'e4 e5 Nf3');first.finish()
    first_id=first.current_id
    second=GameManager(store,settings);second._create(chess.Board(),Observation.from_board(board).timestamp)
    board=chess.Board()
    for san in 'e4 e5 Nf3 Nc6 Bb5'.split():
        board.push_san(san);second.rec.board.push_san(san)
        second.rec.verified.append(second.rec.board.peek().uci());second.rec.history.append(board.board_fen())
    from chessstream.reconstruction import Branch
    second.rec.branches=[Branch(board.fen(),())];second.persist()
    second_id=second.current_id

    live,live_board=record(store,settings,'d4 d5')
    live_id=live.current_id;live_moves=live.rec.verified[:];live_headers=dict(live.headers)
    joined_id=live.combine_games([store.game(first_id),store.game(second_id)],activate=False)

    assert store.game(joined_id)['status']=='combined'
    assert live.current_id==live_id and live.rec.verified==live_moves and live.headers==live_headers
    assert live.rec.board.board_fen()==live_board.board_fen()
    assert store.game(first_id)['status'].startswith('combined source')
    assert store.game(second_id)['status'].startswith('combined source')
    store.close()


def test_half_second_settling_exports_without_reply_and_revises_latest_guess(tmp_path):
    store=Store(tmp_path);manager,board=record(store,Settings(),'e4 e5 Nf3 Nc6')
    now=[0.];manager._clock=lambda:now[0];manager.reset_settling()
    gid=manager.current_id;before=len(manager.rec.verified)
    manager.process(Observation.from_board(board))
    now[0]=.49;manager.process(Observation.from_board(board))
    assert len(manager.rec.verified)==before
    now[0]=.5;manager.process(Observation.from_board(board))
    assert manager.rec.verified[-1]=='b8c6' and not manager.snapshot()['pending_moves']
    assert 'not independently verified' in store.game(gid)['pgn']
    assert len(manager.rec.verified) in manager.snapshot()['guessed_plies']
    manager.recover(gid)  # replaceable suffix survives a restart/recovery
    # The apparent Nc6 was a hover; Black actually drops the knight on f6.
    board.pop();board.push_san('Nf6')
    now[0]=3.;manager.process(Observation.from_board(board))
    now[0]=5.;manager.process(Observation.from_board(board))
    assert manager.current_id==gid and manager.rec.verified[-1]=='g8f6'
    game=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
    assert game.end().board().fen()==board.fen() and len(store.games())==1
    assert 'Nc6' not in [node.san() for node in game.mainline()]
    store.close()


def test_settled_gap_keeps_prefix_when_search_is_inconclusive(tmp_path):
    store=Store(tmp_path);manager,board=record(store,Settings(),'e4 e5 Nf3 Nc6')
    now=[0.];manager._clock=lambda:now[0]
    gid=manager.current_id;prefix=manager.rec.verified[:]
    for san in 'Bc4 Bc5 d3'.split():board.push_san(san)
    obs=Observation.from_board(board)
    from chessstream.reconstruction import ReconstructionUpdate
    manager.rec.observe=lambda obs:ReconstructionUpdate(status='search limit • evidence retained')
    manager.process(obs);now[0]=2.;manager.process(obs)
    # A stable board does NOT make first_shortest guesses historical truth.
    assert manager.rec.verified==prefix
    assert manager.current_id==gid and len(store.games())==1
    assert 'Bc4' not in [node.san() for node in chess.pgn.read_game(io.StringIO(store.game(gid)['pgn'])).mainline()]
    invalid=board.copy();invalid.remove_piece_at(chess.E1)
    now[0]=3.;manager.process(Observation.from_board(invalid))
    now[0]=6.;manager.process(Observation.from_board(invalid))
    assert manager.rec.verified==prefix and manager.current_id==gid
    manager.reset_settling();now[0]=20.;manager.process(Observation.from_board(invalid))
    assert manager._settled_since is None
    store.close()


def test_castling_both_colors_and_wings_settles_without_an_opponent_reply(tmp_path):
    from chessstream.domain import utcnow
    for color in ('w','b'):
        for san in ('O-O','O-O-O'):
            store=Store(tmp_path/(color+san));manager=GameManager(store,Settings())
            board=chess.Board(f'r3k2r/ppp2ppp/8/3pp3/3PP3/8/PPP2PPP/R3K2R {color} KQkq - 0 10')
            now=[0.];manager._clock=lambda:now[0]
            manager._create(board.copy(),utcnow());board.push_san(san)
            manager.process(Observation.from_board(board))
            now[0]=.5;manager.process(Observation.from_board(board))
            game=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
            assert [n.san() for n in game.mainline()]==[san]
            assert game.end().board().fen()==board.fen()
            assert not manager.snapshot()['pending_moves']
            store.close()


def test_false_rook_detour_and_capture_are_repaired_when_knight_reappears(tmp_path):
    from chessstream.domain import utcnow
    store=Store(tmp_path);manager=GameManager(store,Settings())
    source=chess.Board('r3k3/8/8/8/4n3/8/8/1B2K3 b q - 0 1')
    manager._create(source,utcnow());gid=manager.current_id
    # A previous observation led to an inferred rook detour and false capture.
    for san in 'Ra7 Bxe4 Ra8 Bb1'.split():
        manager.rec.board.push_san(san)
        manager.rec.verified.append(manager.rec.board.peek().uci())
        manager.rec.history.append(manager.rec.board.board_fen())
    from chessstream.reconstruction import Branch
    manager.rec.branches=[Branch(manager.rec.board.fen(),())]
    for ply,uci in enumerate(manager.rec.verified,1):
        manager.inferred_moves[str(ply)]={'uci':uci,'comment':'Inferred across capture gap'}
    manager.persist();manager.recover(gid)
    target=source.copy();target.push_san('Nc5')
    now=[0.];manager._clock=lambda:now[0];manager.reset_settling()
    manager.process(Observation.from_board(target))
    now[0]=.5;manager.process(Observation.from_board(target))
    assert manager.current_id==gid and manager.rec.verified==['e4c5']
    game=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
    assert game.end().board().fen()==target.fen()
    assert [node.san() for node in game.mainline()]==['Nc5']
    assert len(store.games())==1 and 'Inferred:' in store.game(gid)['pgn']
    store.close()


def test_comparison_period_is_at_least_two_hz_independent_of_image_saving():
    from chessstream.capture import recognition_period
    assert recognition_period(Settings())==.5
    for enabled in (False,True):
        assert recognition_period(Settings(adaptive=False,interval=10,save_screenshots=enabled))==.5
    assert recognition_period(Settings(adaptive=True,adaptive_fps=6))<.5


def test_half_second_counts_from_first_frame_before_worker_animation_gate(tmp_path):
    from chessstream.capture import RecordingWorker,Region
    store=Store(tmp_path);manager,board=record(store,Settings(),'e4 e5 Nf3')
    board.push_san('Nc6');obs=Observation.from_board(board)
    now=[0.];manager._clock=lambda:now[0];manager.reset_settling()
    worker=RecordingWorker(manager,Region(0,0,600,600))
    worker.process_observation(obs,1)
    now[0]=.5;worker.process_observation(obs,2)
    assert manager.rec.verified[-1]=='b8c6' and not manager.snapshot()['pending_moves']
    store.close()


CLARIFIED_OPENING='e4 c5 d3 Nc6 c3 d5 f3 e5 Ne2 Nf6 g3 c4 dxc4 dxe4 Qxd8+ Nxd8 fxe4 Nxe4'


def test_reported_skipped_moves_hold_unproven_routes_and_allow_manual_verified_line(tmp_path):
    for skip in (False,True):
        store=Store(tmp_path/str(skip));manager,board=record(store,Settings(),CLARIFIED_OPENING)
        gid=manager.current_id;now=[0.];manager._clock=lambda:now[0];manager.reset_settling()
        for index,san in enumerate('Bg2 Nc5 O-O Nd3'.split()):
            board.push_san(san)
            if skip and index%2==0:continue
            now[0]+=5. if skip else 1.
            obs=Observation.from_board(board)
            if san=='Nd3':
                obs.probabilities[chess.C5]=0
                obs.probabilities[chess.C5,0]=.749
                obs.probabilities[chess.C5,8]=.251
            manager.process(obs)
            now[0]+=.5;manager.process(obs)
        game=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
        sans=[node.san() for node in game.mainline()]
        assert not game.errors
        assert 'Rb8' not in sans and 'Ra8' not in sans
        assert manager.current_id==gid and len(store.games())==1
        # The previous behavior forced a guessed skipped-move path after 0.5s.
        # When the original video supplies the exact SAN, it can be supplied
        # as a non-destructive, explicit correction.
        if game.end().board().board_fen()!=board.board_fen():
            expected=(CLARIFIED_OPENING+' Bg2 Nc5 O-O Nd3').split()
            assert sans==expected[:len(sans)],('Existing PGN diverged',sans)
            remaining=expected[len(sans):]
            assert remaining
            manager.correct_line(' '.join(remaining))
        game=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
        assert not game.errors
        assert [node.san() for node in game.mainline()][-5:]==[
            'Nxe4','Bg2','Nc5','O-O','Nd3']
        assert game.end().board().board_fen()==board.board_fen()
        store.close()


def test_reported_rook_and_bishop_detour_is_replaced_by_nc5_without_losing_opening(tmp_path):
    store=Store(tmp_path);manager,source=record(store,Settings(confirm_on_reply=False),CLARIFIED_OPENING+' Bg2')
    gid=manager.current_id;prefix=manager.rec.verified[:];before=len(prefix)
    for san in 'Rb8 Bxe4 Ra8 Bg2'.split():
        manager.rec.board.push_san(san)
        uci=manager.rec.board.peek().uci();manager.rec.verified.append(uci)
        manager.rec.history.append(manager.rec.board.board_fen())
        manager.inferred_moves[str(len(manager.rec.verified))]={'uci':uci,'comment':'Inferred across capture gap'}
    from chessstream.reconstruction import Branch
    manager.rec.branches=[Branch(manager.rec.board.fen(),())];manager.persist();manager.recover(gid)
    target=source.copy();target.push_san('Nc5')
    now=[0.];manager._clock=lambda:now[0];manager.reset_settling()
    manager.process(Observation.from_board(target))
    now[0]=.5;manager.process(Observation.from_board(target))
    assert manager.rec.verified[:before]==prefix
    assert manager.rec.verified[before:]==['e4c5']
    game=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
    assert [n.san() for n in game.mainline()][-3:]==['Nxe4','Bg2','Nc5']
    assert game.end().board().fen()==target.fen()
    assert manager.current_id==gid and len(store.games())==1
    store.close()


REWIND_OPENING='d4 a6 e4 b5 Bd3 Bb7 Nf3 e6 O-O Nf6 Re1'


def test_rewind_does_not_append_rook_detours_and_resumes_live_game_after_restart(tmp_path):
    store=Store(tmp_path);manager,live=record(store,Settings(confirm_on_reply=False),REWIND_OPENING)
    gid=manager.current_id;prefix=manager.rec.verified[:]
    previous=chess.Board()
    for san in 'd4 a6 e4 b5 Bd3 Bb7 Nf3'.split():previous.push_san(san)
    now=[0.];manager._clock=lambda:now[0]
    manager.process(Observation.from_board(previous))
    assert manager.rewind_state and manager.rec.verified==prefix
    # Pause on the historical board well beyond the normal acceptance timer.
    now[0]=10.;manager.process(Observation.from_board(previous))
    manager.recover(gid)
    assert manager.rewind_state
    for san in 'e6 O-O Nf6'.split():
        previous.push_san(san);now[0]+=1.
        manager.process(Observation.from_board(previous))
        assert manager.rec.verified==prefix
    previous.push_san('Re1');manager.process(Observation.from_board(previous))
    assert manager.rewind_state is None
    live.push_san('g6');manager.process(Observation.from_board(live))
    game=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
    assert game.end().board().fen()==live.fen()
    assert manager.rec.verified[:len(prefix)]==prefix
    assert all(n.san() not in ('Ra7','Rf1','Ra8') for n in game.mainline())
    assert len(store.games())==1
    store.close()


def test_confirmed_rewind_removes_only_a_recent_inferred_rook_round_trip(tmp_path):
    store=Store(tmp_path);manager,board=record(store,Settings(confirm_on_reply=False),
        'd4 a6 e4 b5 Bd3 Bb7 Nf3 e6 O-O Nf6')
    before=len(manager.rec.verified)
    for san in 'Re1 Ra7 Rf1 Ra8 Re1 g6'.split():
        board.push_san(san);manager.process(Observation.from_board(board))
    for p in range(before+1,before+5):
        manager.inferred_moves[str(p)]={'uci':manager.rec.verified[p-1],'comment':'Inferred across capture gap'}
    manager.move_clocks[str(before+5)]=570;manager.persist()
    rewound=chess.Board()
    for san in 'd4 a6 e4 b5 Bd3 Bb7 Nf3'.split():rewound.push_san(san)
    manager.process(Observation.from_board(rewound))
    game=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert [n.san() for n in game.mainline()][-2:]==['Re1','g6']
    assert len(manager.rec.verified)==before+2 and manager.move_clocks[str(before+1)]==570
    assert game.end().board().board_fen()==board.board_fen()
    store.close()


def test_real_single_move_repetition_is_not_mistaken_for_video_rewind(tmp_path):
    store=Store(tmp_path);manager,board=record(store,Settings(confirm_on_reply=False),'Nf3 Nf6 Ng1 Ng8 Nf3 Nf6')
    assert len(manager.rec.verified)==6 and manager.rewind_state is None
    assert manager.rec.board.fen()==board.fen()
    store.close()
