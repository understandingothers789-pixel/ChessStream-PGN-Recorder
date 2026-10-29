"""Realistic board-relative username OCR fallback tests.

Synthetic OCR observations isolate the text geometry from the neural model.
The existing retained native Chess.com screenshot test covers model accuracy.
"""
import numpy as np
import pytest

from chessstream.context_capture import context_region
from chessstream.domain import Region
from chessstream.results import (
    ContextStabilizer, EndMessageDetector, extract_context, player_info_bands,
)

BOARD = (300, 220, 700, 700)
HEIGHT, WIDTH = 1130, 1420


class CroppedNameReader:
    def __init__(self, orientation='white', top_name='pablo6367',
                 bottom_name='ohnomyrosen', skip_top=False):
        self.calls = []
        self.orientation=orientation
        self.top_name=top_name
        self.bottom_name=bottom_name
        self.skip_top=skip_top

    def read(self, image):
        h,w=image.shape[:2]
        self.calls.append((h,w))
        if h==HEIGHT:
            # High-resolution stream OCR misses tiny names but sees clocks and
            # occasionally a false version/title in an adjacent overlay.
            lines=[
                ('9:12',.98,(945,143,994,165)),
                ('7:04',.98,(945,965,994,985)),
                ('V1.6.23',.99,(380,145,472,164)),
                ('chess speedrun',.99,(380,962,555,984)),
            ]
            if self.skip_top:
                lines.append((self.top_name,.98,(362,145,470,164)))
            return lines
        if h==700:
            return []  # Board-only result scan cannot see player nameplates.
        # Each player band is tagged by its different pixel color.
        if image[0,0,0]==40:
            return [(self.top_name,.97,(148,70,285,92))]
        if image[0,0,0]==80:
            return [(self.bottom_name,.96,(148,55,318,77))]
        return []


def frame():
    image=np.zeros((HEIGHT,WIDTH,3),dtype=np.uint8)
    image[:220,:,0]=40
    image[900:,:,0]=80
    return image


@pytest.mark.parametrize('orientation',('white','black'))
def test_native_player_bands_recover_both_names_with_far_right_clocks(orientation):
    reader=CroppedNameReader(orientation)
    detector=EndMessageDetector(reader=reader,clock=lambda:10.)
    assert detector.scan(frame(),board_rect=BOARD,orientation=orientation) is None
    result=extract_context(detector.last_lines,BOARD,orientation)
    expected = {'black':'pablo6367','white':'ohnomyrosen'} if orientation=='white' else {'white':'pablo6367','black':'ohnomyrosen'}
    assert result['names']==expected
    assert result['clocks']==({'black':552,'white':424} if orientation=='white' else {'white':552,'black':424})
    assert reader.calls[0]==(HEIGHT,WIDTH)
    assert (700,700) in reader.calls
    assert len(reader.calls)==4   # whole image, board, top, bottom
    stabilizer=ContextStabilizer()
    assert not stabilizer.observe(result)['names']
    assert not stabilizer.observe(result)['names']
    assert stabilizer.observe(result)['names']==expected


def test_only_missing_name_gets_extra_ocr_and_unrelated_text_is_filtered():
    reader=CroppedNameReader(skip_top=True)
    detector=EndMessageDetector(reader=reader,clock=lambda:10.)
    detector.scan(frame(),board_rect=BOARD,orientation='white')
    result=extract_context(detector.last_lines,BOARD,'white')
    assert result['names']=={'black':'pablo6367','white':'ohnomyrosen'}
    assert len(reader.calls)==3  # no unnecessary top band


def test_context_expands_more_vertically_and_never_leaves_desktop():
    source=Region(300,220,700,700)
    desktop={'left':0,'top':0,'width':1420,'height':1130}
    region,relative=context_region(source,(0,0,700,700),desktop,18)
    assert relative[2:]==(700,700)
    assert relative[1]>relative[0] # vertical padding > horizontal
    assert region.top>=0 and region.left>=0
    assert region.top+region.height<=desktop['height']


def test_info_bands_clip_safely_with_top_edge_board():
    bands=player_info_bands((850,1000,3),(120,3,760,760))
    assert all(0<=x0<x1<=1000 and 0<=y0<y1<=850
               for x0,y0,x1,y1 in bands.values())
