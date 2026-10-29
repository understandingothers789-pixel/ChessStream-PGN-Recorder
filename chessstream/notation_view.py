"""Offline, Lichess-inspired notation with inline, selectable variations."""
from html import escape
import re
from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTextBrowser,QApplication


class NotationView(QTextBrowser):
    move_selected=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setOpenLinks(False);self.setOpenExternalLinks(False)
        self.setMinimumWidth(220)
        self.setStyleSheet('QTextBrowser { background:#262421; color:#d9d7d3; border:0; padding:8px; font-size:15px; }')
        self.setToolTip('Click any move or variation to review it. Left/Right or Up/Down steps through the notation.')
        self.anchorClicked.connect(self._activate)
        self.game=None;self.paths=[];self.selected=();self._key=None

    def loadResource(self,kind,url):
        # PGN comments are plain escaped text; never fetch external resources.
        return None

    def contextMenuEvent(self,event):
        menu=self.createStandardContextMenu()
        if self.game is not None:
            menu.addSeparator();menu.addAction('Copy PGN',lambda:QApplication.clipboard().setText(str(self.game)))
        menu.exec(event.globalPos())

    def _activate(self,url):
        if url.scheme()!='move':return
        try:path=tuple(int(part) for part in url.path().split('.') if part)
        except ValueError:return
        if path not in self.paths:return
        self.move_selected.emit(path)

    def keyPressEvent(self,event):
        if event.modifiers()==Qt.NoModifier and event.key() in (Qt.Key_Left,Qt.Key_Right,Qt.Key_Up,Qt.Key_Down,Qt.Key_Home,Qt.Key_End):
            if not self.paths:return
            index=self.paths.index(self.selected) if self.selected in self.paths else 0
            if event.key()==Qt.Key_Home:index=0
            elif event.key()==Qt.Key_End:index=len(self.paths)-1
            else:index=max(0,min(len(self.paths)-1,index+(-1 if event.key() in (Qt.Key_Left,Qt.Key_Up) else 1)))
            self.move_selected.emit(self.paths[index]);event.accept();return
        super().keyPressEvent(event)

    def show_game(self,game,selected=(),follow=False,pending=()):
        key=(str(game),tuple(selected),tuple(pending))
        if key==self._key:return
        self._key=key;self.game=game;self.selected=tuple(selected);self.paths=[()]
        scroll=self.verticalScrollBar().value()
        anchor_name='p'+'.'.join(map(str,selected))
        def link(node,path,number=False):
            self.paths.append(path)
            board=node.parent.board();prefix=(str(board.fullmove_number)+('. ' if board.turn else '… ')) if number else ''
            selected=path==self.selected
            style='background-color:#426b51; color:#fff;' if selected else 'color:#dedbd5;'
            # Qt tooltips can auto-detect rich text; keep their decoded value
            # free of tag delimiters as well as escaping the HTML attribute.
            title=escape(node.comment.replace('<','‹').replace('>','›'),quote=True)
            nags=''.join({1:'!',2:'?',3:'!!',4:'??',5:'!?',6:'?!'}.get(n,'') for n in sorted(node.nags))
            clock=node.clock();clock_text=f' <span style="color:#96938c;font-size:11px">{int(clock)//60}:{int(clock)%60:02d}</span>' if clock is not None else ''
            return f'<a name="p{".".join(map(str,path))}" href="move:{".".join(map(str,path))}" title="{title}" style="text-decoration:none;{style}">&nbsp;{prefix}{escape(node.san())}{nags}&nbsp;</a>{clock_text}'
        def branch(first,path):
            tokens=[];node=first;current=path;start=True
            while True:
                tokens.append(link(node,current,start or node.parent.board().turn));start=False
                if current[-1]==0:
                    for index,alternative in enumerate(node.parent.variations[1:],1):
                        tokens.append('<br>&nbsp;&nbsp;<span style="color:#999">↳ ( </span>'+branch(alternative,current[:-1]+(index,))+' <span style="color:#999">)</span><br>')
                if not node.variations:break
                node=node.variations[0];current=current+(0,)
            return ' '.join(tokens)
        def comment(node):
            text=re.sub(r'\[%[^]]*\]','',node.comment).strip()
            if not text or text.startswith(('Inferred','Observed','Alternative inferred','Previous inferred','Guessed')):return ''
            return '<tr><td colspan="3" style="color:#a8a49b;font-size:12px">'+escape(text)+'</td></tr>'
        rows=[];node=game;path=()
        while node.variations:
            child=node.variations[0];child_path=path+(0,);board=node.board()
            white=link(child,child_path) if board.turn else '<span style="color:#888">…</span>'
            black=''
            # Interrupt a pair when a side line must be shown beneath it.
            paired=board.turn and len(node.variations)==1 and bool(child.variations)
            if paired:black=link(child.variations[0],child_path+(0,))
            elif not board.turn:black=link(child,child_path)
            rows.append(f'<tr><td width="12%" style="color:#999">{board.fullmove_number}</td><td width="44%">{white}</td><td width="44%">{black}</td></tr>')
            rows.append(comment(child))
            if paired:rows.append(comment(child.variations[0]))
            for index,alternative in enumerate(node.variations[1:],1):
                rows.append('<tr><td colspan="3" bgcolor="#302e2b" style="padding:8px;color:#aaa;font-size:13px">↳ '+branch(alternative,path+(index,))+'</td></tr>')
            if paired:
                for index,alternative in enumerate(child.variations[1:],1):
                    rows.append('<tr><td colspan="3" bgcolor="#302e2b" style="padding:8px;color:#aaa;font-size:13px">↳ '+branch(alternative,child_path+(index,))+'</td></tr>')
            node=child;path=child_path
            if paired:node=node.variations[0];path=path+(0,)
        provisional=''
        if pending:provisional='<p style="color:#d6b071;font-size:12px">Pending · '+escape(' '.join(pending))+' · not saved</p>'
        self.setHtml('<a href="move:" style="color:#999;font-size:12px;text-decoration:none">Starting position</a><table width="100%" cellspacing="0" cellpadding="6">'+''.join(rows)+'</table>'+provisional)
        if follow:self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
        else:
            self.verticalScrollBar().setValue(scroll)
            block=self.document().begin()
            while block.isValid():
                fragments=block.begin()
                while not fragments.atEnd():
                    fragment=fragments.fragment()
                    if anchor_name in fragment.charFormat().anchorNames():
                        cursor=QTextCursor(self.document());cursor.setPosition(fragment.position())
                        self.setTextCursor(cursor);self.ensureCursorVisible();return
                    fragments+=1
                block=block.next()
