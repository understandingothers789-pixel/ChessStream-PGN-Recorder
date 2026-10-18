"""Held-out positions captured from the actual Chess.com and Lichess browser UIs."""
from pathlib import Path
import json
import io
import chess
import chess.pgn
import cv2
import pytest
from chessstream.domain import Settings
from chessstream.vision import ScreenshotRecognizer,choose_orientation
from chessstream.games import GameManager
from chessstream.storage import Store

REAL=Path(__file__).parent/'fixtures/real'
MANIFEST=json.loads((REAL/'manifest.json').read_text())


@pytest.mark.parametrize('game',MANIFEST['games'],ids=lambda g:g['id'])
def test_actual_browser_sequences(game,tmp_path):
    rec=ScreenshotRecognizer()
    store=Store(tmp_path/'recordings');manager=GameManager(store,Settings());expected=[];ground=chess.Board()
    # Every second real frame exercises multiple moves between observations.
    indices=sorted(set([0]+list(range(2,len(game['frames']),2))+[len(game['frames'])-1]))
    for f in game['frames']:
        if f['san']:
            move=ground.parse_san(f['san']);expected.append(move);ground.push(move)
        if f['ply'] not in indices:continue
        obs=rec.recognize(cv2.imread(str(REAL/f['file'])))
        obs=choose_orientation(obs,manager.rec.board if manager.rec else None)
        assert obs.placement()==chess.Board(f['fen']).board_fen()
        manager.process(obs)
    assert manager.rec.verified==[m.uci() for m in expected[:-1]]
    assert manager.snapshot()['provisional']
    manager.choose(0)  # One explicit confirmation for the final move, not every move.
    assert manager.rec.verified==[m.uci() for m in expected]
    pgn=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert not pgn.errors
    assert list(pgn.mainline_moves())==expected
    store.close()


def test_actual_back_to_back_games_and_image_only_deletion(tmp_path):
    store=Store(tmp_path/'recordings');manager=GameManager(store,Settings());recognizer=ScreenshotRecognizer()
    for game in MANIFEST['games'][:3]:
        for f in game['frames']:
            image=cv2.imread(str(REAL/f['file']));obs=recognizer.recognize(image)
            obs=choose_orientation(obs,manager.rec.board if manager.rec else None);manager.process(obs)
            if f['ply']==1:
                store.save_screenshot(manager.session_id,manager.current_id,image,obs.timestamp,obs.placement(),obs.confidence,f['ply'])
        manager.choose(0)  # Review the final mate before moving to the next test game.
    games=store.games()
    assert len(games)==3
    assert sorted(g['plies'] for g in games)==[4,7,33]
    assert all(g['status']=='complete' for g in games)
    assert store.delete_screenshots({'session_id':manager.session_id})['count']==3
    assert len(store.games())==3
    assert len(list((store.root/'pgn').glob('*.pgn')))==3
    store.close()
