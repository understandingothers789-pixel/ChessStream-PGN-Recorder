"""Partial OCR names in Hikaru stream must never split one live game.

The recorder correctly detected a new game with A-TrainOutOfBreath versus
HomelanderNoMercy, then exported two additional nonstandard-FEN PGNs with the
same pieces. One fragment had White='th' — the visible tail of the real name.
"""
import chess
import chess.pgn
from chessstream.domain import Observation,Settings,utcnow
from chessstream.storage import Store
from chessstream.games import GameManager
from chessstream.lifecycle import clipped_ocr_name,probable_ocr_variant


FULL={'white':'A-TrainOutOfBreath','black':'HomelanderNoMercy'}


def board_after(text):
    b=chess.Board()
    for san in text.split():b.push_san(san)
    return b


def start_game(tmp_path):
    store=Store(tmp_path)
    manager=GameManager(store,Settings())
    manager._create(chess.Board(),utcnow())
    manager.correct_line('e4 c5 g3 Nc6 Bg2 g6 d3 Bg7 Nf3 e6 O-O Nge7')
    manager.headers.update(White=FULL['white'],Black=FULL['black'])
    manager.lifecycle.bind(manager)
    manager.persist()
    return store,manager


def context(manager,stamp,raw):
    manager.observe_context({'names':raw,'raw_names':raw,'names_stable':True,
                             'name_confidence':{c:.995 for c in raw},
                             'clocks':{'white':548,'black':514}},stamp)


def test_cropped_white_username_never_creates_second_fen_game(tmp_path):
    store,m=start_game(tmp_path)
    gid=m.current_id
    observed=m.rec.board.copy()
    observed.push_san('c3')
    for i in range(8):
        context(m,f'cropped-{i}',{'white':'th','black':FULL['black']})
        m.process(Observation.from_board(observed))
        assert m.current_id==gid
        assert len(store.games())==1
        assert m.headers['White']==FULL['white']
        assert m.lifecycle.changed_names(m,True)=={}
        assert m.lifecycle.raw_names.get('white')!='th'
    # Full OCR name returns and same game continues normally.
    context(m,'full-name-restored',FULL)
    m.process(Observation.from_board(observed))
    assert m.current_id==gid
    assert len(store.games())==1
    store.close()


def test_cropped_black_name_with_white_missing_is_not_new_opponent(tmp_path):
    store,m=start_game(tmp_path)
    gid=m.current_id
    for i in range(7):
        context(m,f'black-tail-{i}',{'black':'anderNoMercy'})
        m.process(Observation.from_board(m.rec.board))
        assert m.current_id==gid
        assert not m.lifecycle.changed_names(m,True)
    assert m.headers['Black']==FULL['black']
    assert len(store.games())==1
    store.close()


def test_single_confirmed_player_protects_unlinked_middlegame_when_second_missing(tmp_path):
    store,m=start_game(tmp_path)
    gid=m.current_id
    unknown=board_after('d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3')
    for i in range(9):
        context(m,f'only-white-{i}',{'white':FULL['white']})
        m.process(Observation.from_board(unknown))
        assert m.current_id==gid
        assert len(store.games())==1
    assert m.rec.board.board_fen()!=unknown.board_fen()
    store.close()


def test_real_name_change_is_not_mistaken_for_clipped_ocr():
    assert clipped_ocr_name('th','A-TrainOutOfBreath')
    assert clipped_ocr_name('anderNoMercy','HomelanderNoMercy')
    assert clipped_ocr_name('elanderNoMercy','HomelanderNoMercy')
    assert not clipped_ocr_name('A-TrainOutOfBreath','A-TrainOutOfBreath')
    assert not clipped_ocr_name('GenuineOpponent','HomelanderNoMercy')
    assert not clipped_ocr_name('OpponentB','OpponentA')
