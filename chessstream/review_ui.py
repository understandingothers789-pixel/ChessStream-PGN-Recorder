"""PGN variation navigation and support tools for the desktop window."""
import io
from pathlib import Path
import chess
import chess.pgn
from PySide6.QtCore import Qt,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QTreeWidget,QTreeWidgetItem,QTabWidget,QPlainTextEdit,
    QDialog,QVBoxLayout,QHBoxLayout,QLabel,QInputDialog,QFileDialog,QApplication)
from .widgets import button,muted
from .pgn_tools import node_at
from .diagnostics import export_diagnostics


class ReviewTools:
    def make_review_tabs(self):
        tabs=QTabWidget()
        self.review_tree=QTreeWidget();self.review_tree.setHeaderLabels(['Move / variation','Comment / clock']);self.review_tree.setIndentation(12)
        self.review_tree.currentItemChanged.connect(self.review_selected_node)
        self.library_pgn=QPlainTextEdit();self.library_pgn.setReadOnly(True)
        tabs.addTab(self.review_tree,'Moves & variations');tabs.addTab(self.library_pgn,'PGN text')
        self.review_document=None;self.review_items={}
        return tabs

    def populate_review(self,row,path=None):
        self.library_pgn.setPlainText(row['pgn'])
        self.review_document=chess.pgn.read_game(io.StringIO(row['pgn']))
        self.review_gid=row['id'];self.review_tree.blockSignals(True);self.review_tree.clear();self.review_items={}
        root=QTreeWidgetItem(['Starting position',self.review_document.comment]);root.setData(0,Qt.UserRole,[])
        self.review_tree.addTopLevelItem(root);self.review_items[()]=root
        def make_item(node,child,parent,path,alternative=False):
            board=node.board();prefix=f'{board.fullmove_number}. ' if board.turn else f'{board.fullmove_number}... '
            item=QTreeWidgetItem([('↳ ' if alternative else '')+prefix+board.san(child.move),child.comment])
            item.setData(0,Qt.UserRole,path);item.setToolTip(1,child.comment)
            parent.addChild(item);self.review_items[tuple(path)]=item
            return item
        def fill(node,parent,indices):
            # Main-line rows stay flat; only alternatives add an indentation level.
            while node.variations:
                main=node.variations[0];item=make_item(node,main,parent,indices+[0])
                for i,child in enumerate(node.variations[1:],1):
                    alternative=make_item(node,child,item,indices+[i],True)
                    fill(child,alternative,indices+[i])
                node=main;indices=indices+[0]
        fill(self.review_document,root,[])
        self.review_tree.expandAll();self.review_tree.resizeColumnToContents(0);self.review_tree.blockSignals(False)
        plies=len(list(self.review_document.mainline_moves()))
        self.review_slider.blockSignals(True);self.review_slider.setMaximum(plies);self.review_slider.setValue(plies);self.review_slider.blockSignals(False)
        chosen=self.review_items.get(tuple(path or [0]*plies),root)
        self.review_tree.setCurrentItem(chosen);self.review_selected_node(chosen)

    def review_selected_node(self,item,previous=None):
        if item is None or self.review_document is None:return
        path=item.data(0,Qt.UserRole);node=node_at(self.review_document,path)
        self.library_board.show_board(node.board().fen(),node.move.uci() if node.move else None)
        self.review_label.setText(f"{len(path)} plies"+(' • variation' if not node.is_mainline() else ''))
        if node.is_mainline():
            self.review_slider.blockSignals(True);self.review_slider.setValue(len(path));self.review_slider.blockSignals(False)

    def slider_review(self):
        if self.review_document is None:return
        item=self.review_items.get((0,)*self.review_slider.value())
        if item:self.review_tree.setCurrentItem(item);self.review_selected_node(item)

    def review_anchor(self):
        item=self.review_tree.currentItem()
        if item is None or self.review_document is None:raise ValueError('Select a game and a position first.')
        path=item.data(0,Qt.UserRole)
        return path,node_at(self.review_document,path)

    def reload_review(self,gid,path):
        row=self.store.game(gid)
        if row:self.populate_review(row,path)

    def add_review_variation(self):
        try:
            path,node=self.review_anchor();fen=node.board().fen();gid=self.review_gid
            text,ok=QInputDialog.getText(self,'Add alternative line','Select the position before the move you want to replace. Enter legal SAN moves from this position:')
            if not ok or not text.strip():return
            comment,ok=QInputDialog.getMultiLineText(self,'Variation comment','Optional comment for this analysis line:','')
            if not ok:return
            self.manager.annotate(gid,path,text.strip(),comment,expected_fen=fen)
            self.reload_review(gid,path);self.statusBar().showMessage('Variation saved in the PGN; played main line preserved',6000)
        except Exception as e:self.error(str(e))

    def edit_review_comment(self):
        try:
            path,node=self.review_anchor();gid=self.review_gid
            text,ok=QInputDialog.getMultiLineText(self,'PGN comment','Comment for the selected move / position:',node.comment)
            if not ok:return
            self.manager.annotate(gid,path,comment=text,expected_fen=node.board().fen());self.reload_review(gid,path)
        except Exception as e:self.error(str(e))

    def delete_review_variation(self):
        try:
            path,node=self.review_anchor();gid=self.review_gid
            self.manager.annotate(gid,path,delete=True,expected_fen=node.board().fen());self.reload_review(gid,path[:-1])
        except Exception as e:self.error(str(e))

    def export_diagnostics_ui(self):
        path,_=QFileDialog.getSaveFileName(self,'Save diagnostic bundle — logs, settings, names and PGNs; no screenshots',str(Path.home()/'ChessStream-diagnostics.zip'),'ZIP files (*.zip)')
        if path:self.background(lambda:export_diagnostics(self.store,Path(path)),lambda saved:self.statusBar().showMessage('Diagnostics saved to '+str(saved),15000))

    def show_diagnostics(self):
        dialog=QDialog(self);dialog.setWindowTitle('ChessStream diagnostics');dialog.resize(900,600);box=QVBoxLayout(dialog)
        box.addWidget(muted('Saved logs include status messages, uncertain squares, detected results, move clocks and errors. The export includes names, settings and PGNs, without screenshots.'))
        path=self.root/'application.log';box.addWidget(QLabel(str(path)))
        text=QPlainTextEdit();text.setReadOnly(True);box.addWidget(text,1)
        def refresh():
            try:text.setPlainText(path.read_text(encoding='utf-8')[-200000:] if path.exists() else 'No logged messages yet.');text.verticalScrollBar().setValue(text.verticalScrollBar().maximum())
            except OSError as e:text.setPlainText(str(e))
        row=QHBoxLayout();row.addWidget(button('Refresh',refresh));row.addWidget(button('Copy displayed log',lambda:QApplication.clipboard().setText(text.toPlainText())));row.addWidget(button('Open log folder',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root)))));row.addWidget(button('Export diagnostic ZIP',self.export_diagnostics_ui));box.addLayout(row);refresh();dialog.exec()
