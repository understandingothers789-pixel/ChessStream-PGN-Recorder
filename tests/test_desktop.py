"""One real-image check per recognizer and one useful desktop integration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import chess
import cv2
from chessstream.domain import Region,Observation
from chessstream.vision import BoardDetector,ScreenshotRecognizer,choose_orientation
from chessstream.results import LocalTextReader,extract_context,parse_end_message
from chessstream.capture import rank_capture_windows,rank_youtube_windows

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
    reader=LocalTextReader();lines=reader.read(image)
    context=extract_context(lines,(108,66,568,568),'white')
    assert context['names']=={'black':'Martinfoot','white':'Guest'}
    assert all(500<=time<=600 for time in context['clocks'].values())
    message=parse_end_message(lines,'white',context['names'])
    assert message and message.result=='0-1'
    # Exercise the native board-focused retry with the actual offline OCR model.
    from chessstream.results import EndMessageDetector
    class BoardReader:
        def read(self,tile):
            return [] if tile.shape==image.shape else reader.read(tile)
    now=[0.];detector=EndMessageDetector(BoardReader(),lambda:now[0])
    assert detector.scan(image,'white',(108,66,568,568),context['names']) is None
    now[0]=1.;end=detector.scan(image,'white',(108,66,568,568),context['names'])
    assert end and end.result=='0-1' and end.reason=='resignation'


def test_desktop_autoselection_provisional_board_and_library_actions(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    import chessstream.gui as gui
    app=QApplication.instance() or QApplication([])
    options=[(1,'ChessStream-PGN-Recorder-main - File Explorer'),
             (2,'understandingothers789-pixel/ChessStream-PGN-Recorder - Brave'),
             (3,'Music - YouTube - Brave'),
             (4,'MASTER SLOWKARU RAPID EDUCATIONAL SPEEDRUN 1 - YouTube - Brave')]
    monkeypatch.setattr(gui,'windows',lambda:options)
    monkeypatch.setattr(gui,'window_client',lambda hwnd:Region(0,0,1200,800,window=hwnd))
    monkeypatch.setattr(gui.MainWindow,'start_preview',lambda self:setattr(self,'preview_started',True))
    window=gui.MainWindow(tmp_path);assert window.region.window==4
    assert window.preview_started
    assert window.settings.save_screenshots is False
    # The common correction actions operate inline, without the old SAN dialog.
    actions=[]
    with monkeypatch.context() as action_patch:
        action_patch.setattr(window.manager,'repair_current',lambda:actions.append('repair'))
        action_patch.setattr(window.manager,'join_previous_recording',lambda:actions.append('join'))
        window.repair_pgn_button.click();window.join_previous_button.click()
    assert actions==['repair','join']
    from PySide6.QtWidgets import QPushButton
    assert any(b.text()=='Combine selected PGNs' for b in window.findChildren(QPushButton))
    assert not window.save_screenshots.isChecked()
    assert rank_capture_windows(options)[0][0]==4
    assert rank_youtube_windows(options)[0][0]==4
    window.on_update({'preview_fen':chess.Board().fen(),'preview_moves':[],'confidence':.95,
                      'weakest_confidence':.9,'uncertain_squares':[],'moves':[],
                      'initial_fen':chess.STARTING_FEN,'orientation':'white',
                      'status':'Previewing selected window'})
    assert window.live_board.fen==chess.Board().fen()
    board=chess.Board();window.manager.process(Observation.from_board(board));board.push_san('e4')
    window.on_update(window.manager.process(Observation.from_board(board)))
    assert window.live_board.fen==board.fen() and window.snapshot['pending_moves']==['e4']
    window._preview_active=True
    window.on_update({**window.snapshot,'recording_started_automatically':True})
    assert not window._preview_active and not window.start_button.isEnabled()
    assert window.pause_button.isEnabled() and window.stop_button.isEnabled()
    window.update_move_table(['e4'],chess.STARTING_FEN,guessed=[1])
    assert window.move_table.item(0,1).text()=='≈ e4'
    assert '1. e4' not in window.store.game(window.manager.current_id)['pgn']
    window.manager.force_new();window.navigate(1);window.game_table.selectAll()
    actions={action.text():action for action in window.game_row_menu().actions()}
    assert 'Delete saved PGN file(s)…' in actions
    assert actions['Join selected recordings…'].isEnabled()
    window.close();window.deleteLater();app.processEvents()


def test_screenshot_browser_supports_extended_range_and_multiselect(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication,QAbstractItemView
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    import chessstream.gui as gui
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui,'windows',lambda:[])
    window=gui.MainWindow(tmp_path)
    image=cv2.imread(str(FIXTURES/'results/native-bot-start.png'))
    for second in (1,2,3):
        window.store.save_screenshot(window.manager.session_id,None,image,
            f'2026-10-19T00:00:0{second}.000+00:00',None,.9)
    window.navigate(2)
    window.show();app.processEvents()
    assert window.shot_list.selectionMode()==QAbstractItemView.ExtendedSelection
    view=window.shot_list.viewport()
    first=window.shot_list.visualItemRect(window.shot_list.item(0)).center()
    third=window.shot_list.visualItemRect(window.shot_list.item(2)).center()
    middle=window.shot_list.visualItemRect(window.shot_list.item(1)).center()
    QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,first)
    QTest.mouseClick(view,Qt.LeftButton,Qt.ShiftModifier,third)
    assert len(window.shot_list.selectedItems())==3
    QTest.mouseClick(view,Qt.LeftButton,Qt.ControlModifier,middle)
    assert {window.shot_list.row(item) for item in window.shot_list.selectedItems()}=={0,2}
    assert window.delete_shots_button.isEnabled()
    ids=window.selected_screenshot_ids()
    assert len(ids)==2 and len(set(ids))==2
    window.close();window.deleteLater();app.processEvents()
