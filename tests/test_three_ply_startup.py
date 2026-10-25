"""Startup from the reported d4 Nf6 c4 placement, with explicit inference."""
import io
import chess
import chess.pgn
import pytest
from chessstream.domain import Settings,Observation,Region,utcnow
from chessstream.games import GameManager
from chessstream.capture import RecordingWorker
from chessstream.storage import Store


def played(line):
    b=chess.Board()
    for san in line.split():b.push_san(san)
    return b


@pytest.mark.parametrize('orientation',['white','black'])
def test_three_ply_startup_recovers_opening_and_black_turn(tmp_path,orientation):
    store=Store(tmp_path);m=GameManager(store,Settings());now=[100.];m._clock=lambda:now[0]
    w=RecordingWorker(m,Region(0,0,500,500),preview_only=True)
    board=played('d4 Nf6 c4');obs=Observation.from_board(board);obs.orientation=orientation
    snapshot=w.process_observation(obs,2)
    assert not w.preview_only and snapshot['recording_started_automatically']
    assert m.rec.initial_fen==chess.STARTING_FEN
    assert not chess.Board(snapshot['preview_fen']).turn
    now[0]+=1;w.process_observation(obs,2)
    game=chess.pgn.read_game(io.StringIO(store.game(m.current_id)['pgn']))
    assert not game.errors and 'FEN' not in game.headers
    assert [n.san() for n in game.mainline()]==['d4','Nf6','c4']
    assert game.end().board().fen()==board.fen()
    assert len(game.variations)==2
    alternative=game.variations[1];line=[alternative.san()]
    while alternative.variations:alternative=alternative.variations[0];line.append(alternative.san())
    assert line==['c4','Nf6','d4'] and 'inferred' in alternative.comment
    gid=m.current_id
    for san in ('e6','Bg5','d5','Nc3','Be7'):
        board.push_san(san);now[0]+=1
        observed=Observation.from_board(board);observed.orientation=orientation
        w.process_observation(observed,2);now[0]+=1;w.process_observation(observed,2)
    assert m.current_id==gid and len(store.games())==1
    assert m.rec.board.fen()==board.fen()
    m.cancel_background_recovery();m.cancel_saved_join();store.close()


def test_old_app_fen_prefix_can_be_backfilled_with_continuation(tmp_path):
    store=Store(tmp_path);m=GameManager(store,Settings(confirm_on_reply=False))
    root=played('d4 Nf6 c4');root.castling_rights=0
    m._create(root,utcnow(),note='Recording began midgame. Earlier moves are unavailable.')
    m.correct_line('e6 Bg5 d5');gid=m.current_id
    assert m._backfill_opening_prefix()
    m.persist();game=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
    assert not game.errors and 'FEN' not in game.headers
    assert [n.san() for n in game.mainline()]==['d4','Nf6','c4','e6','Bg5','d5']
    assert len(game.variations)==2 and m.rec.board.turn==chess.WHITE
    store.close()


def test_ambiguous_general_gap_policy_is_unchanged(tmp_path):
    store=Store(tmp_path);m=GameManager(store,Settings())
    obs=Observation.from_board(played('d4 Nf6 c4'))
    assert not m._infer_short_opening(obs,max_plies=3)  # Only startup gets the explicitly inferred order.
    assert not m._infer_short_opening(Observation.from_board(played('Nf3 Nf6 Nc3 Nc6')),max_plies=4,allow_initial_transposition=True)
    store.close()
