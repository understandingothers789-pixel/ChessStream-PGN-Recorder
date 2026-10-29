"""Keyboard review must update the board, including variation rows."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import chess
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QWidget,QSlider,QLabel
from chessstream.review_ui import ReviewTools


def test_library_horizontal_arrows_review_rows_and_variations():
    app=QApplication.instance() or QApplication([])
    class Board:
        def show_board(self,fen,move):self.fen=fen
    class Review(ReviewTools,QWidget):pass
    review=Review();review.library_board=Board();review.review_slider=QSlider()
    review.review_label=QLabel();tabs=review.make_review_tabs()
    review.populate_review({'id':'test','pgn':'1. e4 e5 (1... c5 2. Nf3) 2. Nf3 *'})
    tree=review.review_tree
    tree.setCurrentItem(review.review_items[(0,)])
    QTest.keyClick(tree,Qt.Key_Right)
    assert tree.currentItem() is review.review_items[(0,0)]
    assert review.library_board.fen==review.review_document.variations[0].variations[0].board().fen()
    QTest.keyClick(tree,Qt.Key_Right)
    assert tree.currentItem() is review.review_items[(0,1)]
    QTest.keyClick(tree,Qt.Key_Right)
    assert tree.currentItem() is review.review_items[(0,1,0)]
    QTest.keyClick(tree,Qt.Key_Left)
    assert tree.currentItem() is review.review_items[(0,1)]
    assert 'variation' in review.review_label.text()
    tree.setCurrentItem(review.review_items[()])
    QTest.keyClick(tree,Qt.Key_Left)
    assert tree.currentItem() is review.review_items[()]
    tree.setCurrentItem(review.review_items[(0,0,0)])
    QTest.keyClick(tree,Qt.Key_Right)
    assert tree.currentItem() is review.review_items[(0,0,0)]
    QTest.keyClick(tree,Qt.Key_Up)
    assert tree.currentItem() is review.review_items[(0,1,0)]
    tabs.close();review.close()
