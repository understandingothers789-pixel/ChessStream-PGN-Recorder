"""Opening bootstrap and automatic recording regressions from the reported start."""
import io
from pathlib import Path
import chess
import chess.pgn
import cv2
from chessstream.capture import RecordingWorker
from chessstream.domain import Observation,Region,Settings,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store
from chessstream.vision import ScreenshotRecognizer


def play(line):
    board=chess.Board()
    for san in line.split():board.push_san(san)
    return board


def test_first_opening_move_auto_starts_despite_uncertain_unchanged_d6(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    worker=RecordingWorker(manager,Region(0,0,500,500),preview_only=True)
    worker.process_observation(Observation.from_board(chess.Board()),2)
    assert worker.preview_only and not store.games()
    # Use the actual browser-captured Chess.com e4 board, Black at the bottom,
    # then simulate the reported weak reading on an unrelated empty square.
    image=cv2.imread(str(Path(__file__).parent/'fixtures/themes/chesscom-ocean-01.png'))
    raw=ScreenshotRecognizer().recognize(image,'black')
    assert raw.placement()==play('e4').board_fen()
    raw.probabilities[chess.D6]=.316/12;raw.probabilities[chess.D6,0]=.684
    worker.process_observation(raw,1)
    assert worker.preview_only and not store.games()
    snapshot=worker.process_observation(raw,2)
    assert snapshot['recording_started_automatically'] and not worker.preview_only
    assert manager.rec.initial_fen==chess.STARTING_FEN and snapshot['pending_moves']==['e4']
    assert snapshot['recognition_ignored_squares']==['d6']
    for _ in range(3):worker.process_observation(raw,2)
    assert not manager.rec.verified
    board=play('e4')
    for san in 'c5 d3 Nc6 c3'.split():
        board.push_san(san);snapshot=worker.process_observation(Observation.from_board(board),2)
    game=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert [node.san() for node in game.mainline()]==['e4','c5','d3','Nc6']
    assert snapshot['pending_moves']==['c3'] and 'SetUp' not in game.headers
    assert not list(store.images.rglob('*.png'))
    store.close()


def test_initial_five_ply_opening_uses_pawns_first_and_standard_pgn_root(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    target=play('e4 c5 d3 Nc6 c3')
    snapshot=manager.process(Observation.from_board(target))
    assert manager.rec.initial_fen==chess.STARTING_FEN
    assert snapshot['moves']==['e4','c5','d3','Nc6'] and snapshot['pending_moves']==['c3']
    manager.choose(0)
    game=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert not game.errors and game.end().board().fen()==target.fen()
    assert 'FEN' not in game.headers and 'SetUp' not in game.headers
    assert 'Earlier moves are not included' not in store.game(manager.current_id)['pgn']
    assert 'guessed' in game.comment and 'Pawn moves were prioritized' in game.comment
    assert all('Guessed opening prefix' in node.comment for node in game.mainline())
    assert manager._san_line(chess.Board(),manager._infer_short_opening(
        Observation.from_board(play('Nf3 Nf6 g3'))))==['g3','Nf6','Nf3']
    store.close()


def test_autostart_opt_out_and_sparse_or_uncertain_move_boards_wait(tmp_path):
    store=Store(tmp_path);settings=Settings(auto_record_opening=False);manager=GameManager(store,settings)
    worker=RecordingWorker(manager,Region(0,0,500,500),preview_only=True)
    worker.process_observation(Observation.from_board(play('e4')),2)
    assert worker.preview_only and not store.games()
    settings.auto_record_opening=True
    for raw in [Observation.from_board(chess.Board('7k/8/8/8/8/8/8/K7 w - - 0 1')),
                Observation.from_board(play('e4'))]:
        if raw.placement()==play('e4').board_fen():raw.probabilities[chess.E4]=1/13
        worker.process_observation(raw,2)
        assert worker.preview_only and not store.games()
    store.close()


def test_resuming_legacy_early_fen_backfills_opening_and_preserves_clock(tmp_path):
    store=Store(tmp_path);settings=Settings();first=GameManager(store,settings)
    board=play('e4 c5 d3')
    first._create(chess.Board(f'{board.board_fen()} b - - 0 1'),utcnow(),
        note='Recording started from a visible midgame FEN. Earlier moves are not included.')
    game_id=first.current_id
    for san in 'Nc6 c3'.split():
        board.push_san(san);first.process(Observation.from_board(board))
    first.move_clocks['1']=584;first.finish()
    resumed=GameManager(store,settings);snapshot=resumed.process(Observation.from_board(board))
    assert resumed.current_id==game_id and len(store.games())==1
    assert resumed.rec.initial_fen==chess.STARTING_FEN
    assert snapshot['moves']==['e4','c5','d3','Nc6'] and snapshot['pending_moves']==['c3']
    game=chess.pgn.read_game(io.StringIO(store.game(game_id)['pgn']))
    assert 'FEN' not in game.headers and 'SetUp' not in game.headers
    assert 'Earlier moves are not included' not in store.game(game_id)['pgn']
    assert list(game.mainline())[3].clock()==584
    assert all('Guessed opening prefix' in node.comment for node in list(game.mainline())[:3])
    resumed.process(Observation.from_board(board))
    assert resumed.rec.verified==['e2e4','c7c5','d2d3','b8c6']
    assert len(store.query("SELECT * FROM audit WHERE action='opening prefix backfilled'"))==1
    store.close()


def test_fresh_opening_does_not_reopen_a_completed_game_at_its_old_first_move(tmp_path):
    store=Store(tmp_path);settings=Settings(confirm_on_reply=False)
    first=GameManager(store,settings);board=chess.Board();first.process(Observation.from_board(board))
    for san in 'f3 e5 g4 Qh4#'.split():
        board.push_san(san);first.process(Observation.from_board(board))
    original=first.current_id
    assert first.headers['Result']=='0-1'
    next_game=GameManager(store,settings)
    worker=RecordingWorker(next_game,Region(0,0,500,500),preview_only=True)
    worker.process_observation(Observation.from_board(play('f3')),2)
    assert next_game.current_id!=original and next_game.headers['Result']=='*'
    assert next_game.rec.initial_fen==chess.STARTING_FEN and next_game.rec.verified==['f2f3']
    store.close()
