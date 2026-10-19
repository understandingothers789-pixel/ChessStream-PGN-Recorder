import io
import chess
import chess.pgn
from chessstream.domain import Settings,Observation,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store
from chessstream.reconstruction import Branch
from chessstream.repair import simplify_shuffles


GHOST='d4 c6 Bf4 Na6 Bb8 e6 Bf4 Nb8 e3 d5 Nf3 f6'


def recorded(manager,sans):
    manager._create(chess.Board(),utcnow())
    manager.correct_line(sans)
    return manager.rec.board.copy()


def test_manual_repair_removes_interleaved_bishop_knight_excursions_and_preserves_annotations(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    endpoint=recorded(manager,GHOST);game_id=manager.current_id
    manager.move_clocks={'3':590,'6':585,'12':578}
    game=chess.pgn.read_game(io.StringIO(store.game(game_id)['pgn']))
    list(game.mainline())[8].comment='A retained developing move'
    manager.review_pgn=game.accept(chess.pgn.StringExporter())
    assert manager.repair_current()==4
    assert manager.current_id==game_id and manager.rec.board.board_fen()==endpoint.board_fen()
    assert manager._san_line(chess.Board(),manager.rec.verified)==['d4','c6','Bf4','e6','e3','d5','Nf3','f6']
    assert manager.move_clocks=={'3':590,'4':585,'8':578}
    exported=store.game(game_id)['pgn'];assert 'A retained developing move' in exported
    assert not chess.pgn.read_game(io.StringIO(exported)).errors
    assert manager.repair_current()==0
    store.close()


def test_automatic_opening_cleanup_requires_unclocked_ghost_or_inferred_excursion(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    endpoint=recorded(manager,GHOST)
    manager.inferred_moves={'1':{'uci':'d2d4','comment':'Guessed opening prefix'}}
    manager.process(Observation.from_board(endpoint))
    assert len(manager.rec.verified)==8
    recorded(manager,'Nf3 Nf6 Ng1 Ng8')
    assert manager.repair_current(automatic=True)==0
    recorded(manager,GHOST)
    manager.inferred_moves={'1':{'uci':'d2d4','comment':'Guessed opening prefix'}}
    manager.move_clocks={'4':580,'5':579,'7':578,'8':577}
    assert manager.repair_current(automatic=True)==0
    store.close()


def test_join_previous_keeps_live_pending_move_and_activates_combined_game(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    recorded(manager,'e4 e5');previous=manager.current_id;manager.finish()
    target=manager.rec.board.copy();target.push_san('Nf3')
    manager._create(target,utcnow(),note='visible midgame FEN')
    manager.correct_line('Nc6');current=manager.current_id
    endpoint=manager.rec.board.copy();goal=endpoint.copy();goal.push_san('Bb5')
    manager.rec.branches=[Branch(manager.rec.board.fen(),('f1b5',))]
    assert manager.join_previous_recording()
    assert manager.current_id not in (previous,current)
    assert manager.rec.board.board_fen()==endpoint.board_fen()
    assert manager.rec.branches[0].board().board_fen()==goal.board_fen()
    assert all(store.game(gid)['status'].startswith('combined source') for gid in (previous,current))
    assert not manager.join_previous_recording()
    store.close()


def test_cleanup_does_not_restore_lost_castling_rights():
    board=chess.Board('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1')
    moves=['h1h2','h8h7','h2h1','h7h8']
    assert simplify_shuffles(board.fen(),moves)==[0,1,2,3]
