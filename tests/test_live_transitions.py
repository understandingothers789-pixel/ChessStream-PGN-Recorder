import chess
from chessstream.domain import Observation,Settings,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store


OLD='e4 c5 d3 Nc6 c3 d5 f3 e5 Ne2 Nf6 g3 c4 dxc4 dxe4 Qxd8+ Nxd8 fxe4 Nxe4 Bg2 Nc5 O-O Nd3'


def board_after(line):
    board=chess.Board()
    for san in line.split():board.push_san(san)
    return board


def manager_at_old_game(tmp_path,enabled=True):
    store=Store(tmp_path);manager=GameManager(store,Settings(split_unlinked_positions=enabled))
    manager._create(chess.Board(),utcnow());manager.correct_line(OLD)
    manager.rewind_state={'anchor_ply':len(manager.rec.verified),'cursor':6}
    return store,manager


def test_unlinked_midgame_exits_rewind_and_starts_fen_after_delay(tmp_path):
    store,manager=manager_at_old_game(tmp_path);time=[0.];manager._clock=lambda:time[0]
    target=board_after('d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3 h6 Bh4 b6 cxd5 exd5')
    previous=manager.current_id
    manager.process(Observation.from_board(target));assert manager.current_id==previous
    time[0]=6.;manager.process(Observation.from_board(target))
    assert manager.current_id!=previous and len(store.games())==2
    assert manager.rec.board.board_fen()==target.board_fen()
    assert store.game(previous)['status'].startswith('preserved')
    store.close()


def test_unlinked_position_setting_can_keep_rewind_protection(tmp_path):
    store,manager=manager_at_old_game(tmp_path,False);time=[0.];manager._clock=lambda:time[0]
    target=board_after('d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3 h6 Bh4 b6 cxd5 exd5')
    previous=manager.current_id
    manager.process(Observation.from_board(target));time[0]=6.
    manager.process(Observation.from_board(target))
    assert manager.current_id==previous and manager.rewind_state
    store.close()


def test_weak_unchanged_b1_does_not_trap_new_opening_in_old_pgn(tmp_path):
    store,manager=manager_at_old_game(tmp_path);time=[0.];manager._clock=lambda:time[0]
    target=board_after('d4 c6 Bf4 d5 e3 e6 Nf3 f6');obs=Observation.from_board(target)
    obs.probabilities[chess.B1]=.66/12;obs.probabilities[chess.B1,2]=.34
    previous=manager.current_id
    manager.process(obs);time[0]=1.1;snapshot=manager.process(obs)
    assert manager.current_id!=previous and manager.rec.initial_fen==chess.STARTING_FEN
    assert any(branch.board().board_fen()==target.board_fen() for branch in manager.rec.branches)
    assert 'b1' in snapshot['recognition_ignored_squares']
    store.close()


def test_reachable_earlier_analysis_branch_keeps_game(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());time=[0.];manager._clock=lambda:time[0]
    manager._create(chess.Board(),utcnow());manager.correct_line('e4 e5 Nf3 Nc6 Bc4 Bc5 d3 d6')
    previous=manager.current_id;target=board_after('e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O')
    manager.process(Observation.from_board(target));time[0]=6.
    manager.process(Observation.from_board(target))
    time[0]=12.;manager.process(Observation.from_board(target))
    assert manager.current_id==previous and len(store.games())==1
    store.close()
