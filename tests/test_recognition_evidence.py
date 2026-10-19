"""Continuity recovers weak classification faults without supplying move evidence."""
import io
from pathlib import Path
import chess
import chess.pgn
import cv2
import numpy as np
from chessstream.domain import LABELS,Observation,Settings
from chessstream.games import GameManager
from chessstream.reconstruction import Reconstructor
from chessstream.storage import Store


def misread(observation,square,wrong,alternative,confidence=.82):
    row=observation.probabilities[square]
    row[:]=.02/(len(LABELS)-2)
    row[LABELS.index(wrong)]=confidence
    row[LABELS.index(alternative)]=.98-confidence
    return observation


def test_legal_continuity_retains_disappearing_and_misclassified_pieces():
    for wrong in ('.','N','q'):
        for line in ('e4','e4 e5'):
            target=chess.Board()
            for san in line.split():target.push_san(san)
            raw=misread(Observation.from_board(target),chess.D1,wrong,'Q')
            original=raw.probabilities.copy()
            rec=Reconstructor(chess.Board())
            update=rec.observe(raw)
            assert update.ignored_squares==[chess.D1]
            assert rec.board.fen()==target.fen()
            assert rec.verified==[move.uci() for move in target.move_stack]
            np.testing.assert_array_equal(raw.probabilities,original)
    # A phantom extra piece is also ignored only where the legal board still
    # supports an unchanged empty square.
    raw=misread(Observation.from_board(target),chess.H3,'N','.')
    rec=Reconstructor(chess.Board());update=rec.observe(raw)
    assert update.ignored_squares==[chess.H3] and rec.board.fen()==target.fen()


def test_noise_cannot_prove_a_hidden_destination_or_overrule_strong_evidence():
    target=chess.Board();target.push_san('e4')
    cases=[misread(Observation.from_board(target),chess.E4,'B','.'),
           misread(Observation.from_board(target),chess.D1,'.','Q',.97)]
    too_many=Observation.from_board(target)
    for square,symbol in ((chess.D1,'Q'),(chess.A1,'R'),(chess.H1,'R')):
        misread(too_many,square,'.',symbol)
    cases.append(too_many)
    for raw in cases:
        rec=Reconstructor(chess.Board());update=rec.observe(raw)
        assert not update.ignored_squares and not rec.verified
        assert rec.board.fen()==chess.STARTING_FEN
    for fen,san,square,wrong,old in [
        ('r3k2r/ppp2ppp/2n5/3pp3/3PP3/2N5/PPP2PPP/R3K2R w KQkq - 0 10','O-O',chess.F1,'B','.'),
        ('7k/8/8/3pP3/8/8/8/7K w - d6 0 1','exd6',chess.D5,'N','p')]:
        source=chess.Board(fen);target=source.copy();target.push_san(san)
        rec=Reconstructor(source)
        update=rec.observe(misread(Observation.from_board(target),square,wrong,old))
        assert not update.ignored_squares and not rec.verified
        assert rec.board.fen()==source.fen()


def test_continuity_preserves_capture_castling_en_passant_promotion_and_pending_policy():
    cases=[(chess.STARTING_FEN,'e4 d5 exd5',chess.D1,'Q'),
           ('r3k2r/ppp2ppp/2n5/3pp3/3PP3/2N5/PPP2PPP/R3K2R w KQkq - 0 10','O-O',chess.A8,'r'),
           ('7k/8/8/3pP3/8/8/8/7K w - d6 0 1','exd6',chess.H8,'k'),
           ('7k/P7/8/8/8/8/8/7K w - - 0 1','a8=Q+',chess.H1,'K')]
    for fen,line,square,symbol in cases:
        source=chess.Board(fen);rec=Reconstructor(source);target=source.copy()
        for san in line.split():
            target.push_san(san)
            update=rec.observe(misread(Observation.from_board(target),square,'.',symbol))
        assert update.ignored_squares==[square] and rec.board.fen()==target.fen()
    rec=Reconstructor(chess.Board(),confirmation_plies=1)
    target=chess.Board();target.push_san('e4')
    for _ in range(3):rec.observe(misread(Observation.from_board(target),chess.D1,'.','Q'))
    assert rec.verified==[] and rec.branches[0].moves==('e2e4',)
    target.push_san('e5');rec.observe(misread(Observation.from_board(target),chess.D1,'.','Q'))
    assert rec.verified==['e2e4'] and rec.branches[0].moves==('e7e5',)


def test_recorder_logs_raw_fault_and_keeps_one_game_without_image_files(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings(confirm_on_reply=False))
    board=chess.Board();manager.process(Observation.from_board(board));game_id=manager.current_id
    board.push_san('e4');raw=misread(Observation.from_board(board),chess.D1,'.','Q')
    snapshot=manager.process(raw)
    assert snapshot['game_id']==game_id and len(store.games())==1
    assert snapshot['recognition_ignored_squares']==['d1']
    game=chess.pgn.read_game(io.StringIO(store.game(game_id)['pgn']))
    assert game.end().board().fen()==board.fen()
    assert 'uncertain unchanged square(s): d1' in store.game(game_id)['pgn']
    manager.process(raw)
    assert len(store.query("SELECT * FROM audit WHERE action='recognition continuity recovery'"))==1
    assert not list(store.images.rglob('*.png'))
    store.close()


def test_local_video_replay_saves_images_only_when_enabled(tmp_path,monkeypatch):
    from chessstream.replay import replay_video
    fixtures=Path(__file__).parent/'fixtures/real'
    frames=[cv2.imread(str(fixtures/f'chesscom-ruy-{ply:03d}.png')) for ply in range(3)]
    class Capture:
        def __init__(self,*args):self.frames=iter(image.copy() for image in frames for _ in range(2))
        def isOpened(self):return True
        def get(self,*args):return 6
        def read(self):
            image=next(self.frames,None)
            return image is not None,image
        def release(self):pass
    monkeypatch.setattr(cv2,'VideoCapture',Capture)
    pgns=[]
    for save in (False,True):
        root=tmp_path/str(save);root.mkdir()
        Settings(save_screenshots=save,adaptive_fps=6).save(root/'settings.json')
        h,w=frames[0].shape[:2]
        replay_video(Path('captured-video.avi'),root,region=f'0,0,{w},{h}',orientation='white')
        store=Store(root);games=store.games()
        assert len(games)==1
        assert bool(store.screenshots())==save
        game=chess.pgn.read_game(io.StringIO(games[0]['pgn']))
        pgns.append([move.uci() for move in game.mainline_moves()])
        store.close()
    assert pgns==[['e2e4'],['e2e4']]
