import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from chessstream.gui import MainWindow
from chessstream.domain import Observation
import chess
import cv2
from pathlib import Path


def test_desktop_pages_game_review_and_screenshots(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path);window.show();app.processEvents()
    b=chess.Board();window.manager.process(Observation.from_board(b))
    for san in 'e4 e5 Nf3'.split():b.push_san(san);window.manager.process(Observation.from_board(b))
    window.on_update(window.manager.snapshot());assert window.move_table.rowCount()==2
    image=cv2.imread(str(Path(__file__).parent/'fixtures/real/lichess-start.png'));window.on_frame(image)
    window.store.save_screenshot(window.manager.session_id,window.manager.current_id,image,'2026-10-18T00:00:00.000+00:00',b.board_fen(),.99,3)
    window.navigate(1);window.game_table.selectRow(0);app.processEvents();assert 'Nf3' in window.library_pgn.toPlainText()
    window.review_slider.setValue(1);assert chess.Board(window.library_board.fen).piece_at(chess.E4)==chess.Piece(chess.PAWN,chess.WHITE)
    window.navigate(2);app.processEvents();assert window.shot_list.count()==1
    window.shot_list.setCurrentRow(0);assert 'Verified ply at capture: 3' in window.shot_info.text()
    window.navigate(3);assert window.retention.value()==0 and not window.dedupe.isChecked()
    window.navigate(0);window.resize(1000,580);app.processEvents()
    scroll=window.stack.currentWidget()
    assert scroll.verticalScrollBar().maximum()>0
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    assert scroll.verticalScrollBar().value()==scroll.verticalScrollBar().maximum()
    window.close();window.deleteLater();app.processEvents()


def test_pending_recognition_is_not_shown_as_a_reconstructed_start(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path)
    assert window.live_board.fen is None
    window.on_update({"fen":None,"moves":[],"status":"Waiting for reliable recognition",
                      "weakest_confidence":.55,"confidence":.99,"uncertain_squares":["d8"]})
    assert window.metric_labels['confidence'].text()=='55.0%'
    assert 'd8' in window.recognition_details.text()
    assert window.live_board.fen is None
    window.close();window.deleteLater();app.processEvents()
