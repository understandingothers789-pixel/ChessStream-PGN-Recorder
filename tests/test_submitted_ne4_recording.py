"""Submitted machine-exported PGN plus log transitions; not video ground truth."""
import io
from pathlib import Path
import chess
import chess.pgn
import pytest
from chessstream.domain import Observation,Settings,Region
from chessstream.games import GameManager
from chessstream.capture import RecordingWorker
from chessstream.storage import Store

FIXTURE=Path(__file__).parent/'fixtures/recordings/submitted-ne4-stall.pgn'
END='2r1b1k1/pp3pbp/2n1p1p1/8/4N3/P3PN1Q/1qBR1PPP/6K1'


def test_submitted_prefix_establishes_black_turn_and_last_clock():
    game=chess.pgn.read_game(io.StringIO(FIXTURE.read_text()))
    assert not game.errors and len(list(game.mainline_moves()))==43
    assert game.board().fen()==chess.STARTING_FEN
    assert game.end().board().board_fen()==END and game.end().board().turn==chess.BLACK
    assert game.end().san()=='Ne4' and game.end().clock()==191


@pytest.mark.parametrize('populated',[False,True])
def test_full_submitted_line_records_identically_with_and_without_library(tmp_path,populated):
    store=Store(tmp_path)
    if populated:
        importer=GameManager(store,Settings());importer.import_pgn(FIXTURE)
        archived=store.games()[0];original=archived['pgn']
    m=GameManager(store,Settings());tick=[100.];m._clock=lambda:tick[0]
    m.lifecycle.names={'white':'WhitePlayer','black':'BlackPlayer'};m.lifecycle.raw_names=dict(m.lifecycle.names)
    worker=RecordingWorker(m,Region(0,0,500,500),preview_only=True)
    game=chess.pgn.read_game(io.StringIO(FIXTURE.read_text()));board=game.board()
    for ply,move in enumerate(game.mainline_moves(),1):
        board.push(move)
        if ply<3:continue
        for _ in range(2):
            tick[0]+=.6;worker.process_observation(Observation.from_board(board),2)
    assert m.rec.verified==[move.uci() for move in game.mainline_moves()]
    assert m.rec.board.fen()==board.fen() and m.rec.board.turn==chess.BLACK
    saved=chess.pgn.read_game(io.StringIO(store.game(m.current_id)['pgn']))
    assert not saved.errors and saved.end().board().fen()==board.fen()
    if populated:
        assert m.current_id!=archived['id'] and store.game(archived['id'])['pgn']==original
    m.cancel_background_recovery();m.cancel_saved_join();store.close()


def test_premove_conflict_does_not_invent_queen_moves_and_correct_frame_resumes(tmp_path):
    store=Store(tmp_path);m=GameManager(store,Settings(confirm_on_reply=False))
    m.import_pgn(FIXTURE);m.recover(store.games()[0]['id'],persist=False)
    prefix=m.rec.verified[:];board=m.rec.board.copy();tick=[100.];m._clock=lambda:tick[0]
    # Log's next view: White's Ng5 while the stored position has Black to move.
    premove=board.copy();premove.turn=chess.WHITE;premove.push_uci('e4g5')
    for _ in range(3):
        tick[0]+=1;m.process(Observation.from_board(premove))
        assert m.rec.verified==prefix and m.premove_state
    conflict=chess.Board('2r1b1k1/pp3pbp/2n1p1p1/6N1/8/P3PN1Q/2BR1PPP/2q3K1 w - - 0 1')
    tick[0]+=1;m.process(Observation.from_board(conflict))
    assert m.rec.verified==prefix
    # Counterfactual recovery check: if the queued knight returns to e4 and
    # Qc1+ is witnessed, accept that real move, not a fabricated queen detour.
    for san in ('Qc1+','Bd1','Rd8','Neg5'):
        board.push_san(san);tick[0]+=1;m.process(Observation.from_board(board))
    assert m.rec.verified==prefix+['b2c1','c2d1','c8d8','e4g5']
    m.cancel_background_recovery();m.cancel_saved_join();store.close()
