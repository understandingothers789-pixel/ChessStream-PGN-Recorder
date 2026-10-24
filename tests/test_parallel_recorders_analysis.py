"""Live Oct 20: two ChessStream builds processing same Hikaru video,
one at 12 plies saving speculative PGN variations, other at 2 plies.

Only one GUI recorder may own the per-user monitor even when builds use
different --data-dir roots. Live move tracking cannot silently activate a
PGN analysis cursor merely because a legal historical branch happens to
match a later screenshot.
"""
import chess
from PySide6.QtCore import QLockFile

from chessstream.__main__ import gui_lock_path
from chessstream.domain import Observation, Settings, utcnow
from chessstream.games import GameManager
from chessstream.storage import Store


def game_board(sans):
    board=chess.Board()
    for san in sans.split():
        board.push_san(san)
    return board


def test_portable_builds_with_different_data_folders_share_gui_lock(tmp_path):
    # Each build used to lock its own data folder, allowing overlapping GUIs.
    first_data=tmp_path/'previous-build'
    latest_data=tmp_path/'latest-build'
    first_data.mkdir();latest_data.mkdir()
    global_path=gui_lock_path()
    assert global_path!=first_data/'.chessstream-gui.lock'
    assert global_path!=latest_data/'.chessstream-gui.lock'
    first=QLockFile(str(global_path))
    second=QLockFile(str(gui_lock_path()))
    first.setStaleLockTime(0)
    second.setStaleLockTime(0)
    assert first.tryLock(100)
    try:
        assert not second.tryLock(0), 'Second GUI must be refused regardless of data-dir'
    finally:
        first.unlock()
    assert second.tryLock(100)
    second.unlock()


def test_live_recording_never_auto_enters_long_analysis_branch(tmp_path):
    store=Store(tmp_path)
    manager=GameManager(store,Settings())
    line='e4 c5 g3 Nc6 Bg2 g6 d3 Bg7 Nf3 e6 O-O Nge7'
    manager._create(chess.Board(),utcnow())
    manager.correct_line(line)
    manager.headers.update(White='A-TrainOutOfBreath',Black='HomelanderNoMercy')
    manager.lifecycle.bind(manager)
    manager.persist()
    gid=manager.current_id
    before=store.game(gid)['pgn']
    future=game_board(line+' c3 d5 exd5 Nxd5')
    for i in range(6):
        # No selected Analysis mode and no video rewind evidence.
        manager._handle_saved_analysis(Observation.from_board(future))
        assert manager.analysis_cursor is None
        assert manager.rewind_state is None
        assert manager.current_id==gid
    assert store.game(gid)['pgn']==before
    store.close()


def test_deliberately_chosen_analysis_mode_still_available(tmp_path):
    store=Store(tmp_path)
    manager=GameManager(store,Settings())
    manager._create(chess.Board(),utcnow())
    manager.correct_line('e4 e5 Nf3 Nc6')
    manager.set_game_mode('analysis')
    assert manager.lifecycle.mode=='analysis'
    # Manual Analysis is never rewritten to auto by the new live safeguard.
    manager._handle_saved_analysis(Observation.from_board(game_board('e4 e5')))
    assert manager.lifecycle.mode=='analysis'
    store.close()
