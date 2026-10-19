import io
import chess
import chess.pgn

from chessstream.analysis_tracking import tree_positions
from chessstream.domain import Observation,Settings,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store


MAIN='d4 d5 Bf4 e6 e3 c6 Nf3 f6 Nbd2 Qb6 Rb1 Bd7 c4 Qd8 Bd3 Na6 a3 Qe7 O-O O-O-O b4 Nc7 e4 g6 Re1 Bh6 Bg3 Bxd2 Qxd2 Qf8 cxd5 exd5 Qf4 Na6 Bb5 Nb8 Ba6 Be6 Bd3 Na6 Bxa6 Bd7 Bb5 Be6'
ANALYSIS='Rc1 Bd7 c4 e5 cxd5 cxd5 e4 dxe4 Nxe4 Nc6 Bc4 exd4 O-O O-O-O'
TARGET='2kr1bnr/pp1b2pp/1qn2p2/8/2BpNB2/5N2/PP3PPP/2RQ1RK1'


def after(sans):
    board=chess.Board()
    for san in sans.split():board.push_san(san)
    return board


def recorded(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());now=[10.]
    manager._clock=lambda:now[0]
    manager._create(chess.Board(),utcnow());manager.correct_line(MAIN)
    manager.headers.update(White='Gear5Luffy',Black='UsoppNoCourage')
    manager.move_clocks={'10':577,'20':536};manager.persist()
    return store,manager,now


def test_reported_replay_transposition_and_streamed_rc1_analysis_stay_in_original_pgn(tmp_path):
    store,manager,now=recorded(tmp_path);original=manager.current_id
    played=manager.rec.verified[:];endpoint=manager.rec.board.fen()
    manager._create(chess.Board(),utcnow(),note='Temporary visible board FEN segment.')
    manager.correct_line('d4 c6 Bf4 e6 e3');fragment=manager.current_id
    manager.headers.update(White='Gear5Luffy',Black='UsoppNoCourage');manager.persist()
    manager.annotate(fragment,[0]*2,'Nf3 d5',comment='Keep this existing fragment variation')
    manager.process(Observation.from_board(manager.rec.board))
    assert manager.current_id==original and len(store.games())==1
    assert store.game(fragment)['status'].startswith('reconnected analysis')
    assert manager.rec.verified==played and manager.move_clocks=={'10':577,'20':536}
    # Following the replay reaches the same position in a different opening order.
    board=after('d4 d5 Bf4 e6 e3 c6 Nf3 f6 Nbd2 Qb6')
    manager.process(Observation.from_board(board))
    for index,san in enumerate(ANALYSIS.split()):
        board.push_san(san);now[0]+=.6
        if index==4:continue  # Miss one frame during the consecutive pawn captures.
        manager.process(Observation.from_board(board));now[0]+=.6
        manager.process(Observation.from_board(board))
    assert board.board_fen()==TARGET
    assert manager.current_id==original and manager.rec.verified==played
    assert manager.rec.board.fen()==endpoint and len(store.games())==1
    game=chess.pgn.read_game(io.StringIO(store.game(original)['pgn']))
    assert not game.errors and [move.uci() for move in game.mainline_moves()]==played
    assert 'Keep this existing fragment variation' in store.game(original)['pgn']
    assert any(not node.is_mainline() and position.board_fen()==TARGET for node,_,position in tree_positions(game))
    assert list(game.mainline())[9].clock()==577
    # The saved variation remains available after restarting the manager.
    restored=GameManager(store,Settings());restored.recover(original)
    assert restored.analysis_cursor and restored.rec.verified==played
    restored.process(Observation.from_board(board))
    assert restored.current_id==original and len(store.games())==1
    store.close()


def test_fen_checkpoint_matches_saved_variation_and_preserves_completed_result(tmp_path):
    store,manager,now=recorded(tmp_path);original=manager.current_id
    manager.annotate(original,[0]*10,ANALYSIS,automatic=True)
    manager.headers['Result']='1-0';manager.persist()
    manager._start_from_visible(Observation.from_board(chess.Board(TARGET+' w - - 0 1')),'test checkpoint')
    fragment=manager.current_id
    manager.headers.update(White='Gear5Luffy',Black='UsoppNoCourage');manager.persist()
    manager.process(Observation.from_board(manager.rec.board))
    assert manager.current_id==original and manager.headers['Result']=='1-0'
    assert len(store.games())==1 and store.game(fragment)['status'].startswith('reconnected analysis')
    store.close()


def test_matching_names_do_not_merge_unlinked_board_or_clock_reset_rematch(tmp_path):
    store,manager,now=recorded(tmp_path);original=manager.current_id
    board=after('e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O b5 Bb3 Be7 Re1 O-O h3 d6')
    manager._start_from_visible(Observation.from_board(board),'unrelated board')
    unrelated=manager.current_id
    manager.headers.update(White='Gear5Luffy',Black='UsoppNoCourage');manager.persist()
    assert not manager._try_replay_recording(Observation.from_board(board))
    assert manager.current_id==unrelated and len(store.games())==2
    manager._create(chess.Board(),utcnow(),note='Temporary visible board FEN segment.')
    manager.correct_line('d4 c6 Bf4 e6 e3')
    manager.headers.update(White='Gear5Luffy',Black='UsoppNoCourage');manager.clock_reset_seen=now[0]
    assert not manager._try_replay_recording(Observation.from_board(manager.rec.board))
    manager.clock_reset_seen=False
    manager.pending_identity={'white':'Another player'}
    assert not manager._try_replay_recording(Observation.from_board(manager.rec.board))
    manager.pending_identity=None;manager.terminal_message={'reason':'aborted'}
    assert not manager._try_replay_recording(Observation.from_board(manager.rec.board))
    assert manager.current_id!=original
    store.close()
