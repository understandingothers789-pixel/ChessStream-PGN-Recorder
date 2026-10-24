"""Regression: false draws on an unrelated stream/tool window must not
terminate an active six-ply ChessStream game (October 20 live reproduction).
"""
import numpy as np
import pytest
from chessstream.results import EndMessageDetector,parse_end_message,_result_line_is_an_announcement


@pytest.mark.parametrize("text",[
    "one-line variations easiert scan.he database explorewill keepits win/draw/lossars",
    "win/draw/loss",
    "Wins / Draw / Losses",
    "This database displays the draw rate by rating",
    "Draw 48 percent | Win 52 percent",
    "Possible game ended from the search results window",
    "There are many drawn chess games in this playlist",
])
def test_incidental_result_vocabulary_must_not_end_live_game(text):
    assert not _result_line_is_an_announcement(text)
    assert parse_end_message([(text,.995,(500,450,800,495))],player_color='white') is None


@pytest.mark.parametrize("text,expected",[
    ("Draw","1/2-1/2"),
    ("Game drawn","1/2-1/2"),
    ("1/2-1/2","1/2-1/2"),
    ("You Won!","1-0"),
    ("You Lost by resignation","0-1"),
    ("Black won by checkmate","0-1"),
])
def test_actual_announcements_remain_supported(text,expected):
    assert _result_line_is_an_announcement(text)
    result=parse_end_message([(text,.95,(450,360,700,402))],player_color="white")
    assert result is not None and result.result==expected


class ScreenReader:
    def __init__(self,title):self.title=title
    def read(self,image):
        # The whole-screen OCR sees a sidebar drawn 200 px away from the
        # board. Cropping the 400x400 board returns no message.
        if image.shape[:2]==(900,1300):
            return [(self.title,.99,(40,450,230,490))]
        return []


def test_result_from_unrelated_sidebar_cannot_end_a_game_after_one_second():
    img=np.zeros((900,1300,3),dtype=np.uint8)
    now=[0.]
    reader=ScreenReader("Draw")
    detector=EndMessageDetector(reader=reader,clock=lambda:now[0])
    assert detector.scan(img,'white',(380,250,400,400)) is None
    now[0]=2.
    assert detector.scan(img,'white',(380,250,400,400)) is None


def test_result_without_detected_board_cannot_end_a_game():
    img=np.zeros((900,1300,3),dtype=np.uint8)
    now=[0.]
    reader=ScreenReader("Draw")
    detector=EndMessageDetector(reader=reader,clock=lambda:now[0])
    assert detector.scan(img,'white',None) is None
    now[0]=2.
    assert detector.scan(img,'white',None) is None
