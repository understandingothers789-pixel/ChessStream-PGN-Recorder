from __future__ import annotations

from pathlib import Path
import chess
import chess.svg
from PySide6.QtCore import Qt, Signal, QRect, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QPixmap, QImage
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QFrame, QPushButton, QHBoxLayout, QSizePolicy
from .domain import Region


STYLE = """
* { font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; color: #dce5f1; }
QMainWindow, QDialog { background: #101620; }
QWidget#sidebar { background: #0c111a; border-right: 1px solid #243041; }
QWidget#page { background: #101620; }
QLabel#brand { font-size: 20px; font-weight: 700; color: #f4f7fb; }
QLabel#title { font-size: 27px; font-weight: 650; color: #f4f7fb; }
QLabel#subtitle, QLabel#muted { color: #94a5ba; }
QLabel#metric { font-size: 23px; font-weight: 650; color: #69dec1; }
QLabel#cardTitle { font-size: 14px; font-weight: 600; color: #e3eaf4; }
QFrame#card { background: #182231; border: 1px solid #2a384b; border-radius: 12px; }
QPushButton { background: #233247; border: 1px solid #34465d; border-radius: 7px; padding: 9px 14px; font-weight: 500; }
QPushButton:hover { background: #2c405a; border-color: #67869f; }
QPushButton:pressed { background: #172739; }
QPushButton:disabled { color: #647286; border-color: #253245; background: #192332; }
QPushButton#primary { background: #6bdec1; color: #092c28; border: 0; font-weight: 700; }
QPushButton#primary:hover { background: #98ead5; }
QPushButton#danger { color: #ffadae; background: #3a242e; border-color: #75424b; }
QPushButton#nav { text-align: left; border: 0; background: transparent; padding: 12px 16px; color: #a4b4c8; }
QPushButton#nav:checked { background: #20332f; color: #8aebd1; border-left: 3px solid #6bdec1; }
QPushButton#nav:hover { background: #1b2838; }
QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QKeySequenceEdit {
 background: #111b29; border: 1px solid #34465d; border-radius: 6px; padding: 7px; selection-background-color: #345e69; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #6bdec1; }
QTableWidget, QListWidget, QTreeWidget { background: #121c2a; alternate-background-color: #192637; border: 1px solid #2b3a50; border-radius: 8px; gridline-color: #26364b; }
QTableWidget::item, QListWidget::item { padding: 6px; }
QTableWidget::item:selected, QListWidget::item:selected, QTreeWidget::item:selected { background: #254d50; }
QTreeWidget::item { padding: 4px; }
QHeaderView::section { background: #202e41; border: 0; padding: 10px; color: #a9bad0; font-weight: 600; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #111b29; width: 10px; }
QScrollBar::handle:vertical { background: #3a4c63; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QCheckBox { spacing: 9px; padding: 5px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #587088; border-radius: 4px; background: #111b29; }
QCheckBox::indicator:checked { background: #6bdec1; }
QTabWidget::pane { border: 1px solid #2b3a50; }
QTabBar::tab { background: #192638; padding: 10px 20px; }
QTabBar::tab:selected { color: #6bdec1; background: #243748; }
QStatusBar { background: #0c111a; color: #9cacc0; }
QToolTip { background: #25374e; color: #e5eef7; padding: 5px; border: 1px solid #537085; }
"""


def button(text, callback=None, primary=False, danger=False):
    b=QPushButton(text)
    if primary:b.setObjectName("primary")
    elif danger:b.setObjectName("danger")
    if callback:b.clicked.connect(callback)
    return b


def muted(text):
    label=QLabel(text);label.setObjectName("muted");label.setWordWrap(True)
    return label


class Card(QFrame):
    def __init__(self,title=None):
        super().__init__();self.setObjectName("card")
        self.box=QVBoxLayout(self);self.box.setContentsMargins(18,16,18,16);self.box.setSpacing(12)
        if title:
            label=QLabel(title);label.setObjectName("cardTitle");self.box.addWidget(label)


class ImageView(QLabel):
    double_clicked=Signal()
    def __init__(self):
        super().__init__("Draw a rectangle around the board\nto see the live capture")
        self.setAlignment(Qt.AlignCenter);self.setMinimumSize(180,180)
        self.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Ignored)
        self.setStyleSheet("background: #0c131f; color: #73869e; border-radius: 8px;")
        self.original=QPixmap()

    def set_array(self,image):
        h,w=image.shape[:2]
        q=QImage(image.data,w,h,image.strides[0],QImage.Format_BGR888).copy()
        self.original=QPixmap.fromImage(q);self.refresh()

    def set_file(self,path):
        self.original=QPixmap(str(path));self.refresh()

    def refresh(self):
        if not self.original.isNull():
            self.setPixmap(self.original.scaled(self.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def resizeEvent(self,event):
        super().resizeEvent(event);self.refresh()

    def mouseDoubleClickEvent(self,event):self.double_clicked.emit()


class BoardView(QSvgWidget):
    def __init__(self):
        super().__init__();self.setMinimumSize(180,180)
        self.fen=chess.STARTING_FEN;self.flipped=False;self.last_move=None
        self.show_board()

    def show_pending(self):
        self.fen=None;self.last_move=None
        self.load(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">'
                  b'<rect width="400" height="400" rx="8" fill="#0c131f"/>'
                  b'<text x="200" y="195" text-anchor="middle" fill="#aac2b7" font-family="sans-serif" font-size="17">Waiting for reliable recognition</text>'
                  b'<text x="200" y="224" text-anchor="middle" fill="#73869e" font-family="sans-serif" font-size="13">No starting position accepted yet</text></svg>')

    def show_board(self,fen=None,last_move=None,flipped=None,provisional=False):
        if fen:self.fen=fen
        if flipped is not None:self.flipped=flipped
        self.last_move=last_move
        b=chess.Board(self.fen)
        move=chess.Move.from_uci(last_move) if last_move else None
        colors={"square light":"#d7ded5","square dark":"#638978","margin":"#182231",
                "coord dark":"#aac2b7","coord light":"#aac2b7"}
        if provisional:
            colors["square light lastmove"]="#efc06f"
            colors["square dark lastmove"]="#b97832"
        svg=chess.svg.board(b,orientation=not self.flipped,lastmove=move,
            check=b.king(b.turn) if b.is_check() else None,
            colors=colors)
        self.load(svg.encode())


class DrawOverlay(QWidget):
    selected=Signal(object)
    cancelled=Signal()
    def __init__(self,screen,physical):
        super().__init__();self.screen_info=screen;self.physical=physical
        self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(screen.geometry());self.setCursor(Qt.CrossCursor)
        self.origin=None;self.selection_rect=QRect();self.setMouseTracking(True)

    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton:self.origin=e.position().toPoint()

    def mouseMoveEvent(self,e):
        if self.origin is not None:
            self.selection_rect=QRect(self.origin,e.position().toPoint()).normalized();self.update()

    def mouseReleaseEvent(self,e):
        if self.origin is None:return
        self.selection_rect=QRect(self.origin,e.position().toPoint()).normalized()
        sx=self.physical['width']/self.width();sy=self.physical['height']/self.height()
        r=Region(self.physical['left']+round(self.selection_rect.left()*sx),self.physical['top']+round(self.selection_rect.top()*sy),round(self.selection_rect.width()*sx),round(self.selection_rect.height()*sy))
        if r.valid():self.selected.emit(r)

    def keyPressEvent(self,e):
        if e.key()==Qt.Key_Escape:self.cancelled.emit()

    def paintEvent(self,e):
        p=QPainter(self);p.fillRect(self.rect(),QColor(5,10,20,95))
        p.setPen(QPen(QColor('#6bdec1'),3));p.drawRect(self.selection_rect)
        p.setPen(Qt.white);p.setFont(self.font());p.drawText(30,45,"Draw tightly around all 64 squares. Esc cancels. You can adjust the region later.")
        if self.selection_rect.width():p.drawText(self.selection_rect.topLeft()+QRect(0,0,0,24).bottomRight(),f"{self.selection_rect.width()} × {self.selection_rect.height()}")


class RegionEditor(QWidget):
    selected=Signal(object)
    cancelled=Signal()
    def __init__(self,region,screen,physical):
        super().__init__();self.screen_info=screen;self.physical=physical;self.old=region
        self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground);self.setMinimumSize(90,90)
        self.sx=physical['width']/screen.geometry().width();self.sy=physical['height']/screen.geometry().height()
        g=screen.geometry()
        self.setGeometry(g.x()+round((region.left-physical['left'])/self.sx),g.y()+round((region.top-physical['top'])/self.sy),round(region.width/self.sx),round(region.height/self.sy))
        self.anchor=None;self.resizing=False;self.start_rect=None

    def mousePressEvent(self,e):
        self.anchor=e.globalPosition().toPoint();self.start_rect=self.geometry()
        self.resizing=e.position().x()>self.width()-28 or e.position().y()>self.height()-28

    def mouseMoveEvent(self,e):
        if self.anchor:
            delta=e.globalPosition().toPoint()-self.anchor
            if self.resizing:self.resize(max(90,self.start_rect.width()+delta.x()),max(90,self.start_rect.height()+delta.y()))
            else:self.move(self.start_rect.topLeft()+delta)

    def mouseReleaseEvent(self,e):self.anchor=None
    def mouseDoubleClickEvent(self,e):self.accept_region()

    def keyPressEvent(self,e):
        if e.key() in [Qt.Key_Return,Qt.Key_Enter]:self.accept_region()
        elif e.key()==Qt.Key_Escape:self.cancelled.emit()

    def accept_region(self):
        g=self.screen_info.geometry()
        self.selected.emit(Region(self.physical['left']+round((self.x()-g.x())*self.sx),self.physical['top']+round((self.y()-g.y())*self.sy),round(self.width()*self.sx),round(self.height()*self.sy)))

    def paintEvent(self,e):
        p=QPainter(self);p.fillRect(self.rect(),QColor(12,25,30,35));p.setPen(QPen(QColor('#6bdec1'),4));p.drawRect(self.rect().adjusted(2,2,-2,-2))
        p.fillRect(3,3,self.width()-6,42,QColor(13,37,40,235));p.setPen(Qt.white)
        p.drawText(14,22,"Drag to move • resize from bottom/right")
        p.drawText(14,38,"Enter / double-click applies • Esc cancels")
        p.setPen(QPen(QColor('#6bdec1'),5));p.drawLine(self.width()-25,self.height()-4,self.width()-4,self.height()-25)
