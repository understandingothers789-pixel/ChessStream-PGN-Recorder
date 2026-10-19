"""Premove/result correctness and bounded asynchronous evidence recovery."""
import io
import chess
import chess.pgn
import numpy as np
from chessstream.domain import Settings,Observation,utcnow
from chessstream.storage import Store
from chessstream.games import GameManager
from chessstream.results import EndMessage,EndMessageDetector,parse_end_message
from chessstream.recovery import RecentFrames,recover_gap

SOURCE='rn2qrk1/1bpp1p1p/p3pBpQ/1p2P3/2PP4/5P2/PP3P1P/R5K1 b - - 0 22'


def make_manager(path):
    store=Store(path);manager=GameManager(store,Settings())
    board=chess.Board(SOURCE);manager._create(board.copy(),utcnow())
    manager.player_color='white'
    return store,manager,board


def test_qg7_premove_never_invents_black_waiting_moves_and_resignation_keeps_qh6(tmp_path):
    store,manager,board=make_manager(tmp_path)
    preview=board.copy();preview.turn=chess.WHITE;preview.push_san('Qg7#')
    now=[0.];manager._clock=lambda:now[0]
    for now[0] in (0.,.5,2.,10.):
        snapshot=manager.process(Observation.from_board(preview))
        assert manager.premove_state and manager.rec.verified==[]
        assert snapshot['result']=='*' and snapshot['preview_fen'].split()[0]==preview.board_fen()
    gid=manager.current_id;manager.recover(gid)
    assert manager.premove_state
    message=EndMessage('1-0','resignation','You Won! | by resignation',.98)
    manager.declare_end(message,Observation.from_board(board))
    manager.process(Observation.from_board(board))
    game=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
    assert game.headers['Result']=='1-0' and game.headers['Termination']=='resignation'
    assert not list(game.mainline_moves()) and game.end().board().board_fen()==board.board_fen()
    assert 'Qg7#' not in store.game(gid)['pgn']
    store.close()


def test_premove_becomes_a_played_mate_only_after_observed_opponent_move(tmp_path):
    store,manager,board=make_manager(tmp_path)
    preview=board.copy();preview.turn=chess.WHITE;preview.push_san('Qg7#')
    manager.process(Observation.from_board(preview));assert manager.premove_state
    board.push_san('b4');board.push_san('Qg7#')
    now=[0.];manager._clock=lambda:now[0];manager.reset_settling()
    manager.process(Observation.from_board(board));now[0]=.5
    manager.process(Observation.from_board(board))
    assert manager.headers['Result']=='1-0'
    game=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert [node.san() for node in game.mainline()]==['b4','Qg7#']
    assert game.end().board().board_fen()==board.board_fen() and not manager.premove_state
    assert game.headers['Result']=='1-0'
    store.close()


def test_result_ocr_board_retry_maps_boxes_and_is_not_blocked_by_player_name_ocr(tmp_path):
    class Reader:
        def __init__(self):self.shapes=[]
        def read(self,image):
            self.shapes.append(image.shape[:2])
            if image.shape[1]>600:return []
            return [('You Won!',.99,(100,160,210,190)),('by resignation',.97,(100,190,240,215))]
    reader=Reader();now=[0.];detector=EndMessageDetector(reader,lambda:now[0])
    image=np.zeros((900,1500,3),np.uint8);rect=(800,100,500,500)
    assert detector.scan(image,'white',rect) is None
    now[0]=1.;message=detector.scan(image,'white',rect)
    assert message.result=='1-0' and message.reason=='resignation'
    assert len(reader.shapes)==2 and any(line[2][0]>=800 for line in detector.last_lines)
    assert parse_end_message([('by resignation',.99)]).reason=='resignation'
    assert parse_end_message([('Resign',.99)]) is None  # ordinary action button
    from chessstream.capture import RecordingWorker,Region
    store,manager,board=make_manager(tmp_path)
    manager.pending_identity={'white':'temporary OCR spelling'}
    manager.settings.read_context=False
    worker=RecordingWorker(manager,Region(0,0,500,500))
    worker._text_detector=detector;worker._context_game=manager.current_id
    now[0]=2.;worker.scan_context(image,rect,Observation.from_board(board))
    assert manager.terminal_message['reason']=='resignation' and manager.headers['Result']=='1-0'
    store.close()


def test_recent_frames_are_bounded_deduplicated_and_useful_in_search_without_disk_files(tmp_path):
    ring=RecentFrames(12);board=chess.Board();image=np.zeros((900,900,3),np.uint8)
    for i in range(20):
        image[:]=i;ring.add(image,Observation.from_board(board));ring.mark('game',True)
    assert len(ring.frames)==12 and max(ring.frames[-1]['image'].shape[:2])==768
    ring.add(image,Observation.from_board(board));assert len(ring.frames)==12
    assert ring.frames[-1]['comparisons']==2 and not list(tmp_path.iterdir())
    from chessstream.reconstruction import Reconstructor
    source=chess.Board();middle=source.copy();middle.push_san('Nc3');middle.push_san('Nc6')
    final=middle.copy();final.push_san('Nf3');final.push_san('Nf6')
    state=Reconstructor(source).serialize()
    result=recover_gap([state],Observation.from_board(final),6,60000,350,
        [Observation.from_board(source),Observation.from_board(middle)])
    assert result
    rec=Reconstructor.restore(result[1])
    assert rec.verified[:2]==['b1c3','b8c6'] and rec.board.fen()==final.fen()


def test_background_results_apply_only_to_unchanged_game_and_observation(tmp_path):
    for stale in (False,True):
        store=Store(tmp_path/str(stale));manager=GameManager(store,Settings(confirm_on_reply=False))
        source=chess.Board();manager.process(Observation.from_board(source));source.push_san('e4')
        manager.process(Observation.from_board(source))
        target=source.copy();target.push_san('e5');target.push_san('Nf3')
        obs=Observation.from_board(target);manager.rec.status='unmatched position'
        assert manager.background_recovery(obs)
        manager._recovery_future.result(timeout=3)
        if stale:target.push_san('Nc6');obs=Observation.from_board(target)
        manager.background_recovery(obs)
        assert len(manager.rec.verified)==(1 if stale else 3)
        if not stale:assert manager.rec.board.fen()==target.fen()
        manager.cancel_background_recovery();store.close()


def test_resignation_can_confirm_real_pending_qh6_but_not_following_qg7_premove(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings())
    actual=chess.Board(SOURCE)
    initial=actual.copy();initial.remove_piece_at(chess.H6)
    initial.set_piece_at(chess.D2,chess.Piece(chess.QUEEN,chess.WHITE));initial.turn=chess.WHITE
    manager._create(initial,utcnow());manager.process(Observation.from_board(actual))
    assert manager.snapshot()['pending_moves']==['Qh6']
    preview=actual.copy();preview.turn=chess.WHITE;preview.push_san('Qg7#')
    manager.process(Observation.from_board(preview));assert manager.premove_state
    manager.declare_end(EndMessage('1-0','resignation','You Won! by resignation',.99),Observation.from_board(actual))
    game=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert [node.san() for node in game.mainline()]==['Qh6']
    assert game.headers['Termination']=='resignation' and game.end().board().board_fen()==actual.board_fen()
    store.close()
