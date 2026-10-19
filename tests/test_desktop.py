"""One real-image check per recognizer and one useful desktop integration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import chess
import cv2
from chessstream.domain import Region,Observation
from chessstream.vision import BoardDetector,ScreenshotRecognizer,choose_orientation
from chessstream.results import LocalTextReader,extract_context,parse_end_message

FIXTURES=Path(__file__).parent/'fixtures'


def test_actual_board_page_detection_piece_recognition_and_board_flip():
    recognizer=ScreenshotRecognizer()
    for filename in ['results/native-bot-start.png','real/lichess-start-page.png']:
        image=cv2.imread(str(FIXTURES/filename));rect,_=BoardDetector().detect(image)
        assert rect is not None
        x,y,w,h=rect;board=image[y:y+h,x:x+w]
        assert recognizer.recognize(board).placement()==chess.Board().board_fen()
    # This retained browser capture actually has Black at the bottom; the
    # pieces themselves remain upright, as they do during a real board flip.
    flipped=recognizer.recognize(cv2.imread(str(FIXTURES/'themes/chesscom-ocean-00.png')))
    assert choose_orientation(flipped,chess.Board()).placement()==chess.Board().board_fen()


def test_native_ocr_still_reads_names_clocks_and_game_end():
    image=cv2.imread(str(FIXTURES/'results/native-bot-resigned.png'))
    lines=LocalTextReader().read(image)
    context=extract_context(lines,(108,66,568,568),'white')
    assert context['names']=={'black':'Martinfoot','white':'Guest'}
    assert all(500<=time<=600 for time in context['clocks'].values())
    message=parse_end_message(lines,'white',context['names'])
    assert message and message.result=='0-1'


def test_desktop_autoselection_provisional_board_and_library_actions(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    import chessstream.gui as gui
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui,'windows',lambda:[(1,'Music - YouTube - Brave'),(2,'Hikaru rapid speedrun - YouTube - Brave')])
    monkeypatch.setattr(gui,'window_client',lambda hwnd:Region(0,0,1200,800,window=hwnd))
    window=gui.MainWindow(tmp_path);assert window.region.window==2
    board=chess.Board();window.manager.process(Observation.from_board(board));board.push_san('e4')
    window.on_update(window.manager.process(Observation.from_board(board)))
    assert window.live_board.fen==board.fen() and window.snapshot['pending_moves']==['e4']
    assert '1. e4' not in window.store.game(window.manager.current_id)['pgn']
    window.manager.force_new();window.navigate(1);window.game_table.selectAll()
    actions={action.text():action for action in window.game_row_menu().actions()}
    assert 'Delete saved PGN file(s)…' in actions
    assert actions['Join selected recordings…'].isEnabled()
    window.close();window.deleteLater();app.processEvents()
