from pathlib import Path
import chess
import cv2
import pytest
from chessstream.vision import TemplateRecognizer,BoardDetector,choose_orientation
from chessstream.domain import board_labels

REAL=Path(__file__).parent/'fixtures/real'


def test_browser_captured_lichess_start():
    path=REAL/'lichess-start.png'
    assert path.exists(), 'Real browser-captured fixture is required'
    obs=TemplateRecognizer().recognize(cv2.imread(str(path)))
    assert obs.placement()==chess.Board().board_fen()
    assert obs.confidence>.90


def test_board_localization_on_real_full_page():
    image=cv2.imread(str(REAL/'lichess-start-page.png'))
    rect,score=BoardDetector().detect(image)
    assert rect is not None
    x,y,w,h=rect
    assert abs(x-358)<6 and abs(y-65)<6
    assert abs(w-712)<10 and abs(h-712)<10
    assert score>.6


def test_actual_mss_window_capture_at_different_grid_size():
    image=cv2.imread(str(REAL/'mss-headed-lichess-start.png'))
    rect,score=BoardDetector().detect(image)
    assert rect is not None
    x,y,w,h=rect
    obs=TemplateRecognizer().recognize(image[y:y+h,x:x+w])
    assert obs.placement()==chess.Board().board_fen()


@pytest.mark.parametrize('name',['lichess-legal-dots.png','lichess-arrow.png'])
def test_actual_ui_obstructions_do_not_fabricate_moves(name):
    from chessstream.reconstruction import Reconstructor
    rec=TemplateRecognizer();r=Reconstructor(chess.Board())
    r.observe(rec.recognize(cv2.imread(str(REAL/name))))
    assert not r.verified
    # The next clear image can recover without discarding the original game.
    r.observe(rec.recognize(cv2.imread(str(REAL/'lichess-fools-001.png'))))
    assert r.verified==['f2f3']
