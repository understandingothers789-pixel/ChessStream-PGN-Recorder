import io
import json
import numpy as np
import chess
import chess.pgn
from chessstream.domain import Observation,Settings,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store


def play(board,line):
    for san in line.split():board.push_san(san)
    return board


def test_stable_unmatched_board_starts_new_fen_pgn_and_keeps_old_game(tmp_path):
    store=Store(tmp_path)
    settings=Settings(max_plies=1,confirm_on_reply=False,unresolved_fen_seconds=10,new_game_change_seconds=10)
    manager=GameManager(store,settings);now=[100.0];manager._clock=lambda:now[0]
    start=chess.Board();manager.process(Observation.from_board(start))
    after_e4=play(chess.Board(),'e4');manager.process(Observation.from_board(after_e4))
    old_id=manager.current_id
    destination=play(chess.Board(),'e4 e5 Nf3 Nc6 Bc4 Bc5 d4')
    observed=Observation.from_board(destination);manager.process(observed)
    assert manager.current_id==old_id
    assert 'new FEN recording in' in manager.last_message
    image=np.zeros((80,80,3),np.uint8)
    store.save_screenshot(manager.session_id,old_id,image,observed.timestamp,
                          destination.board_fen(),observed.confidence,1)
    now[0]+=9
    manager.process(Observation.from_board(destination))
    assert manager.current_id==old_id
    now[0]+=2
    manager.process(Observation.from_board(destination))
    new_id=manager.current_id
    assert new_id!=old_id
    assert store.game(old_id)['plies']==1
    old_pgn=chess.pgn.read_game(io.StringIO(store.game(old_id)['pgn']))
    assert [m.uci() for m in old_pgn.mainline_moves()]==['e2e4']
    new_pgn=chess.pgn.read_game(io.StringIO(store.game(new_id)['pgn']))
    assert new_pgn.headers['SetUp']=='1'
    assert chess.Board(new_pgn.headers['FEN']).board_fen()==destination.board_fen()
    assert list(new_pgn.mainline_moves())==[]
    assert store.screenshots({'game_id':new_id})
    assert store.query("SELECT * FROM audit WHERE action='visible FEN checkpoint'")
    # The next observed black move selects the correct side-to-move root.
    destination.push_san('Bxd4')
    manager.process(Observation.from_board(destination))
    assert manager.rec.initial_fen.split()[1]=='b'
    assert manager.rec.verified==['c5d4']
    store.close()


def test_changed_or_matched_position_cancels_unresolved_fen_timer(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(max_plies=1,confirm_on_reply=False,unresolved_fen_seconds=10))
    now=[20.0];manager._clock=lambda:now[0]
    manager.process(Observation.from_board(chess.Board()))
    initial=play(chess.Board(),'e4');manager.process(Observation.from_board(initial));old_id=manager.current_id
    far=play(initial.copy(),'e5 Nf3 Nc6 Bc4');manager.process(Observation.from_board(far))
    now[0]+=9
    changed=play(initial.copy(),'e5 Nf3');manager.process(Observation.from_board(changed))
    assert manager.current_id==old_id
    assert manager._unresolved_position==changed.board_fen()
    # Returning to the verified board also clears the timer.
    manager.process(Observation.from_board(initial))
    assert manager._unresolved_since is None
    now[0]+=100
    manager.process(Observation.from_board(initial))
    assert manager.current_id==old_id
    store.close()


def test_unmatched_jump_from_midgame_root_can_recover_before_any_verified_ply(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(max_plies=1,confirm_on_reply=False,unresolved_fen_seconds=2,new_game_change_seconds=2))
    now=[50.0];manager._clock=lambda:now[0]
    initial=play(chess.Board(),'e4 e5 Nf3 Nc6 Bc4')
    manager.process(Observation.from_board(initial));old_id=manager.current_id
    assert not manager.rec.verified
    jumped=play(chess.Board(),'d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7')
    manager.process(Observation.from_board(jumped))
    now[0]+=3
    manager.process(Observation.from_board(jumped))
    assert manager.current_id!=old_id
    assert store.game(old_id)['plies']==0
    assert chess.Board(manager.rec.initial_fen).board_fen()==jumped.board_fen()
    store.close()


def test_start_from_visible_fen_and_copy_candidates_keep_uncertain_turn_explicit(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    board=play(chess.Board(),'e4 e5 Nf3 Nc6 Bc4')
    manager.process(Observation.from_board(board));old_id=manager.current_id
    candidates=manager.visible_fens()
    assert len(candidates)==2
    assert {chess.Board(fen).turn for fen in candidates}=={chess.WHITE,chess.BLACK}
    manager.force_new()
    assert manager.current_id!=old_id
    assert manager.rec.initial_fen.split()[0]==board.board_fen()
    assert len(manager.rec.branches)==2
    assert 'visible midgame FEN' in manager.note
    store.close()


def test_recovery_timeout_load_is_bounded_and_old_settings_default_safe(tmp_path):
    settings_file=tmp_path/'settings.json';settings_file.write_text(json.dumps({'interval':1}))
    settings=Settings.load(settings_file)
    assert settings.unresolved_fen_seconds==15
    settings_file.write_text(json.dumps({'unresolved_fen_seconds':99999}))
    assert Settings.load(settings_file).unresolved_fen_seconds==600


def test_confident_but_invalid_popup_position_does_not_crash_automatic_recovery(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(max_plies=1,confirm_on_reply=False,unresolved_fen_seconds=1,new_game_change_seconds=1))
    now=[10.];manager._clock=lambda:now[0]
    manager.process(Observation.from_board(chess.Board()));gid=manager.current_id
    obscured=Observation.from_board(chess.Board(None))
    manager.process(obscured);now[0]+=2;manager.process(obscured)
    assert manager.current_id==gid
    assert 'do not form a valid FEN' in manager.last_message
    store.close()


def test_unexplained_large_board_change_splits_after_five_seconds_and_preserves_old_game(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(max_plies=2,confirm_on_reply=False))
    now=[100.0];manager._clock=lambda:now[0]
    manager.process(Observation.from_board(chess.Board()));old_id=manager.current_id
    changed=play(chess.Board(),'d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7')
    manager.process(Observation.from_board(changed))
    now[0]+=4.9;manager.process(Observation.from_board(changed))
    assert manager.current_id==old_id
    now[0]+=.2;manager.process(Observation.from_board(changed))
    assert manager.current_id!=old_id
    assert store.game(old_id)['plies']==0
    assert chess.Board(manager.rec.initial_fen).board_fen()==changed.board_fen()
    store.close()


def test_position_reachable_as_analysis_branch_stays_with_existing_game(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(max_plies=2,confirm_on_reply=False))
    now=[200.0];manager._clock=lambda:now[0]
    board=chess.Board();manager.process(Observation.from_board(board))
    for san in 'e4 e5 Nf3 Nf6'.split():
        board.push_san(san);manager.process(Observation.from_board(board))
    old_id=manager.current_id
    alternative=play(chess.Board(),'e4 e5 Nf3 Nc6')
    manager.process(Observation.from_board(alternative))
    assert manager.current_id==old_id
    assert 'Review position' in manager.last_message
    now[0]+=6;manager.process(Observation.from_board(alternative))
    row=store.game(old_id)
    pgn=chess.pgn.read_game(io.StringIO(row['pgn']))
    assert not pgn.errors
    anchor=pgn
    for _ in range(3):anchor=anchor.variations[0]
    assert len(list(anchor.variations))==2
    assert manager.current_id==old_id
    store.close()
