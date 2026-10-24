"""Observed intermediate boards separate gaps; unseen excursions stay pending."""
import io
import json
from pathlib import Path

import chess
import chess.pgn
import cv2

from chessstream.domain import Observation,Settings
from chessstream.games import GameManager
from chessstream.reconstruction import Reconstructor
from chessstream.storage import Store
from chessstream.vision import ScreenshotRecognizer,choose_orientation


def played(line):
    board=chess.Board()
    for san in line.split():board.push_san(san)
    return board


def test_observed_bishop_then_two_ply_capture_gap_survives_state_roundtrip():
    source=played('e4 e5 Nf3 d6 d4')
    rec=Reconstructor(source,confirmation_plies=1)
    target=source.copy();target.push_san('Bg4')
    rec.observe(Observation.from_board(target))
    rec=Reconstructor.restore(rec.serialize())
    assert rec.branches[0].requires_confirmation is False
    for san in ('dxe5','Bxf3'):target.push_san(san)
    rec.observe(Observation.from_board(target))
    assert rec.verified==['c8g4','d4e5']
    assert not rec.gap_requires_confirmation
    assert rec.branches[0].moves==('g4f3',)
    rec=Reconstructor.restore(rec.serialize())
    target.push_san('Qxf3');rec.observe(Observation.from_board(target))
    assert rec.verified==['c8g4','d4e5','g4f3']
    assert not rec.gap_requires_confirmation


def test_entirely_unseen_repeated_bishop_still_needs_confirmation_after_restart():
    source=played('e4 e5 Nf3 d6 d4');target=source.copy()
    for san in ('Bg4','dxe5','Bxf3'):target.push_san(san)
    rec=Reconstructor(source,confirmation_plies=1)
    rec.observe(Observation.from_board(target))
    assert rec.gap_requires_confirmation and not rec.verified
    serialized=rec.serialize()
    for branch in serialized['branches']:branch.pop('requires_confirmation')
    # Older saved states lack per-gap evidence. Preserve their conservative
    # confirmation policy rather than manufacturing witnessed landmarks.
    rec=Reconstructor.restore(serialized)
    target.push_san('Qxf3');rec.observe(Observation.from_board(target))
    assert rec.gap_requires_confirmation and not rec.verified


def test_real_opera_images_with_every_other_frame_missing_finish_in_one_pgn(tmp_path):
    root=Path(__file__).parent/'fixtures/real'
    game=next(game for game in json.loads((root/'manifest.json').read_text())['games']
              if game['id']=='lichess-opera')
    indices=sorted({0,*range(2,len(game['frames']),2),len(game['frames'])-1})
    store=Store(tmp_path);manager=GameManager(store,Settings());model=ScreenshotRecognizer()
    for index in indices:
        observed=model.recognize(cv2.imread(str(root/game['frames'][index]['file'])))
        observed=choose_orientation(observed,manager.rec.board if manager.rec else None)
        manager.process(observed)
    expected=played(' '.join(frame['san'] for frame in game['frames'] if frame['san']))
    assert len(store.games())==1 and not manager.rec.gap_requires_confirmation
    assert manager.rec.verified==[move.uci() for move in expected.move_stack[:-1]]
    manager.choose(0)  # Existing final-move confirmation policy.
    exported=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert not exported.errors and list(exported.mainline_moves())==expected.move_stack
    assert exported.end().board().fen()==expected.fen()
    store.close()
