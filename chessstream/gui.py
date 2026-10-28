from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import io
import json
import logging
import sys
import threading
import chess
import chess.pgn
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSize, QDateTime
from PySide6.QtGui import QShortcut, QKeySequence, QIcon, QPixmap, QDesktopServices, QColor
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QStackedWidget, QLabel, QPushButton, QDoubleSpinBox, QSpinBox, QCheckBox,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSplitter, QPlainTextEdit, QTextBrowser, QLineEdit, QListWidget, QListWidgetItem,
    QSlider, QFileDialog, QMessageBox, QInputDialog, QDialog, QDialogButtonBox,
    QFormLayout, QScrollArea, QDateTimeEdit, QTabWidget, QKeySequenceEdit, QMenu, QButtonGroup
)
from .domain import Settings, Region, atomic_text
from .storage import Store
from .games import GameManager
from .capture import (RecordingWorker, monitors, windows, window_client, containing_window,
                      rank_youtube_windows, rank_capture_windows)
from .widgets import STYLE, Card, ImageView, BoardView, DrawOverlay, RegionEditor, button, muted
from .review_ui import ReviewTools
from .hotkeys import GlobalHotkeys
from .model_security import import_custom_model, validate_custom_model
from .gap_join import join_recordings, AmbiguousGapError
from .notation_view import NotationView
from .pgn_tools import node_at


def human_bytes(n):
    for unit in ["B","KB","MB","GB","TB"]:
        if n<1024:return f"{n:.1f} {unit}"
        n/=1024
    return f"{n:.1f} PB"


def local_time(value):
    try:return datetime.fromisoformat(value).astimezone().strftime("%b %d, %H:%M:%S")
    except (ValueError,TypeError):return value or "—"


class Task(QThread):
    result=Signal(object)
    failed=Signal(str)
    def __init__(self,fn):super().__init__();self.fn=fn
    def run(self):
        try:self.result.emit(self.fn())
        except Exception as e:logging.exception("Background task failed");self.failed.emit(str(e))


class MoveTableWidget(QTableWidget):
    step_move=Signal(int)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Left,Qt.Key_Right) and event.modifiers()==Qt.NoModifier:
            self.step_move.emit(-1 if event.key()==Qt.Key_Left else 1)
            event.accept();return
        super().keyPressEvent(event)


class MainWindow(ReviewTools,QMainWindow):
    def __init__(self,root:Path):
        super().__init__();self.root=root;self.settings=Settings.load(root/"settings.json")
        self.store=Store(root);self.manager=GameManager(self.store,self.settings)
        self.worker=None;self._preview_active=False;self.tasks=[];self.overlays=[];self.latest_image=None;self.snapshot={}
        self._live_review=None
        self.retention_task=None;self._closing=False
        self.region=Region(**self.settings.region) if self.settings.region else None
        self.setWindowTitle("ChessStream PGN Recorder")
        available=QApplication.primaryScreen().availableGeometry()
        minimum_width=min(960,max(640,available.width()-24));minimum_height=min(560,max(400,available.height()-24))
        self.setMinimumSize(minimum_width,minimum_height)
        self.resize(max(minimum_width,min(1460,available.width()-48)),max(minimum_height,min(940,available.height()-48)))
        self.setStyleSheet(STYLE)
        self.global_hotkeys=GlobalHotkeys(QApplication.instance())
        icon=Path(__file__).parent/"assets/icon.ico"
        if icon.exists():self.setWindowIcon(QIcon(str(icon)))
        outer=QWidget();self.setCentralWidget(outer);layout=QHBoxLayout(outer);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        side=QWidget();side.setObjectName("sidebar");side.setFixedWidth(208);sidebar=QVBoxLayout(side);sidebar.setContentsMargins(16,28,16,20)
        brand=QLabel("♞  ChessStream");brand.setObjectName("brand");sidebar.addWidget(brand);sidebar.addWidget(muted("PGN RECORDER  /  LOCAL"));sidebar.addSpacing(35)
        self.stack=QStackedWidget();self.nav=[];self.nav_group=QButtonGroup(self)
        for i,name in enumerate(["◉   Live recording","▦   Game library","▧   Screenshots","⚙   Settings"]):
            b=button(name,lambda checked=False,n=i:self.navigate(n));b.setObjectName("nav");b.setCheckable(True);self.nav_group.addButton(b,i);sidebar.addWidget(b);self.nav.append(b)
        sidebar.addStretch();sidebar.addWidget(muted("Local recognition\nNo accounts or paid APIs\n\nv1.6.24-dev15"))
        sidebar.addWidget(button("Open user guide",self.open_guide))
        sidebar.addWidget(button("Diagnostics / logs",self.show_diagnostics))
        layout.addWidget(side);layout.addWidget(self.stack,1)
        self.build_live();self.build_library();self.build_screenshots();self.build_settings()
        self.navigate(0);self.install_hotkeys()
        if sys.platform=='win32':QTimer.singleShot(250,self.refresh_desktop_shortcut)
        self.statusBar().showMessage("Ready • "+("screenshot saving is on" if self.settings.save_screenshots else "screenshot saving is off"))
        # Prefer the best visible YouTube window at every launch, including
        # over a stale saved source. If none is available, retain the saved
        # source while briefly retrying in case the browser is still opening.
        self._auto_window_enabled = True
        self.auto_window_timer=QTimer(self);self.auto_window_timer.setInterval(2000)
        self.auto_window_timer.timeout.connect(self._auto_select_youtube_window)
        if self._auto_window_enabled and not self._auto_select_youtube_window():
            if sys.platform == "win32":self.auto_window_timer.start()
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh_usage);self.timer.start(10000)
        self.retention_timer=QTimer(self);self.retention_timer.timeout.connect(self.run_retention);self.retention_timer.start(60000)
        QTimer.singleShot(100,self.run_retention);self.refresh_usage()
        recoverable=[g for g in self.store.games() if g["status"] not in ["imported","complete"]]
        if recoverable:self.recovery.setText(f"{len(recoverable)} saved recording(s) available. Open Game library to resume or export.")

    def page(self,title,subtitle):
        page=QWidget();page.setObjectName("page");box=QVBoxLayout(page);box.setContentsMargins(28,24,28,24);box.setSpacing(16)
        label=QLabel(title);label.setObjectName("title");box.addWidget(label);box.addWidget(muted(subtitle))
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page)
        self.stack.addWidget(scroll);return page,box

    def navigate(self,index):
        for i,b in enumerate(self.nav):b.setChecked(i==index)
        self.stack.setCurrentIndex(index)
        if index==1:self.refresh_library()
        elif index==2:self.refresh_screenshots()

    def build_live(self):
        page,box=self.page("Record the board. Keep the game.","Draw around a visible board, then start. Hidden player names are recorded as Unknown.")
        controls=QHBoxLayout();self.start_button=button("●  Start recording",self.toggle_start,primary=True);self.pause_button=button("Pause",self.pause);self.stop_button=button("Stop",self.stop)
        self.pause_button.setEnabled(False);self.stop_button.setEnabled(False)
        for b in [self.start_button,self.pause_button,self.stop_button]:controls.addWidget(b)
        controls.addStretch();controls.addWidget(button("Select capture region",self.draw_region));controls.addWidget(button("Adjust",self.adjust_region))
        box.addLayout(controls)
        source=QHBoxLayout();self.source_label=muted(self.region_text());source.addWidget(self.source_label,1)
        source.addWidget(button("Monitor…",self.choose_monitor));source.addWidget(button("Window…",self.choose_window))
        source.addWidget(QLabel("Screenshots"));self.screenshot_mode=QComboBox();self.screenshot_mode.addItem('Per position','positions');self.screenshot_mode.addItem('At interval','interval');self.screenshot_mode.setCurrentIndex(0 if self.settings.screenshot_mode=='positions' else 1);self.screenshot_mode.currentIndexChanged.connect(self.set_screenshot_mode);source.addWidget(self.screenshot_mode)
        self.interval=QDoubleSpinBox();self.interval.setRange(.1,60);self.interval.setDecimals(1);self.interval.setSuffix(" s");self.interval.setValue(self.settings.interval);self.interval.setEnabled(self.settings.screenshot_mode!='positions');self.interval.valueChanged.connect(self.set_interval);source.addWidget(self.interval)
        box.addLayout(source)
        metrics=QHBoxLayout();self.metric_labels={}
        for key,title,value in [("moves","PGN PLIES","0"),("confidence","WEAKEST SQUARE SCORE","—"),("saved","SAVED SCREENSHOTS","0"),("disk","SCREENSHOT STORAGE","0 MB")]:
            card=Card();card.box.addWidget(muted(title));label=QLabel(value);label.setObjectName("metric");card.box.addWidget(label);self.metric_labels[key]=label;metrics.addWidget(card)
        box.addLayout(metrics)
        splitter=QSplitter(Qt.Horizontal)
        capture_card=Card("CAPTURED BOARD");self.live_image=ImageView();capture_card.box.addWidget(self.live_image,1);self.capture_caption=muted(self._screenshot_caption());capture_card.box.addWidget(self.capture_caption)
        self.recognition_details=muted("Bundled screenshot model • waiting for a capture");capture_card.box.addWidget(self.recognition_details)
        internal=Card("RECONSTRUCTED BOARD");self.board_heading=internal.box.itemAt(0).widget();self.live_board=BoardView();internal.box.addWidget(self.live_board,1);self.last_move_label=muted("Waiting for the first verified position");internal.box.addWidget(self.last_move_label)
        self.return_live_button=button('Return to live board',self.return_to_live_board)
        self.return_live_button.hide();internal.box.insertWidget(1,self.return_live_button)
        self.live_board.show_pending()
        moves_card=Card("MOVES")
        # Keep the common PGN actions beside the move list, where they remain
        # reachable even when the live page is taller than the window.
        pgn_actions=QHBoxLayout();pgn_actions.setSpacing(6)
        self.live_copy_pgn=button("Copy PGN",self.copy_current);self.live_copy_pgn.setToolTip("Copy the current recording as PGN")
        self.live_export_pgn=button("Export PGN",self.export_current);self.live_export_pgn.setToolTip("Save the current recording as a PGN file")
        self.live_copy_fen=button("Copy FEN",self.copy_visible_fen);self.live_copy_fen.setToolTip("Copy the visible board position as FEN")
        for action in [self.live_copy_pgn,self.live_export_pgn,self.live_copy_fen]:
            action.setStyleSheet("padding:7px 4px;font-size:11px")
            pgn_actions.addWidget(action)
        moves_card.box.addLayout(pgn_actions)
        self.follow_live_button=button('Following latest',self.return_to_live_board)
        self.follow_live_button.setCheckable(True);self.follow_live_button.setChecked(True)
        self.follow_live_button.setToolTip('Resume following the newest position. Clicking the latest PGN move or stepping to the end also resumes live following.')
        moves_card.box.addWidget(self.follow_live_button)
        self.game_identity_button=button('Game: waiting ▾',self.game_controls_menu)
        self.game_identity_button.setStyleSheet('padding:6px;font-size:11px')
        moves_card.box.addWidget(self.game_identity_button)
        self.move_table=MoveTableWidget(0,3);self.move_table.setHorizontalHeaderLabels(["#","White","Black"]);self.move_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);self.move_table.verticalHeader().hide();self.move_table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.move_table.setMinimumWidth(220);self.move_table.setContextMenuPolicy(Qt.CustomContextMenu);self.move_table.customContextMenuRequested.connect(self.live_moves_context_menu);self.move_table.step_move.connect(self.navigate_live_move);self.move_table.setToolTip('Click a move to review it. Use the left and right arrow keys to step through moves in order.');moves_card.box.addWidget(self.move_table,1)
        self.move_table.itemClicked.connect(self.review_live_move)
        self.move_table.hide()
        self.live_notation=NotationView();moves_card.box.addWidget(self.live_notation,1)
        self.live_notation.move_selected.connect(self.review_notation_move)
        self.live_notation.setContextMenuPolicy(Qt.CustomContextMenu)
        self.live_notation.customContextMenuRequested.connect(self.live_moves_context_menu)
        self.uncertain_label=muted('UNVERIFIED POSSIBILITIES • excluded from PGN');self.uncertain_label.setStyleSheet('color:#f4c17a');self.uncertain_label.hide();moves_card.box.addWidget(self.uncertain_label)
        self.alternatives=QComboBox();self.alternatives.setVisible(False);self.alternatives.setStyleSheet('border-color:#c49151;color:#f4d6aa');moves_card.box.addWidget(self.alternatives)
        self.choose_path=button("Confirm selected sequence",self.choose_sequence);self.choose_path.hide();moves_card.box.addWidget(self.choose_path)
        moves_card.box.addWidget(button("Start PGN from visible FEN",self.new_game))
        repair_actions=QHBoxLayout();repair_actions.setSpacing(6)
        self.repair_pgn_button=button("Repair PGN",lambda:self.run_pgn_action('repair'))
        self.repair_pgn_button.setToolTip('Remove redundant piece round trips when the remaining legal moves reach the same final position. The original PGN is retained in diagnostics.')
        self.join_previous_button=button("Join previous",lambda:self.run_pgn_action('join_previous'))
        self.join_previous_button.setToolTip('Try joining this recording to either of the two previous PGNs. Make the combined game active and keep the originals.')
        for action in (self.repair_pgn_button,self.join_previous_button):
            action.setStyleSheet('padding:7px 4px;font-size:11px')
            repair_actions.addWidget(action,1)
        moves_card.box.addLayout(repair_actions)
        for card in [capture_card,internal,moves_card]:splitter.addWidget(card)
        splitter.setSizes([430,430,265])
        audio_row=QHBoxLayout()
        self.audio_toggle=QCheckBox('Audio move cues (experimental)');self.audio_toggle.setChecked(self.settings.audio_cues)
        self.audio_toggle.setToolTip('Listen locally to all sound on the default Windows output device. No microphone or audio recordings. Built-in Chess.com and Lichess default sounds; no learning required.')
        self.audio_toggle.toggled.connect(self.set_audio_cues);audio_row.addWidget(self.audio_toggle)
        audio_row.addStretch();box.addLayout(audio_row)
        self.audio_status=muted('Audio cues off');self.audio_status.setWordWrap(True);box.addWidget(self.audio_status);box.addWidget(splitter,1)
        self.recording_status=QLabel("●  Ready to record");self.recording_status.setWordWrap(True);self.recording_status.setStyleSheet("color:#8ee3ce;font-weight:600;padding:8px;");box.addWidget(self.recording_status)
        self.recovery=muted("Search uses the shortest legal gap. Unseen repetitions and identical transpositions may need review.");box.addWidget(self.recovery)
        footer=QHBoxLayout();footer.addWidget(button("Flip orientation",self.flip_orientation));footer.addWidget(button("Calibrate piece set…",self.calibrate));footer.addStretch();self.delay_label=muted("All processing stays on this computer");footer.addWidget(self.delay_label);box.addLayout(footer)

    def set_audio_cues(self,enabled):
        self.settings.audio_cues=enabled;self.settings.save(self.root/'settings.json')
        self.audio_status.setText('Starting playback listener…' if enabled else 'Audio cues off')

    def live_moves_context_menu(self,position):
        menu=QMenu(self.live_notation)
        copy=menu.addAction("Copy current PGN")
        export=menu.addAction("Export current PGN…")
        menu.addSeparator()
        fen=menu.addAction("Copy visible FEN")
        menu.addSeparator()
        manual=menu.addAction("Edit moves manually…")
        selected=menu.exec(self.live_notation.viewport().mapToGlobal(position))
        if selected==copy:self.copy_current()
        elif selected==export:self.export_current()
        elif selected==fen:self.copy_visible_fen()
        elif selected==manual:self.correct_moves()

    def game_controls_menu(self):
        menu=QMenu(self.game_identity_button)
        for text,mode in [('Automatic game detection','auto'),('Start separate PGN from visible board','new'),
                          ('Continue current PGN','continue'),('Treat as analysis / replay','analysis'),
                          ('Undo last game switch','undo')]:
            action=menu.addAction(text,lambda checked=False,value=mode:self.run_game_control(value))
            if mode=='undo':action.setEnabled(bool(self.snapshot.get('lifecycle',{}).get('can_undo')))
        menu.addSeparator();selected_path=self.live_notation.selected
        ply=len(selected_path) if selected_path and not any(selected_path) else None
        action=menu.addAction('Split PGN after selected move',lambda:self.run_game_control('split',ply))
        action.setEnabled(bool(ply and 0<ply<len(self.snapshot.get('moves',[]))))
        menu.exec(self.game_identity_button.mapToGlobal(self.game_identity_button.rect().bottomLeft()))

    def run_game_control(self,mode,ply=None):
        try:
            self._pgn_action_pending=True
            if mode=='split':
                value=(self.snapshot.get('game_id'),ply)
                if self.worker and self.worker.isRunning():self.worker.commands.put(('split_game',value))
                else:self.manager.split_game_at(ply);self.on_update(self.manager.snapshot())
            elif self.worker and self.worker.isRunning():self.worker.commands.put(('game_mode',mode))
            else:self.manager.set_game_mode(mode);self.on_update(self.manager.snapshot())
        except Exception as error:self.error(str(error))

    def run_pgn_action(self,action):
        if self.worker and self.worker.isRunning():
            self._pgn_action_pending=True
            self.worker.commands.put((action,None))
            self.recording_status.setText('Checking PGN…')
            return
        if action=='repair':self.manager.repair_current()
        else:
            self.manager.join_previous_recording(background=True)
            def poll_join():
                if self._closing:return
                self.manager.poll_saved_join()
                self.on_update(self.manager.snapshot())
                if self.manager._saved_join_future:QTimer.singleShot(100,poll_join)
            QTimer.singleShot(100,poll_join)
        self.on_update(self.manager.snapshot())

    def region_text(self):
        r=self.region
        if not r:return "No capture source selected"
        return f"{'Tracked window' if r.window else 'Screen region'}  •  {r.width} × {r.height} px  •  ({r.left}, {r.top})"

    def set_interval(self,value):
        self.settings.interval=value;self.settings.save(self.root/"settings.json")
        if hasattr(self,'settings_interval'):self.settings_interval.setValue(value)

    def set_screenshot_mode(self,index):
        self.settings.screenshot_mode=self.screenshot_mode.currentData();self.settings.save(self.root/'settings.json')
        if hasattr(self,'interval'):self.interval.setEnabled(self.settings.screenshot_mode!='positions')
        if hasattr(self,'capture_caption'):self.capture_caption.setText(self._screenshot_caption())

    def _screenshot_caption(self):
        if not self.settings.save_screenshots:
            return 'Screenshot saving is off. Frames are still captured and analyzed in memory; no screenshot images are written to disk.'
        return ('Saved screenshots: one per settled position. Arrow and cursor changes reuse that position. Analysis frames stay temporary.'
                if self.settings.screenshot_mode=='positions' else
                'Permanent screenshots: at the selected interval. Analysis frames stay temporary.')

    def toggle_start(self):
        if self.worker and self.worker.isRunning():
            if self._preview_active:
                self.worker.commands.put(("record",None));self._preview_active=False
                self.start_button.setEnabled(False);self.pause_button.setEnabled(True);self.stop_button.setEnabled(True)
                self.recording_status.setText("●  Starting recording from the live preview")
            else:self.pause()
            return
        if self._auto_window_enabled and not self._auto_select_youtube_window():
            # Freeze the fallback region before the user starts recording.
            self._auto_window_enabled=False;self.auto_window_timer.stop()
        if not self.region:self.draw_region();return
        if self.manager.rec and self.manager.ended:
            self.manager=GameManager(self.store,self.settings)
        elif not self.manager.rec:
            sessions=self.store.query('SELECT ended FROM sessions WHERE id=?',(self.manager.session_id,))
            if sessions and sessions[0]['ended']:
                self.manager.session_id=self.store.session()
        self.worker=RecordingWorker(self.manager,self.region);self.worker.frame.connect(self.on_frame);self.worker.update.connect(self.on_update);self.worker.problem.connect(self.error);self.worker.region_changed.connect(self.auto_region);self.worker.finished.connect(self.worker_finished);self.worker.start()
        self.start_button.setEnabled(False);self.pause_button.setEnabled(True);self.stop_button.setEnabled(True);self.recording_status.setText("●  Capturing • waiting for a stable board")

    def pause(self):
        if not self.worker or not self.worker.isRunning():return
        if self.worker.paused.is_set():self.worker.paused.clear();self.pause_button.setText("Pause")
        else:self.worker.paused.set();self.pause_button.setText("Resume");self.recording_status.setText("Ⅱ  Paused • PGN and screenshots preserved")

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop();self.stop_button.setEnabled(False);self.recording_status.setText("Saving recording…")

    def worker_finished(self):
        was_preview=self._preview_active;self._preview_active=False
        self.start_button.setEnabled(True);self.pause_button.setEnabled(False);self.pause_button.setText("Pause");self.stop_button.setEnabled(False)
        self.recording_status.setText("■  Preview stopped" if was_preview else "■  Stopped • verified PGN saved");self.refresh_usage()

    def start_preview(self):
        """Show the selected board and recognition result without saving data."""
        if not self.region or (self.worker and self.worker.isRunning()):return
        self._preview_active=True
        self.worker=RecordingWorker(self.manager,self.region,preview_only=True)
        self.worker.frame.connect(self.on_frame);self.worker.update.connect(self.on_update)
        self.worker.problem.connect(self.error);self.worker.region_changed.connect(self.auto_region)
        self.worker.finished.connect(self.worker_finished);self.worker.start()
        self.stop_button.setEnabled(True)
        self.recording_status.setText('◉  Armed • recording starts when an opening move appears' if self.settings.auto_record_opening else
                                     '◉  Live preview • click Start recording when ready')

    def on_frame(self,image):
        self.latest_image=image;self.live_image.set_array(image)

    def on_update(self,snap):
        self.snapshot=snap
        notation_key=(snap.get('recorded_pgn',''),snap.get('initial_fen',chess.STARTING_FEN),tuple(snap.get('moves',[])))
        if notation_key!=getattr(self,'_notation_document_key',None):
            self._notation_document_key=notation_key
            document=chess.pgn.read_game(io.StringIO(notation_key[0]))
            if document is None:
                document=chess.pgn.Game();document.setup(chess.Board(notation_key[1]));node=document
                for san in notation_key[2]:node=node.add_main_variation(node.board().parse_san(san))
            self._live_document=document
        audio=snap.get('audio_cues')
        if audio:
            self.audio_status.setText(f"Audio • {audio['status']} • {audio.get('count',0)} cues"+
                (f" • {audio['board_hint']}" if audio.get('board_hint') else '')+
                (f" • {audio['device']}" if audio.get('device') else '')+
                (f" • {audio['dropped_blocks']} interrupted blocks" if audio.get('dropped_blocks') else ''))
        lifecycle=snap.get('lifecycle',{})
        self.game_identity_button.setText('Game: '+lifecycle.get('state','waiting for a game')+' ▾')
        self.game_identity_button.setToolTip('White: '+snap.get('players',{}).get('white','Unknown')+'\nBlack: '+snap.get('players',{}).get('black','Unknown')+
            '\nGame ID: '+str(snap.get('game_id') or 'waiting')+'\nAccepted plies: '+str(snap.get('plies',0))+
            '\nPending histories: '+str(snap.get('pending_hypotheses',0))+
            '\nIdentity: '+lifecycle.get('identity','pending')+'\n'+lifecycle.get('reason','')+'\nClick to correct game detection or split a PGN.')
        if self._live_review:
            line=snap.get('moves',[])+(snap.get('pending_moves',[]) if snap.get('provisional') else [])
            review=self._live_review
            if 'path' in review:
                try:valid=node_at(self._live_document,review['path']).board().fen()==review['fen']
                except IndexError:valid=False
            else:valid=tuple(line[:review['ply']])==review['prefix']
            if (review['game_id']!=snap.get('game_id') or review['initial_fen']!=snap.get('initial_fen',chess.STARTING_FEN)
                    or not valid):self._live_review=None
        self.return_live_button.setVisible(self._live_review is not None)
        self.follow_live_button.setChecked(self._live_review is None)
        self.follow_live_button.setText('Following latest' if self._live_review is None else 'Follow latest')
        if snap.get('recording_started_automatically'):
            self._preview_active=False
            self.start_button.setEnabled(False);self.pause_button.setEnabled(True);self.stop_button.setEnabled(True)
        diagnostic_key=(snap.get('game_id'),snap.get('status'),tuple(snap.get('uncertain_squares',[])),snap.get('plies'))
        if diagnostic_key!=getattr(self,'_last_diagnostic',None):
            logging.info('Live display %s',json.dumps({key:snap.get(key) for key in ['game_id','status','plies','weakest_confidence','uncertain_squares','orientation','result','clocks','players','lifecycle','evidence_revision','pending_hypotheses','recovery_tasks','processing_ms','capture_metrics']}))
            self._last_diagnostic=diagnostic_key
        if not self.worker or not self.worker.paused.is_set() or getattr(self,'_pgn_action_pending',False):
            self._pgn_action_pending=False
            status=snap.get('status','Recording');self.recording_status.setText("●  "+status)
            warning=any(word in status.lower() for word in ['uncertain','unmatched','limit','obstructed','hidden','reset','review','waiting','unknown','provisional'])
            self.recording_status.setStyleSheet(f"color:{'#f4c17a' if warning else '#8ee3ce'};font-weight:600;padding:8px;")
        moves=snap.get('moves',[]);self.metric_labels['moves'].setText(str(len(moves)))
        if 'weakest_confidence' in snap:
            self.metric_labels['confidence'].setText(f"{snap['weakest_confidence']*100:.1f}%")
            self.metric_labels['confidence'].setToolTip(f"Lowest square classifier score. Average: {snap.get('confidence',0)*100:.1f}%. Scores are not an accuracy guarantee.")
        if 'uncertain_squares' in snap:
            uncertain=snap['uncertain_squares']
            text=("Uncertain: "+", ".join(uncertain[:10])+(f" (+{len(uncertain)-10} more)" if len(uncertain)>10 else "")) if uncertain else "All 64 squares meet the recognition threshold"
            ignored=snap.get('recognition_ignored_squares',[])
            if ignored:text='Continuity check • uncertain on '+', '.join(ignored)+'; previous legal pieces retained there'
            self.recognition_details.setText(text)
            self.recognition_details.setStyleSheet("color:"+("#f4c17a" if uncertain or ignored else "#8ee3ce"))
        mode=snap.get('recognition_mode')
        if mode and mode!=getattr(self,'_displayed_recognition_mode',None):
            self.recognizer_setting.setCurrentIndex(1 if mode=='calibrated' else 0)
            self._displayed_recognition_mode=mode
        if snap.get('confidence')==0:
            self.metric_labels['confidence'].setText('—')
            self.recognition_details.setText('Board not found • previous verified position preserved')
        if 'saved_count' in snap:self.metric_labels['saved'].setText(str(snap['saved_count']))
        display_fen=snap.get('preview_fen') or snap.get('fen')
        preview_moves=snap.get('preview_moves',[])
        preview_active=bool(preview_moves) or bool(display_fen and display_fen!=snap.get('fen'))
        preview_line=' '.join(preview_moves)
        candidates=snap.get('preview_candidates',0)
        last_move=snap.get('preview_last_move') or snap.get('last_move')
        if self._live_review:
            display_fen=self._live_review['fen'];last_move=self._live_review['last_move'];preview_active=False
        self.board_heading.setText('REVIEWING SELECTED MOVE • recording continues' if self._live_review else
                                  'PROVISIONAL BOARD PREVIEW • excluded from PGN' if preview_active else 'RECONSTRUCTED BOARD')
        render_key=(display_fen,last_move,snap.get('orientation'),preview_active)
        if display_fen and render_key!=getattr(self,'_last_board_render',None):
            self.live_board.show_board(display_fen,last_move,snap.get('orientation')=='black',preview_active);self._last_board_render=render_key
        elif not display_fen:
            self.live_board.show_pending();self._last_board_render=None
        self.last_move_label.setText(f"{len(moves)} verified plies  •  Last: {moves[-1] if moves else '—'}" if snap.get('fen') else "Waiting for a reliable first position • recording continues")
        pending=snap.get('pending_moves',[]) if snap.get('provisional') else []
        guessed=snap.get('guessed_plies',[])
        self.update_move_table(moves,snap.get('initial_fen',chess.STARTING_FEN),pending,guessed)
        selected=tuple(self._live_review.get('path',(0,)*self._live_review['ply'])) if self._live_review else (0,)*len(moves)
        self.live_notation.show_game(self._live_document,selected,follow=self._live_review is None,pending=pending)
        if preview_active:
            option=f" • candidate 1 of {candidates}" if candidates>1 else ""
            suffix=" • final confirmation needed" if snap.get('pending_terminal') else " • not yet in PGN"
            self.last_move_label.setText(f"{len(moves)} verified plies • preview: {preview_line or 'current legal position'}{option}{suffix}")
        if guessed:self.last_move_label.setText(self.last_move_label.text().replace('verified plies','PGN plies')+f' • {len(guessed)} plies inferred (≈)')
        if self._live_review:
            self.last_move_label.setText(f"Selected ply {self._live_review['ply']} • {self._live_review['prefix'][-1]} • live recording continues")
        options=snap.get('alternatives',[])
        if [self.alternatives.itemText(i) for i in range(self.alternatives.count())]!=options:
            self.alternatives.clear();self.alternatives.addItems(options)
        self.alternatives.setVisible(bool(options));self.choose_path.setVisible(bool(options));self.choose_path.setEnabled(not snap.get('incomplete',False))
        self.uncertain_label.setVisible(bool(options))
        self.uncertain_label.setText(('FINAL MOVE • confirm after review; excluded from PGN' if snap.get('pending_terminal') else 'PROVISIONAL MOVE • waiting for opponent reply; excluded from PGN') if snap.get('provisional') else 'UNVERIFIED POSSIBILITIES • excluded from PGN')
        self.choose_path.setText('Confirm final / pending move' if snap.get('provisional') else 'Confirm selected sequence')
        self.choose_path.setToolTip('Confirm only after seeing the piece released, or when reviewing the final move. This overrides reply-based confirmation.')
        if snap.get('clocks'):
            def clock_text(seconds):
                return f'{int(seconds)//60}:{int(seconds)%60:02d}'
            self.recovery.setText('Observed clocks • '+ '  |  '.join(color.title()+' ('+snap.get('players',{}).get(color,'Unknown')+'): '+clock_text(seconds) for color,seconds in snap['clocks'].items())+' • saved in PGN clock comments')
        self.delay_label.setText(f"Processing {snap.get('processing_ms',0)} ms  •  {snap.get('orientation','auto').title()} at bottom")

    def update_move_table(self,moves,fen,pending=(),guessed=()):
        key=(fen,tuple(moves),tuple(pending),tuple(guessed))
        if key==getattr(self,'_last_moves_render',None):return
        self._last_moves_render=key
        self.move_table.clearContents()
        initial=chess.Board(fen);start=initial.fullmove_number;black_first=not initial.turn
        rows=(len(moves)+len(pending)+(1 if black_first else 0)+1)//2
        self.move_table.setRowCount(rows)
        for row in range(rows):self.move_table.setItem(row,0,QTableWidgetItem(str(start+row)))
        for i,san in enumerate(list(moves)+list(pending)):
            index=i+(1 if black_first else 0)
            prefix='… ' if i>=len(moves) else ('≈ ' if i+1 in guessed else '✓ ')
            item=QTableWidgetItem(prefix+san)
            item.setData(Qt.UserRole,i+1)
            if i>=len(moves):item.setForeground(QColor('#f4c17a'));item.setToolTip('Provisional: a held piece can look like a move. Not included in PGN until confirmed.')
            elif i+1 in guessed:
                item.setForeground(QColor('#f4c17a'));item.setToolTip('Guessed opening prefix included in PGN. Shortest legal line with pawn moves prioritized; earlier move order may differ.')
            self.move_table.setItem(index//2,1+index%2,item)
        if rows and not self._live_review:self.move_table.scrollToBottom()

    def review_live_move(self,item):
        ply=item.data(Qt.UserRole)
        if not ply:return
        snap=self.snapshot;line=snap.get('moves',[])+(snap.get('pending_moves',[]) if snap.get('provisional') else [])
        if ply>=len(snap.get('moves',[])):
            self.return_to_live_board();return
        initial=snap.get('initial_fen',chess.STARTING_FEN);board=chess.Board(initial)
        try:
            for san in line[:ply]:board.push_san(san)
        except ValueError:return
        self._live_review={'game_id':snap.get('game_id'),'initial_fen':initial,'ply':ply,
            'prefix':tuple(line[:ply]),'fen':board.fen(),'last_move':board.peek().uci()}
        self.on_update(snap)

    def review_notation_move(self,path):
        path=tuple(path)
        if path==(0,)*len(self.snapshot.get('moves',[])):
            self.return_to_live_board();return
        try:node=node_at(self._live_document,path)
        except (IndexError,AttributeError):return
        board=node.board();prefix=[];cursor=node
        while cursor.parent is not None:prefix.append(cursor.san());cursor=cursor.parent
        self._live_review={'game_id':self.snapshot.get('game_id'),'initial_fen':self._live_document.board().fen(),
            'ply':len(path),'path':path,'prefix':tuple(reversed(prefix)) or ('Starting position',),
            'fen':board.fen(),'last_move':node.move.uci() if node.move else None}
        self.on_update(self.snapshot)

    def navigate_live_move(self,direction):
        snap=self.snapshot
        line=snap.get('moves',[])+(snap.get('pending_moves',[]) if snap.get('provisional') else [])
        if not line:return
        current=self._live_review['ply'] if self._live_review else max(1,len(snap.get('moves',[])))
        target=max(1,min(len(line),current+direction))
        initial=chess.Board(snap.get('initial_fen',chess.STARTING_FEN))
        table_index=target-1+(1 if not initial.turn else 0)
        item=self.move_table.item(table_index//2,1+table_index%2)
        if item:
            self.move_table.setCurrentItem(item);self.move_table.scrollToItem(item)
            self.review_live_move(item)

    def return_to_live_board(self):
        self._live_review=None;self._last_board_render=None
        self.on_update(self.snapshot);self.move_table.scrollToBottom()

    def sources(self):
        physical=monitors();result=[]
        for i,screen in enumerate(QApplication.screens()):
            match=next((p for p in physical if p['name']==screen.name()),physical[min(i,len(physical)-1)])
            result.append((screen,match))
        return result

    def draw_region(self):
        try:
            self.overlay_was_paused=not self.worker or self.worker.paused.is_set()
            if self.worker:self.worker.paused.set()
            self.hide()
            for screen,physical in self.sources():
                overlay=DrawOverlay(screen,physical);overlay.selected.connect(self.region_selected);overlay.cancelled.connect(self.close_overlays);self.overlays.append(overlay);overlay.show();overlay.activateWindow()
        except Exception as e:self.show();self.error(str(e))

    def adjust_region(self):
        if not self.region:self.draw_region();return
        if self.region.window:self.draw_region();return
        try:
            screen,physical=next(((s,p) for s,p in self.sources() if p['left']<=self.region.left<p['left']+p['width']),self.sources()[0])
            self.overlay_was_paused=not self.worker or self.worker.paused.is_set()
            if self.worker:self.worker.paused.set()
            self.hide();overlay=RegionEditor(self.region,screen,physical);overlay.selected.connect(self.region_selected);overlay.cancelled.connect(self.close_overlays);self.overlays.append(overlay);overlay.show();overlay.activateWindow()
        except Exception as e:self.show();self.error(str(e))

    def close_overlays(self):
        for overlay in self.overlays:overlay.close();overlay.deleteLater()
        self.overlays=[];self.show();self.activateWindow()
        if self.worker and not getattr(self,'overlay_was_paused',True):self.worker.paused.clear()

    def region_selected(self,region):
        self._auto_window_enabled=False
        self.auto_window_timer.stop()
        if not region.window:region.tracking_window=containing_window(region)
        self.region=region;self.settings.region=asdict(region);self.settings.save(self.root/"settings.json");self.source_label.setText(self.region_text())
        if self.worker and self.worker.isRunning():self.worker.commands.put(("region",region))
        self.close_overlays()
        if not self.worker or not self.worker.isRunning():self.start_preview()

    def auto_region(self,region):
        self.region=region;self.settings.region=asdict(region);self.settings.save(self.root/'settings.json');self.source_label.setText(self.region_text()+' • reacquired after layout change')

    def choose_monitor(self):
        try:
            options=monitors();names=[f"{m['name']} — {m['width']} × {m['height']}" for m in options]
            name,ok=QInputDialog.getItem(self,"Capture monitor","Choose a visible monitor; the board will be detected within it.",names,0,False)
            if ok:
                m=options[names.index(name)];self.region_selected(Region(m['left'],m['top'],m['width'],m['height']))
        except Exception as e:self.error(str(e))

    def choose_window(self):
        try:
            options=rank_capture_windows(windows())
            if not options:self.error("Window selection requires Windows. Draw a screen region on this platform.");return
            names=[name for _,name in options];name,ok=QInputDialog.getItem(self,"Track application window","Keep the selected window visible. Its position and size are followed.",names,0,False)
            if ok:self.region_selected(window_client(options[names.index(name)][0]))
        except Exception as e:self.error(str(e))

    def _auto_select_youtube_window(self):
        """Select the most chess-relevant visible YouTube browser window."""
        if not self._auto_window_enabled:
            self.auto_window_timer.stop();return bool(self.region)
        for hwnd,title in rank_youtube_windows(windows()):
            try:
                region=window_client(hwnd)
                if region.width < 200 or region.height < 200:continue
            except (OSError,RuntimeError):
                continue
            self.region=region
            if hasattr(self,"source_label"):self.source_label.setText(self.region_text())
            if self.worker and self.worker.isRunning():self.worker.commands.put(("region",region))
            self.auto_window_timer.stop()
            if hasattr(self,"statusBar"):
                self.statusBar().showMessage(f"Auto-selected YouTube window: {title} • "+
                    ('armed to record the first opening move' if self.settings.auto_record_opening else 'click Start recording when ready'),10000)
            logging.info("Automatically selected YouTube capture window hwnd=%s title=%r",hwnd,title)
            self.start_preview()
            return True
        return False

    def flip_orientation(self):
        current=self.snapshot.get('orientation','white');self.settings.orientation='black' if current=='white' else 'white'
        self.orientation_setting.setCurrentText(self.settings.orientation);self.settings.save(self.root/"settings.json")
        if self.worker:self.worker.commands.put(("region",self.region))

    def calibrate(self):
        if self.latest_image is None:self.error("Start capture and show the standard starting position first.");return
        dialog=QMessageBox(self);dialog.setWindowTitle("Learn this piece set");dialog.setText("The visible board MUST be the standard starting position, with all 32 pieces on their original squares. This labels the pieces from that layout.");dialog.setInformativeText("Optional fallback: this switches to manually learned templates. The bundled screenshot model is recommended for common Chess.com and Lichess themes. Choose the color at the bottom; return to the bundled model in Settings.")
        white=dialog.addButton("White at bottom",QMessageBox.AcceptRole);black=dialog.addButton("Black at bottom",QMessageBox.AcceptRole);dialog.addButton(QMessageBox.Cancel);dialog.exec()
        chosen=dialog.clickedButton()
        if chosen not in [white,black]:return
        if self.worker and self.worker.isRunning():self.worker.commands.put(("calibrate",(self.latest_image.copy(),'white' if chosen==white else 'black')))
        else:
            from .vision import TemplateRecognizer
            TemplateRecognizer.calibrate(self.latest_image,self.root/'custom-templates.npz','white' if chosen==white else 'black')
            self.settings.recognition_mode='calibrated';self.settings.onnx_model='';self.model.clear();self.settings.save(self.root/'settings.json');self.recognizer_setting.setCurrentIndex(1)
        self.statusBar().showMessage("Piece templates calibrated. Show the board clearly to verify recognition.",8000)

    def choose_sequence(self):
        if self.worker and self.worker.isRunning():self.worker.commands.put(("choose",self.alternatives.currentIndex()))
        else:self.manager.choose(self.alternatives.currentIndex());self.on_update(self.manager.snapshot())

    def correct_moves(self):
        if not self.manager.rec:self.error('Capture a valid position first.');return
        d=QDialog(self);d.setWindowTitle('Correct the verified move history');d.setMinimumWidth(530);form=QFormLayout(d)
        revision=len(self.manager.rec.verified)
        form.addRow(muted('If necessary, undo recent plies before entering the correct legal SAN sequence. A ply is one move by one player. Screenshots are preserved and the correction is audited.'))
        undo=QSpinBox();undo.setRange(0,len(self.manager.rec.verified));form.addRow('Undo recent verified plies',undo)
        san=QLineEdit();san.setPlaceholderText('Legal SAN, such as e4 e5 Nf3');form.addRow('Then append these moves',san)
        controls=QDialogButtonBox(QDialogButtonBox.Apply|QDialogButtonBox.Cancel);controls.button(QDialogButtonBox.Apply).clicked.connect(d.accept);controls.rejected.connect(d.reject);form.addRow(controls)
        if d.exec() and (san.text().strip() or undo.value()):
            try:
                value=(san.text().strip(),undo.value(),revision)
                if self.worker and self.worker.isRunning():self.worker.commands.put(("correct",value))
                else:self.manager.correct_line(*value);self.on_update(self.manager.snapshot())
            except Exception as e:self.error(str(e))

    def new_game(self):
        if QMessageBox.question(self,"Start PGN from visible FEN?","Save the current PGN and start a new PGN from the visible board as its starting FEN? Moves before this position are not added to the new PGN. All existing game data and screenshots are kept.")!=QMessageBox.Yes:return
        try:
            if self.worker and self.worker.isRunning():self.worker.commands.put(("new",None))
            else:self.manager.force_new();self.on_update(self.manager.snapshot())
        except Exception as e:self.error(str(e))

    def copy_visible_fen(self):
        candidates=self.manager.visible_fens()
        if not candidates:
            self.error("Capture a clear, stable board first.");return
        fen=candidates[0]
        if len(candidates)>1:
            labels=[("White to move" if chess.Board(value).turn else "Black to move")+"  •  "+value for value in candidates]
            choice,ok=QInputDialog.getItem(self,"Copy visible FEN","The board image cannot show whose turn it is. Choose the side to move:",labels,0,False)
            if not ok:return
            fen=candidates[labels.index(choice)]
        QApplication.clipboard().setText(fen)
        self.statusBar().showMessage("Visible position FEN copied",6000)

    def build_library(self):
        page,box=self.page("Your game library","Every game is saved locally. Screenshot deletion leaves these games and PGNs intact.")
        bar=QHBoxLayout()
        for name,fn in [("Combine selected PGNs",self.join_selected),("Export selected",self.export_selected),("Export entire session",self.export_session),("Export all",self.export_all),("Open PGN…",self.import_pgn),("Refresh",self.refresh_library)]:bar.addWidget(button(name,fn))
        bar.addStretch();box.addLayout(bar)
        self.game_table=QTableWidget(0,7);self.game_table.setHorizontalHeaderLabels(["Game","Date","Duration","Plies","Status","Result","Saved .pgn"]);self.game_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents);self.game_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);self.game_table.setSelectionBehavior(QAbstractItemView.SelectRows);self.game_table.setSelectionMode(QAbstractItemView.ExtendedSelection);self.game_table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.game_table.verticalHeader().hide();self.game_table.itemSelectionChanged.connect(self.show_game);self.game_table.setContextMenuPolicy(Qt.CustomContextMenu);self.game_table.customContextMenuRequested.connect(self.game_context_menu)
        box.addWidget(self.game_table,2)
        detail=QSplitter(Qt.Horizontal);self.library_board=BoardView();detail.addWidget(self.library_board);detail.addWidget(self.make_review_tabs());detail.setSizes([350,650]);box.addWidget(detail,2)
        timeline=QHBoxLayout();timeline.addWidget(QLabel("Review ply"));self.review_slider=QSlider(Qt.Horizontal);self.review_slider.valueChanged.connect(self.review_game);timeline.addWidget(self.review_slider,1);self.review_label=muted("0");timeline.addWidget(self.review_label);box.addLayout(timeline)
        actions=QHBoxLayout()
        for name,fn in [("Rename / edit headers",self.edit_game),("Copy PGN",self.copy_selected),("Resume recording",self.resume_game),("Screenshots",self.game_screenshots)]:actions.addWidget(button(name,fn))
        actions.addWidget(button("Remove saved .pgn copies…",self.delete_saved_pgns,danger=True))
        actions.addStretch();actions.addWidget(button("Delete from library…",self.delete_games,danger=True));box.addLayout(actions)
        variations=QHBoxLayout()
        for label,fn in [('Add alternative line…',self.add_review_variation),('Edit comment…',self.edit_review_comment),('Remove alternative line',self.delete_review_variation)]:variations.addWidget(button(label,fn))
        variations.addWidget(muted('Select a position before an existing move; alternatives are saved in exported PGNs.'));box.addLayout(variations)
        self.game_rows=[]

    def refresh_library(self):
        self.game_rows=self.store.games();self.game_table.setRowCount(len(self.game_rows))
        for row,g in enumerate(self.game_rows):
            duration='—'
            if g['ended']:
                seconds=max(0,int((datetime.fromisoformat(g['ended'])-datetime.fromisoformat(g['started'])).total_seconds()));duration=f"{seconds//60}:{seconds%60:02d}"
            values=[g['name'],local_time(g['started']),duration,str(g['plies']),g['status'],json.loads(g['headers']).get('Result','*'),('Yes' if (self.store.root/'pgn'/(g['id']+'.pgn')).is_file() else 'No')]
            for col,value in enumerate(values):self.game_table.setItem(row,col,QTableWidgetItem(value))

    def selected_games(self):
        return [self.game_rows[i.row()] for i in self.game_table.selectionModel().selectedRows() if i.row()<len(self.game_rows)]

    def game_context_menu(self,pos):
        item=self.game_table.itemAt(pos)
        if item is None:return
        self.select_context_game(item.row())
        self.game_row_menu().exec(self.game_table.viewport().mapToGlobal(pos))

    def select_context_game(self,row):
        selected_rows={index.row() for index in self.game_table.selectionModel().selectedRows()}
        if row not in selected_rows:
            self.game_table.clearSelection();self.game_table.selectRow(row)

    def game_row_menu(self):
        menu=QMenu(self)
        menu.addAction("Copy PGN",self.copy_selected)
        menu.addAction("Export selected…",self.export_selected)
        action=menu.addAction("Join selected recordings…",self.join_selected)
        action.setEnabled(len(self.selected_games())>=2)
        menu.addSeparator()
        menu.addAction("Remove saved .pgn copies…",self.delete_saved_pgns)
        menu.addAction("Delete game(s) from library…",self.delete_games)
        return menu

    def show_game(self):
        selected=self.selected_games()
        if not selected:return
        self.populate_review(selected[0])

    def review_game(self):
        self.slider_review()


    def edit_game(self):
        selected=self.selected_games()
        if not selected:return
        g=selected[0];headers=json.loads(g['headers']);d=QDialog(self);d.setWindowTitle("Game details");d.setMinimumWidth(430);form=QFormLayout(d);name=QLineEdit(g['name']);form.addRow("Game name",name);fields={}
        for key in ['White','Black','WhiteElo','BlackElo','Event','Site','Date','TimeControl']:
            fields[key]=QLineEdit(headers.get(key,''));form.addRow(key,fields[key])
        result=QComboBox();result.addItems(['*','1-0','0-1','1/2-1/2']);result.setCurrentText(headers.get('Result','*'));form.addRow('Result',result)
        form.addRow(muted("Resignation and timeout cannot be proved from pieces alone. Set the result when known."))
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);form.addRow(buttons)
        if d.exec():
            for key,field in fields.items():
                value=field.text().strip()
                if value:headers[key]=value
                elif key in ['White','Black']:headers[key]='Unknown'
                elif key=='Date':headers[key]='????.??.??'
                elif key in ['Event','Site']:headers[key]='?'
                else:headers.pop(key,None)
            headers['Result']=result.currentText()
            try:self.manager.edit(g['id'],name.text().strip() or g['name'],headers);self.refresh_library()
            except Exception as e:self.error(str(e))

    def resume_game(self):
        selected=self.selected_games()
        if not selected:return
        if self.worker and self.worker.isRunning():self.error("Stop the current capture before resuming another game.");return
        try:self.manager.recover(selected[0]['id']);self.on_update(self.manager.snapshot());self.navigate(0)
        except Exception as e:self.error(str(e))

    def game_screenshots(self):
        selected=self.selected_games()
        if not selected:return
        gid=selected[0]['id'];self.navigate(2)
        index=self.shot_game.findData(gid)
        if index>=0:self.shot_game.setCurrentIndex(index)

    def delete_games(self):
        selected=self.selected_games()
        if not selected:return
        if any(g['id']==self.manager.current_id for g in selected) and self.worker and self.worker.isRunning():self.error("Stop capture before deleting its game data.");return
        if QMessageBox.warning(self,"Delete game data?",f"Delete {len(selected)} game(s), their move histories, and their internal autosaved PGNs? Screenshots are kept. PGNs you exported elsewhere are kept.",QMessageBox.Yes|QMessageBox.Cancel)!=QMessageBox.Yes:return
        for g in selected:
            self.store.delete_game(g['id'])
            if g['id']==self.manager.current_id:self.manager=GameManager(self.store,self.settings)
        self.refresh_library()
        self.statusBar().showMessage(f"Deleted {len(selected)} game(s) from the library; screenshots kept.",10000)

    def delete_saved_pgns(self):
        selected=self.selected_games()
        if not selected:return
        if any(g['id']==self.manager.current_id for g in selected) and self.worker and self.worker.isRunning():
            self.error("Stop capture before deleting the active game's PGN file.");return
        count=len(selected)
        text=(f"Delete the app-saved PGN file(s) for {count} selected game(s)?\n\n"
              "This removes ChessStream's local autosave and matching per-game files in the configured automatic-export folder. "
              "Game details, move history, screenshots, and manually exported PGN files are kept. "
              "The app can recreate an automatic save if you later resume or change a game.")
        if QMessageBox.warning(self,"Delete saved PGN files?",text,
                QMessageBox.Yes|QMessageBox.Cancel)!=QMessageBox.Yes:return
        try:
            deleted=self.store.delete_pgn_files([g['id'] for g in selected],self.settings.export_dir)
            self.refresh_library()
            self.statusBar().showMessage(f"Removed {len(deleted)} saved .pgn file(s). Game entries remain; choose Delete from library to remove entries.",15000)
        except Exception as e:self.error(str(e))

    def write_export(self,rows):
        if not rows:self.error("No games selected or recorded yet.");return
        path,_=QFileDialog.getSaveFileName(self,"Export standards-compliant PGN",str(Path.home()/"ChessStream.pgn"),"PGN files (*.pgn)")
        if path:
            try:atomic_text(Path(path),"\n\n".join(g['pgn'].strip() for g in rows)+"\n");self.statusBar().showMessage(f"Exported {len(rows)} game(s) to {path}",10000)
            except Exception as e:self.error(str(e))

    def export_current(self):
        g=self.store.game(self.manager.current_id);self.write_export([g] if g else [])
    def export_selected(self):self.write_export(self.selected_games())
    def join_selected(self):
        selected=self.selected_games()
        if len(selected)<2:
            self.error('Ctrl-click two or more recordings, then choose Join selected recordings.');return
        capture_running=bool(self.worker and self.worker.isRunning())
        if capture_running and any(g['id']==self.manager.current_id for g in selected):
            self.error('The active PGN is still changing. Select older saved PGNs to combine while recording continues.');return
        if getattr(self,'_library_join_cancel',None) and not self._library_join_cancel.is_set():
            self.statusBar().showMessage('A saved-PGN join is already running',6000);return
        self._library_join_cancel=threading.Event()
        cancelled=self._library_join_cancel
        original_manager=self.manager
        original_game=self.manager.current_id
        revision=self.manager._evidence_revision
        def saved(pgn):
            cancelled.set()
            running=bool(self.worker and self.worker.isRunning())
            for source in selected:
                latest=self.store.game(source['id'])
                if not latest or latest['pgn']!=source['pgn']:
                    self.error('A source PGN changed during the join; originals preserved. Please retry.');return
            if running and any(g['id']==self.manager.current_id for g in selected):
                self.error('A selected PGN is now recording. Stop capture before combining it.');return
            activate=(not running and not capture_running and self.manager is original_manager
                      and self.manager.current_id==original_game and self.manager._evidence_revision==revision)
            self.manager.combine_games(selected,pgn,activate=activate)
            self.refresh_library()
            if not activate:
                self.statusBar().showMessage('Older PGNs combined • live recording continues unchanged',8000)
            else:
                self.on_update(self.manager.snapshot())
                self.navigate(0)
        def search(confirmed):
            try:
                return {'pgn':join_recordings(selected,original_manager.searcher(),confirmed,cancelled=cancelled.is_set)}
            except AmbiguousGapError as error:
                return {'ambiguous':error}
            except ValueError as error:
                return {'error':str(error)}

        def result(outcome,confirmed=None):
            if self._closing:return
            # Older UI/test callbacks pass the completed PGN directly.
            if isinstance(outcome,str):
                saved(outcome)
                return
            if 'pgn' in outcome:
                saved(outcome['pgn'])
                return
            if 'error' in outcome:
                cancelled.set();self.error(outcome['error']);return
            error=outcome['ambiguous']
            if not error.source_fen or error.later_id is None or len(error.alternatives)>32:
                cancelled.set()
                self.error(str(error)+' Too many choices to safely display; originals kept.')
                return
            options=[]
            for path in error.alternatives:
                board=chess.Board(error.source_fen)
                names=[]
                for uci in path:
                    move=chess.Move.from_uci(uci)
                    names.append(board.san(move))
                    board.push(move)
                options.append(' '.join(names) or '(no missing moves)')
            labels=[f"{i+1}. {name}" for i,name in enumerate(options)]
            answer,ok=QInputDialog.getItem(self,'Verify unobserved chess moves',
                'This unobserved gap needs verification. Only select a line '
                'if you can verify its moves from the video. Cancel to preserve both PGNs.',
                labels,0,False)
            if not ok:
                cancelled.set()
                self.statusBar().showMessage('PGN join canceled • original recordings retained',8000)
                return
            selection=labels.index(answer)
            overrides=dict(confirmed or {})
            overrides[error.later_id]=error.alternatives[selection]
            self.background(lambda:search(overrides),lambda next_result:result(next_result,overrides))

        self.background(lambda:search({}),result)
    def export_all(self):self.write_export(list(reversed(self.store.games())))
    def export_session(self):
        selected=self.selected_games()
        sid=selected[0]['session_id'] if selected else self.manager.session_id
        self.write_export(list(reversed([g for g in self.store.games() if g['session_id']==sid])))
    def copy_current(self):
        g=self.store.game(self.manager.current_id)
        if g:QApplication.clipboard().setText(g['pgn']);self.statusBar().showMessage("PGN copied",3000)
    def copy_selected(self):
        selected=self.selected_games()
        if selected:QApplication.clipboard().setText('\n\n'.join(g['pgn'] for g in selected))
    def import_pgn(self):
        path,_=QFileDialog.getOpenFileName(self,"Open existing PGN","","PGN files (*.pgn);;All files (*)")
        if path:
            try:count=self.manager.import_pgn(Path(path));self.refresh_library();self.statusBar().showMessage(f"Imported {count} game(s)",6000)
            except Exception as e:self.error(str(e))

    def build_screenshots(self):
        page,box=self.page("Screenshots, on your terms","Saved screenshots stay here until you delete them or explicitly enable a retention policy. Extra adaptive frames are never stored as images.")
        bar=QHBoxLayout();self.shot_game=QComboBox();self.shot_game.setMinimumWidth(240);self.shot_game.currentIndexChanged.connect(self.refresh_shot_list);bar.addWidget(self.shot_game);bar.addWidget(button("Refresh",self.refresh_screenshots));bar.addStretch();bar.addWidget(button("Open storage folder",lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.images)))));box.addLayout(bar)
        self.storage_info=muted("");box.addWidget(self.storage_info)
        split=QSplitter(Qt.Horizontal);self.shot_list=QListWidget();self.shot_list.setIconSize(QSize(76,76));self.shot_list.setSelectionMode(QAbstractItemView.ExtendedSelection);self.shot_list.currentRowChanged.connect(self.show_screenshot);self.shot_list.itemSelectionChanged.connect(self.update_screenshot_actions);self.shot_list.setContextMenuPolicy(Qt.CustomContextMenu);self.shot_list.customContextMenuRequested.connect(self.screenshot_row_menu);split.addWidget(self.shot_list)
        detail=QWidget();dbox=QVBoxLayout(detail);self.shot_image=ImageView();self.shot_image.double_clicked.connect(self.full_screenshot);dbox.addWidget(self.shot_image,1)
        shot_detail=QHBoxLayout();self.shot_board=BoardView();self.shot_board.setFixedSize(170,170);shot_detail.addWidget(self.shot_board)
        self.shot_info=muted("Select a screenshot to review its position and move association. Double-click the image for full resolution.");self.shot_info.setTextInteractionFlags(Qt.TextSelectableByMouse);shot_detail.addWidget(self.shot_info,1);dbox.addLayout(shot_detail);split.addWidget(detail);split.setSizes([310,700]);box.addWidget(split,1)
        timeline=QHBoxLayout();timeline.addWidget(QLabel("Timeline"));self.shot_slider=QSlider(Qt.Horizontal);self.shot_slider.valueChanged.connect(self.shot_list.setCurrentRow);timeline.addWidget(self.shot_slider,1);timeline.addWidget(button("Older screenshots",self.older_shots));box.addLayout(timeline)
        bottom=QHBoxLayout();self.delete_shots_button=button("Delete selected screenshots…",self.delete_selected_screenshots,danger=True);self.delete_shots_button.setEnabled(False);bottom.addWidget(self.delete_shots_button);bottom.addWidget(button("Delete by scope…",lambda:self.deletion_dialog(False),danger=True));bottom.addWidget(button("Schedule deletion…",lambda:self.deletion_dialog(True)));bottom.addWidget(button("Scheduled jobs…",self.scheduled_jobs));bottom.addStretch();bottom.addWidget(muted("PGNs, moves and game details are preserved"));box.addLayout(bottom)
        self.shot_rows=[];self.shot_before=None

    def refresh_screenshots(self):
        gid=self.shot_game.currentData();self.shot_game.blockSignals(True);self.shot_game.clear();self.shot_game.addItem("All games and unassigned captures",None)
        for g in self.store.games():self.shot_game.addItem(g['name']+'  •  '+local_time(g['started']),g['id'])
        self.shot_game.setCurrentIndex(max(0,self.shot_game.findData(gid)));self.shot_game.blockSignals(False);self.shot_before=None;self.refresh_shot_list();self.refresh_usage()

    def refresh_shot_list(self):
        scope={};gid=self.shot_game.currentData()
        if gid:scope['game_id']=gid
        if getattr(self,'shot_before',None):scope['before']=self.shot_before
        self.shot_rows=self.store.screenshots(scope,limit=200);self.shot_list.clear()
        for s in self.shot_rows:
            item=QListWidgetItem(f"#{s['sequence']:05d}   {local_time(s['timestamp'])}\nSimilarity: {s['confidence']*100:.1f}%" if s['confidence'] is not None else f"#{s['sequence']:05d}   {local_time(s['timestamp'])}\nBoard not found")
            try:pix=QPixmap(str(self.store.screenshot_file(s['path'])))
            except (OSError,ValueError) as exc:logging.warning('Skipping invalid screenshot path: %s',exc);pix=QPixmap()
            item.setIcon(QIcon(pix.scaled(76,76,Qt.KeepAspectRatio,Qt.SmoothTransformation)));item.setSizeHint(QSize(260,90));self.shot_list.addItem(item)
        self.shot_slider.setRange(0,max(0,len(self.shot_rows)-1))
        if self.shot_rows:
            self.shot_list.setCurrentRow(0)
            self.shot_list.clearSelection()
        self.update_screenshot_actions()

    def update_screenshot_actions(self):
        if hasattr(self,'delete_shots_button'):
            self.delete_shots_button.setEnabled(bool(self.shot_list.selectedItems()))

    def screenshot_row_menu(self,position):
        item=self.shot_list.itemAt(position)
        if item is None:return
        if not item.isSelected():
            self.shot_list.clearSelection();item.setSelected(True);self.shot_list.setCurrentItem(item)
        menu=QMenu(self.shot_list)
        delete=menu.addAction('Delete selected screenshot(s)…')
        delete.triggered.connect(self.delete_selected_screenshots)
        menu.exec(self.shot_list.mapToGlobal(position))

    def delete_selected_screenshots(self):
        ids=self.selected_screenshot_ids()
        if not ids:return
        estimate=self.store.deletion_estimate({'ids':ids})
        answer=QMessageBox.warning(self,'Delete selected screenshots?',
            f'Permanently delete {estimate["count"]} selected screenshot files ({human_bytes(estimate["bytes"])}). '
            'Screenshot metadata will be marked deleted. PGNs, moves, and game details will be kept.',
            QMessageBox.Yes|QMessageBox.Cancel)
        if answer!=QMessageBox.Yes:return
        self.background(lambda:self.store.delete_screenshots({'ids':ids}),
            lambda result:(self.refresh_screenshots(),self.statusBar().showMessage(
                f'Deleted {result["count"]} selected screenshots. PGNs kept.',8000)))

    def selected_screenshot_ids(self):
        return [int(self.shot_rows[self.shot_list.row(item)]['id']) for item in self.shot_list.selectedItems()
                if 0<=self.shot_list.row(item)<len(self.shot_rows)]

    def older_shots(self):
        if self.shot_rows:self.shot_before=self.shot_rows[-1]['timestamp'];self.refresh_shot_list()

    def show_screenshot(self,index):
        if index<0 or index>=len(self.shot_rows):return
        s=self.shot_rows[index]
        try:self.shot_image.set_file(self.store.screenshot_file(s['path']))
        except (OSError,ValueError) as exc:self.error(f"Could not open saved screenshot: {exc}");return
        self.shot_slider.blockSignals(True);self.shot_slider.setValue(index);self.shot_slider.blockSignals(False)
        g=self.store.game(s['game_id']) if s['game_id'] else None
        text=f"{local_time(s['timestamp'])}   •   Sequence {s['sequence']}   •   {g['name'] if g else 'Unassigned / game data deleted'}\n"
        text+=f"Observed placement: {s['fen'] or 'Unavailable'}\nVerified ply at capture: {s['move_ply'] or 0}   •   {human_bytes(s['bytes'])}\n{self.root/s['path']}"
        if s['fen']:
            self.shot_board.show_board(s['fen'] if ' ' in s['fen'] else s['fen']+' w - - 0 1')
        if g:
            state=json.loads(g['state']);b=chess.Board(state['initial_fen']);san=[]
            for uci in state['verified'][:s['move_ply'] or 0]:san.append(b.san(chess.Move.from_uci(uci)));b.push_uci(uci)
            text+='\nRecent verified moves: '+' '.join(san[-6:])
        self.shot_info.setText(text)

    def full_screenshot(self):
        i=self.shot_list.currentRow()
        if i<0 or i>=len(self.shot_rows):return
        try:path=self.store.screenshot_file(self.shot_rows[i]['path'])
        except (OSError,ValueError) as exc:self.error(f"Could not open saved screenshot: {exc}");return
        d=QDialog(self);d.setWindowTitle('Full-resolution screenshot');d.resize(1000,850);layout=QVBoxLayout(d);scroll=QScrollArea();label=QLabel();label.setPixmap(QPixmap(str(path)));scroll.setWidget(label);layout.addWidget(scroll);layout.addWidget(muted('Original image, one image pixel per display pixel. Scroll to inspect.'));d.exec()

    def deletion_dialog(self,scheduled):
        d=QDialog(self);d.setWindowTitle("Schedule screenshot deletion" if scheduled else "Delete screenshots");d.setMinimumWidth(530);form=QFormLayout(d)
        scope_box=QComboBox();scope_box.addItems(["One game","Entire session","Older than date","Within time range","All screenshots"]);form.addRow("Scope",scope_box)
        games=QComboBox()
        for g in self.store.games():games.addItem(g['name']+' • '+local_time(g['started']),g['id'])
        form.addRow("Game",games)
        sessions=QComboBox()
        for s in self.store.query("SELECT * FROM sessions ORDER BY started DESC"):sessions.addItem(local_time(s['started'])+' • '+s['id'][:8],s['id'])
        form.addRow("Session",sessions)
        start=QDateTimeEdit(QDateTime.currentDateTime().addDays(-7));end=QDateTimeEdit(QDateTime.currentDateTime());due=QDateTimeEdit(QDateTime.currentDateTime().addDays(1))
        for edit in [start,end,due]:edit.setCalendarPopup(True);edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        form.addRow("From (inclusive)",start);form.addRow("Before (exclusive)",end)
        if scheduled:form.addRow("Delete at (local time)",due)
        description=muted("Only image files in the screenshot storage folder will be deleted. Metadata records remain marked deleted. PGNs, move histories, game details and exports are kept.")
        form.addRow(description);estimate=QLabel();form.addRow(estimate)
        def utc(edit):return edit.dateTime().toPython().astimezone(timezone.utc).isoformat(timespec='milliseconds')
        def scope():
            i=scope_box.currentIndex()
            return ({'game_id':games.currentData()} if i==0 else {'session_id':sessions.currentData()} if i==1 else {'before':utc(end)} if i==2 else {'after':utc(start),'before':utc(end)} if i==3 else {})
        def update():
            i=scope_box.currentIndex();games.setEnabled(i==0);sessions.setEnabled(i==1);start.setEnabled(i==3);end.setEnabled(i in [2,3]);n=self.store.deletion_estimate(scope());estimate.setText(f"Currently matches {n['count']} screenshots • {human_bytes(n['bytes'])}")
        for control in [scope_box,games,sessions]:control.currentIndexChanged.connect(update)
        start.dateTimeChanged.connect(update);end.dateTimeChanged.connect(update);update()
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);form.addRow(buttons)
        if not d.exec():return
        selected_scope=scope()
        if scope_box.currentIndex()==0 and not games.currentData():self.error("Select a game.");return
        if scope_box.currentIndex()==1 and not sessions.currentData():self.error("Select a session.");return
        n=self.store.deletion_estimate(selected_scope)
        text=f"{'Schedule deletion of' if scheduled else 'Permanently delete'} {n['count']} matching screenshots ({human_bytes(n['bytes'])})?\n\nPGNs, moves, and game metadata are kept."
        if scheduled:text+='\nThe job will include any additional screenshots matching this scope when it runs. If the app is closed, it runs next time you open it.'
        if QMessageBox.warning(self,"Confirm screenshot deletion",text,QMessageBox.Yes|QMessageBox.Cancel)!=QMessageBox.Yes:return
        if scheduled:
            self.store.schedule_deletion(utc(due),selected_scope);self.statusBar().showMessage("Deletion scheduled and saved across restarts",8000)
        else:self.background(lambda:self.store.delete_screenshots(selected_scope),lambda result:(self.refresh_screenshots(),self.statusBar().showMessage(f"Deleted {result['count']} screenshots. PGNs kept.",8000)))

    def scheduled_jobs(self):
        rows=self.store.query("SELECT * FROM deletion_jobs WHERE completed IS NULL ORDER BY due")
        if not rows:QMessageBox.information(self,"Scheduled deletions","No pending deletion jobs.");return
        names=[f"{r['id']} • {local_time(r['due'])} • {r['scope']}" for r in rows]
        choice,ok=QInputDialog.getItem(self,"Scheduled deletions","Choose a job to cancel. Cancel closes without changing it.",names,0,False)
        if ok and QMessageBox.question(self,"Cancel deletion job?",choice)==QMessageBox.Yes:self.store.cancel_deletion(rows[names.index(choice)]['id'])

    def build_settings(self):
        page,box=self.page("Settings","Tune capture, recognition and storage. Processing is local; no account is required.")
        tabs=QTabWidget();box.addWidget(tabs,1)
        def tab(name):
            widget=QWidget();layout=QFormLayout(widget);layout.setContentsMargins(24,24,24,24);layout.setVerticalSpacing(18);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(widget);tabs.addTab(scroll,name);return layout
        capture=tab("Capture & recognition")
        self.auto_record_opening=QCheckBox('Start recording automatically when an opening move appears')
        self.auto_record_opening.setChecked(self.settings.auto_record_opening)
        capture.addRow('Automatic recording',self.auto_record_opening)
        self.infer_unseen_opening=QCheckBox('Recover unseen opening only when its move order is unique')
        self.infer_unseen_opening.setChecked(self.settings.infer_unseen_opening)
        capture.addRow('Unseen opening',self.infer_unseen_opening)
        self.settings_interval=QDoubleSpinBox();self.settings_interval.setRange(.1,60);self.settings_interval.setValue(self.settings.interval);self.settings_interval.setSuffix(' seconds');capture.addRow('Permanent screenshot interval',self.settings_interval)
        self.adaptive=QCheckBox('Analyze additional temporary frames for fast games');self.adaptive.setChecked(self.settings.adaptive);capture.addRow('Adaptive recognition',self.adaptive)
        self.confirm_reply=QCheckBox('Keep latest move provisional until a reply or 0.5 seconds unchanged');self.confirm_reply.setChecked(self.settings.confirm_on_reply);capture.addRow('Protect against dragged pieces',self.confirm_reply)
        capture.addRow(muted('Recommended for blitz and rapid: a stable hover is not proof of a drop. The last move stays amber and out of PGN until a reply or explicit final-move confirmation.'))
        self.unresolved_fen=QDoubleSpinBox();self.unresolved_fen.setRange(0,600);self.unresolved_fen.setDecimals(0);self.unresolved_fen.setSuffix(' seconds');self.unresolved_fen.setSpecialValueText('Off');self.unresolved_fen.setValue(self.settings.unresolved_fen_seconds);capture.addRow('Warn about a small unresolved mismatch after',self.unresolved_fen)
        capture.addRow(muted('Small mismatches remain pending. The warning offers New game, Continue or Analysis in the Game menu beside the moves. It does not force a new PGN or invent a connection.'))
        self.new_game_delay=QDoubleSpinBox();self.new_game_delay.setRange(1,120);self.new_game_delay.setDecimals(0);self.new_game_delay.setSuffix(' seconds');self.new_game_delay.setValue(self.settings.new_game_change_seconds);capture.addRow('Confirm a likely new game after',self.new_game_delay)
        self.new_game_squares=QSpinBox();self.new_game_squares.setRange(1,32);self.new_game_squares.setValue(self.settings.new_game_min_changed_squares);capture.addRow('Minimum changed squares',self.new_game_squares)
        self.split_unlinked_positions=QCheckBox('Save the old PGN and start a new one for a stable unrelated board')
        self.split_unlinked_positions.setChecked(self.settings.split_unlinked_positions)
        self.split_unlinked_positions.setToolTip('Use the new-game delay and changed-square threshold above. Check earlier played positions and bounded legal branches first; a search limit is not proof of mathematical impossibility.')
        capture.addRow('Switch to unrelated positions',self.split_unlinked_positions)
        capture.addRow(muted('Before starting a new PGN, the recorder checks saved positions and short legal continuations. A board linked to earlier play is treated as review/analysis; a clear, substantially different board that stays put is started as a separate FEN game.'))
        self.detect_results=QCheckBox('Read visible result messages and end the game automatically');self.detect_results.setChecked(self.settings.detect_results);capture.addRow('Game-ending messages',self.detect_results)
        self.read_context=QCheckBox('Read clocks and nearby player names outside the board');self.read_context.setChecked(self.settings.read_context);capture.addRow('Visible game information',self.read_context)
        self.auto_context=QCheckBox('Look just outside the selected board for names and clocks');self.auto_context.setChecked(self.settings.auto_context);capture.addRow('Automatic surrounding context',self.auto_context)
        self.context_padding=QSpinBox();self.context_padding.setRange(0,50);self.context_padding.setSuffix(' % of board size');self.context_padding.setValue(self.settings.context_padding_percent);capture.addRow('Context margin on each side',self.context_padding)
        capture.addRow(muted('A tight board selection is enough: temporary text captures include the nearby margin, clipped to the desktop. The board preview and saved screenshots stay on the board. Enlarge this margin for distant clocks, or disable it to read only your selected area. Hidden names stay Unknown.'))
        self.result_player=QComboBox()
        for label,value in [('Remember bottom color when recording starts','initial-bottom'),('White','white'),('Black','black'),('Unknown — require an explicit color or score','unknown')]:self.result_player.addItem(label,value)
        self.result_player.setCurrentIndex(max(0,self.result_player.findData(self.settings.result_player_color)));capture.addRow('Player color for You Won / You Lost',self.result_player)
        capture.addRow(muted('The default assumes the account owner begins at the bottom, then remembers that color across flips. If recording starts on an already flipped board, choose White or Black here. Explicit scores and White/Black Won messages take precedence.'))
        self.review_seconds=QSpinBox();self.review_seconds.setRange(0,3600);self.review_seconds.setSuffix(' seconds');self.review_seconds.setSpecialValueText('Off');self.review_seconds.setValue(self.settings.review_seconds);capture.addRow('Capture post-game review variations for',self.review_seconds)
        self.fps=QSpinBox();self.fps.setRange(2,15);self.fps.setValue(self.settings.adaptive_fps);self.fps.setSuffix(' frames/s');capture.addRow('Adaptive target rate',self.fps)
        self.detect_setting=QCheckBox('Find the board inside the selected area');self.detect_setting.setChecked(self.settings.detect_board);capture.addRow('Board detection',self.detect_setting)
        self.orientation_setting=QComboBox();self.orientation_setting.addItems(['auto','white','black']);self.orientation_setting.setCurrentText(self.settings.orientation);capture.addRow('Color at the bottom',self.orientation_setting)
        self.recognizer_setting=QComboBox();self.recognizer_setting.addItem('Bundled screenshot model (recommended)','neural');self.recognizer_setting.addItem('Manually calibrated templates','calibrated');self.recognizer_setting.setCurrentIndex(1 if self.settings.recognition_mode=='calibrated' else 0);capture.addRow('Piece recognition',self.recognizer_setting)
        self.maxplies=QSpinBox();self.maxplies.setRange(1,6);self.maxplies.setValue(self.settings.max_plies);capture.addRow('Maximum missing plies',self.maxplies)
        self.nodes=QSpinBox();self.nodes.setRange(1000,1000000);self.nodes.setSingleStep(10000);self.nodes.setValue(self.settings.search_nodes);capture.addRow('Search node limit / hypothesis',self.nodes)
        self.ms=QSpinBox();self.ms.setRange(50,5000);self.ms.setValue(self.settings.search_ms);self.ms.setSuffix(' ms');capture.addRow('Search time / hypothesis',self.ms)
        self.threshold=QDoubleSpinBox();self.threshold.setRange(.5,.99);self.threshold.setSingleStep(.05);self.threshold.setValue(self.settings.min_confidence);capture.addRow('Minimum square score',self.threshold)
        self.initialfen=QLineEdit(self.settings.initial_fen);self.initialfen.setPlaceholderText('Optional full FEN for the first position');capture.addRow('Known initial position',self.initialfen)
        self.model=QLineEdit(self.settings.onnx_model);self.model.setPlaceholderText('Optional compatible RGB/logit model; leave blank to use the bundled model');model_row=QWidget();model_box=QHBoxLayout(model_row);model_box.setContentsMargins(0,0,0,0);model_box.addWidget(self.model);model_box.addWidget(button('Import model…',self.browse_model));capture.addRow('Custom ONNX model',model_row)
        capture.addRow(muted('Imported models are copied into the app-managed models folder, separate from screenshots and settings. Only load models you trust. Models must follow the documented 13-class contract.'))
        storage=tab('Storage & saving')
        self.save_screenshots=QCheckBox('Save screenshot images to disk while recording')
        self.save_screenshots.setChecked(self.settings.save_screenshots)
        storage.addRow('Screenshot images',self.save_screenshots)
        storage.addRow(muted('Off by default. The recorder still captures and analyzes frames in memory, and game joining uses PGNs and position data, so turning this off does not affect move reconstruction or rejoining.'))
        self.dedupe=QCheckBox('Skip saving byte-identical images (recognition still runs)');self.dedupe.setChecked(self.settings.deduplicate);storage.addRow('Optional deduplication',self.dedupe)
        self.retention=QSpinBox();self.retention.setRange(0,36500);self.retention.setValue(self.settings.retention_days);self.retention.setSpecialValueText('Keep indefinitely');self.retention.setSuffix(' days');storage.addRow('Automatically delete after',self.retention)
        storage.addRow(muted('Enabling a positive retention period authorizes permanent deletion of older screenshot files, including files already saved. Game data and PGNs are kept. Due jobs run when the application is open.'))
        self.export_path=QLineEdit(self.settings.export_dir);export_row=QWidget();export_box=QHBoxLayout(export_row);export_box.setContentsMargins(0,0,0,0);export_box.addWidget(self.export_path);export_box.addWidget(button('Browse…',self.browse_export));storage.addRow('Automatic export folder',export_row)
        self.autoexport=QCheckBox('Update exported PGN after verified moves and game completion');self.autoexport.setChecked(self.settings.auto_export);storage.addRow('Automatic export',self.autoexport)
        storage.addRow('Data directory',muted(str(self.root)));storage.addRow(muted('Verified progress is always saved atomically in the local database and per-game PGN files. The export folder provides an additional copy. Screenshots and metadata are separate.'))
        shortcuts=tab('Hotkeys & help');self.start_key=QKeySequenceEdit(QKeySequence(self.settings.start_hotkey));self.stop_key=QKeySequenceEdit(QKeySequence(self.settings.stop_hotkey));self.region_key=QKeySequenceEdit(QKeySequence(self.settings.region_hotkey));shortcuts.addRow('Start / pause / resume',self.start_key);shortcuts.addRow('Stop recording',self.stop_key);shortcuts.addRow('Select capture region',self.region_key);shortcuts.addRow(muted('On Windows, single-key or modifier hotkeys are registered globally when available; otherwise they work with app focus. Capturing protected video or a minimized/covered browser is not supported. Keep the browser visible and position this window beside it or on another monitor.'))
        shortcuts.addRow(button('Open user guide',self.open_guide));shortcuts.addRow(button('Open application data',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root)))))
        if sys.platform=='win32':shortcuts.addRow(button('Create / refresh desktop shortcut',lambda:self.refresh_desktop_shortcut(manual=True)))
        box.addWidget(button('Save settings',self.save_settings,primary=True),0,Qt.AlignRight)

    def browse_export(self):
        directory=QFileDialog.getExistingDirectory(self,'Automatic export directory',self.export_path.text())
        if directory:self.export_path.setText(directory)

    def browse_model(self):
        source,_=QFileDialog.getOpenFileName(self,'Import a trusted ONNX model',self.model.text(),'ONNX models (*.onnx)')
        if not source:return
        try:self.model.setText(str(import_custom_model(source,self.root/'models')))
        except (OSError,ValueError,RuntimeError) as exc:self.error(str(exc))

    def save_settings(self):
        try:
            if self.initialfen.text().strip():
                b=chess.Board(self.initialfen.text().strip())
                if not b.is_valid():raise ValueError('Initial FEN must be a valid chess position')
            if self.model.text().strip():
                source=Path(self.model.text().strip())
                try:validate_custom_model(source,self.root/'models')
                except ValueError:source=import_custom_model(source,self.root/'models')
                self.model.setText(str(source))
            days=self.retention.value()
            if days and days!=self.settings.retention_days:
                if QMessageBox.warning(self,'Enable automatic image deletion?',f'Permanently delete saved screenshots older than {days} days, now and on future runs? PGNs and game data are kept.',QMessageBox.Yes|QMessageBox.Cancel)!=QMessageBox.Yes:return
            s=self.settings
            s.auto_record_opening=self.auto_record_opening.isChecked()
            s.infer_unseen_opening=self.infer_unseen_opening.isChecked()
            s.split_unlinked_positions=self.split_unlinked_positions.isChecked()
            s.interval=self.settings_interval.value();s.adaptive=self.adaptive.isChecked();s.confirm_on_reply=self.confirm_reply.isChecked();s.unresolved_fen_seconds=self.unresolved_fen.value();s.new_game_change_seconds=self.new_game_delay.value();s.new_game_min_changed_squares=self.new_game_squares.value();s.detect_results=self.detect_results.isChecked();s.read_context=self.read_context.isChecked();s.auto_context=self.auto_context.isChecked();s.context_padding_percent=self.context_padding.value();s.result_player_color=self.result_player.currentData();s.review_seconds=self.review_seconds.value();s.adaptive_fps=self.fps.value();s.detect_board=self.detect_setting.isChecked();s.orientation=self.orientation_setting.currentText();s.max_plies=self.maxplies.value();s.search_nodes=self.nodes.value();s.search_ms=self.ms.value();s.min_confidence=self.threshold.value();s.initial_fen=self.initialfen.text().strip();s.onnx_model=self.model.text().strip();s.recognition_mode=self.recognizer_setting.currentData();s.save_screenshots=self.save_screenshots.isChecked();s.deduplicate=self.dedupe.isChecked();s.retention_days=days;s.export_dir=self.export_path.text().strip();s.auto_export=self.autoexport.isChecked();s.start_hotkey=self.start_key.keySequence().toString();s.stop_hotkey=self.stop_key.keySequence().toString();s.region_hotkey=self.region_key.keySequence().toString();s.save(self.root/'settings.json');self.interval.setValue(s.interval);self.install_hotkeys();self.run_retention();self.capture_caption.setText(self._screenshot_caption());self.statusBar().showMessage('Settings saved',6000)
            if self.worker:self.worker.commands.put(('region',self.region))
        except Exception as e:self.error(str(e))

    def install_hotkeys(self):
        self.global_hotkeys.clear()
        for shortcut in getattr(self,'shortcuts',[]):shortcut.setEnabled(False);shortcut.deleteLater()
        self.shortcuts=[]
        for sequence,fn in [(self.settings.start_hotkey,self.toggle_start),(self.settings.stop_hotkey,self.stop),(self.settings.region_hotkey,self.draw_region)]:
            if sequence:
                if self.global_hotkeys.register(sequence,fn):continue
                key=QShortcut(QKeySequence(sequence),self);key.activated.connect(fn);self.shortcuts.append(key)

    def refresh_desktop_shortcut(self,manual=False):
        if self._closing:return
        from .desktop import create_desktop_shortcut
        def create():
            try:return create_desktop_shortcut(self.root,force=manual)
            except Exception:
                logging.exception('Could not refresh ChessStream desktop shortcut')
                return None
        def done(path):
            if manual:self.statusBar().showMessage('ChessStream desktop shortcut refreshed' if path else
                'Could not create desktop shortcut; see Diagnostics / logs',8000)
        self.background(create,done)

    def refresh_usage(self):
        if self._closing:return
        try:
            usage=self.store.usage();text=f"{usage['count']} screenshots  •  {human_bytes(usage['bytes'])} used  •  {human_bytes(usage['free'])} available  •  {'Keep indefinitely' if not self.settings.retention_days else str(self.settings.retention_days)+' day retention'}"
            self.metric_labels['disk'].setText(human_bytes(usage['bytes']));self.storage_info.setText(text)
        except Exception:logging.exception('Could not read disk usage')

    def background(self,fn,done=None):
        task=Task(fn);self.tasks.append(task)
        if done:task.result.connect(done)
        task.failed.connect(self.error);task.finished.connect(lambda:self.tasks.remove(task) if task in self.tasks else None);task.start()
        return task

    def run_retention(self):
        if self._closing:return
        if self.retention_task and self.retention_task.isRunning():return
        self.retention_task=self.background(lambda:self.store.run_retention(self.settings.retention_days),lambda _:self.refresh_usage())

    def error(self,text):
        logging.warning('User-visible error: %s',text)
        self.statusBar().showMessage(text,15000);QMessageBox.warning(self,'ChessStream',text)

    def open_guide(self):
        guide=Path(__file__).parent/'assets/USER_GUIDE.html'
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(guide)))

    def closeEvent(self,event):
        if getattr(self,'_library_join_cancel',None):self._library_join_cancel.set()
        self.manager.cancel_saved_join()
        self.manager.cancel_background_recovery()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            if not self.worker.wait(12000):
                self.statusBar().showMessage('Waiting for current search or file write to finish…');event.ignore();return
        self._closing=True
        for task in self.tasks[:]:task.wait()
        self.timer.stop();self.retention_timer.stop();self.global_hotkeys.clear();self.settings.save(self.root/'settings.json');self.store.close();event.accept()
