"""A visible opening may be farther ahead than the ordinary short-gap search."""
import chess
import chess.pgn
from chessstream.domain import Observation,Settings
from chessstream.games import GameManager
from chessstream.opening import infer_visible_opening
from chessstream.storage import Store
import io


def board_after(sans):
    board=chess.Board()
    for san in sans.split():board.push_san(san)
    return board


def test_ten_ply_castled_opening_proposal_does_not_become_an_unobserved_mainline(tmp_path):
    target=board_after('e4 b5 d4 a6 Bd3 g6 Nf3 Bb7 O-O Bg7')
    path=infer_visible_opening(Observation.from_board(target))
    assert len(path)==10
    result=chess.Board()
    for uci in path:result.push_uci(uci)
    assert result.board_fen()==target.board_fen() and 'e1g1' in path
    store=Store(tmp_path);manager=GameManager(store,Settings(infer_unseen_opening=True))
    snapshot=manager.process(Observation.from_board(target))
    assert manager.rec.initial_fen.split()[0]==target.board_fen()
    assert not snapshot['moves'] and not snapshot['pending_moves']
    for san in ('Nc3','d6'):
        target.push_san(san);manager.process(Observation.from_board(target))
    manager.choose(0)
    game=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert not game.errors and game.end().board().board_fen()==target.board_fen()
    assert 'FEN' in game.headers
    assert [node.san() for node in game.mainline()]==['Nc3','d6']
    store.close()


def test_two_early_captures_still_allow_bounded_opening_inference():
    target=board_after('e4 d5 exd5 Qxd5 Nc3 a6 d4 b5 Nf3 g6')
    path=infer_visible_opening(Observation.from_board(target))
    replay=chess.Board()
    for uci in path:replay.push_uci(uci)
    assert len(path)==10 and replay.board_fen()==target.board_fen()
    assert sum(board_after('e4 d5 exd5 Qxd5').occupied_co[color].bit_count() for color in chess.COLORS)==30


def test_divergent_opening_starts_fen_then_undo_restores_previous_pgn(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());time=[0.]
    manager._clock=lambda:time[0]
    old=board_after('d4 a6 c4 b5')
    fresh=board_after('e4 b5 d4 a6 Bd3 g6 Nf3 Bb7 O-O Bg7')
    manager.process(Observation.from_board(old));old_id=manager.current_id
    manager.process(Observation.from_board(fresh));time[0]=5.1
    manager.process(Observation.from_board(fresh));fresh_id=manager.current_id
    assert fresh_id!=old_id and len(store.games())==2
    assert manager.rec.initial_fen.split()[0]==fresh.board_fen()
    assert not manager.rec.verified and store.game(old_id)['status'].startswith('preserved')
    manager.set_game_mode('undo')
    assert manager.current_id==old_id
    assert store.game(fresh_id)['status'].startswith('preserved')
    store.close()


def test_skipped_opening_continuation_keeps_existing_game(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(infer_unseen_opening=True));time=[0.]
    manager._clock=lambda:time[0]
    old=board_after('e4 a6 d4 b5')
    target=board_after('e4 a6 d4 b5 Bd3 g6 Nf3 Bb7 O-O Bg7')
    manager.process(Observation.from_board(old));game_id=manager.current_id
    prefix=manager.rec.verified[:]
    manager.process(Observation.from_board(target));time[0]=1.1
    manager.process(Observation.from_board(target))
    assert manager.current_id==game_id and len(store.games())==1
    assert manager.rec.verified==prefix
    assert manager.last_observation.placement()==target.board_fen()
    store.close()


def test_changed_players_and_reset_clocks_split_even_matching_early_placement(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());time=[2.]
    manager._clock=lambda:time[0]
    opening=board_after('e4 a6')
    manager.process(Observation.from_board(opening));previous=manager.current_id
    manager.observe_context({'names':{'white':'EarlierWhite','black':'EarlierBlack'},'names_stable':True},'baseline')
    manager.observe_context({'names':{'white':'NewWhite','black':'NewBlack'},'names_stable':True},'new-names')
    manager.process(Observation.from_board(opening));time[0]=3.1
    manager.process(Observation.from_board(opening))
    assert manager.current_id!=previous
    assert manager.headers['White']=='NewWhite' and manager.headers['Black']=='NewBlack'
    assert manager.rec.initial_fen.split()[0]==opening.board_fen() and not manager.rec.verified
    store.close()
