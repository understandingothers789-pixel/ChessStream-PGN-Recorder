from pathlib import Path
import io
import cv2
import chess
import chess.pgn
from chessstream.replay import replay_video
from chessstream.storage import Store
from chessstream.games import GameManager
from chessstream.domain import Settings


def test_compressed_prerecorded_video(tmp_path):
    real=Path(__file__).parent/'fixtures/real'
    path=tmp_path/'test-video.avi'
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),6,(480,480))
    assert writer.isOpened()
    for ply in range(5):
        image=cv2.resize(cv2.imread(str(real/f'lichess-fools-{ply:03d}.png')),(480,480))
        for _ in range(3):writer.write(image)
    writer.release()
    root=tmp_path/'recording';replay_video(path,root,'0,0,480,480',1,'white')
    store=Store(root);games=store.games();assert len(games)==1
    game=chess.pgn.read_game(io.StringIO(games[0]['pgn']))
    b=chess.Board();expected=[]
    for san in 'f3 e5 g4 Qh4#'.split():
        move=b.parse_san(san);expected.append(move);b.push(move)
    assert list(game.mainline_moves())==expected[:-1]
    assert game.headers['Result']=='*'
    manager=GameManager(store,Settings());manager.recover(games[0]['id']);manager.choose(0)
    game=chess.pgn.read_game(io.StringIO(store.game(games[0]['id'])['pgn']))
    assert list(game.mainline_moves())==expected
    assert game.headers['Result']=='0-1'
    store.close()
