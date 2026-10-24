from __future__ import annotations

from dataclasses import asdict
import ctypes
from ctypes import wintypes
import queue
import sys
import threading
import time
import logging
import re
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from .domain import Region, utcnow
from .games import GameManager
from .context_capture import capture_context
from .results import EndMessageDetector,ContextStabilizer,extract_context
from .vision import BoardDetector, TemplateRecognizer, create_recognizer, choose_orientation, checker_score


def should_save_screenshot(settings, preview_only, save_due, position_mode, observation, stable_count):
    """Whether a captured frame should become a permanent image on disk."""
    return bool(not preview_only and settings.save_screenshots and save_due
                and (not position_mode or observation is not None and stable_count >= 2))


def enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (OSError, AttributeError):
            ctypes.windll.shcore.SetProcessDpiAwareness(2)


def monitors() -> list[dict]:
    import mss
    with mss.mss() as cap:
        result = [dict(m, name=f"Monitor {i}") for i,m in enumerate(cap.monitors[1:],1)]
    if sys.platform == "win32":
        class Info(ctypes.Structure):
            _fields_ = [("cbSize",wintypes.DWORD),("rcMonitor",wintypes.RECT),
                        ("rcWork",wintypes.RECT),("dwFlags",wintypes.DWORD),("szDevice",wintypes.WCHAR*32)]
        found=[]
        @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HMONITOR,wintypes.HDC,ctypes.POINTER(wintypes.RECT),wintypes.LPARAM)
        def callback(handle,dc,rect,data):
            info = Info();info.cbSize=ctypes.sizeof(info)
            ctypes.windll.user32.GetMonitorInfoW.argtypes=[wintypes.HMONITOR,ctypes.c_void_p]
            if ctypes.windll.user32.GetMonitorInfoW(handle,ctypes.byref(info)):
                r=info.rcMonitor
                found.append({"left":r.left,"top":r.top,"width":r.right-r.left,"height":r.bottom-r.top,"name":info.szDevice})
            return True
        ctypes.windll.user32.EnumDisplayMonitors(0,0,callback,0)
        if found:
            return found
    return result


def windows() -> list[tuple[int,str]]:
    if sys.platform != "win32":
        return []
    result=[]
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def callback(hwnd,data):
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            length=ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            title=ctypes.create_unicode_buffer(length+1)
            ctypes.windll.user32.GetWindowTextW(hwnd,title,length+1)
            if length and title.value != "ChessStream PGN Recorder":
                result.append((int(hwnd),title.value))
        return True
    ctypes.windll.user32.EnumWindows(callback,0)
    return result


_CHESS_TITLE_TERMS = {
    "chess.com": 8, "lichess": 8, "chess": 7, "hikaru": 6, "magnus": 5,
    "stockfish": 5, "grandmaster": 4, "blitz": 4, "bullet": 4, "rapid": 4,
    "speedrun": 8, "speed": 3, "run": 2, "rating": 4, "climb": 4,
    "elo": 3, "educational": 3, "gambit": 3, "opening": 3, "puzzle": 3, "tactics": 3,
    "chessable": 4, "titled": 2, "arena": 2,
}


def _chess_title_score(title: str) -> int:
    words = set(re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)?", title.casefold()))
    score = sum(weight for term, weight in _CHESS_TITLE_TERMS.items() if term in words)
    if {"speed", "run"} <= words:
        score += 8
    if {"rating", "climb"} <= words:
        score += 8
    if "rating" in words and "road" in words:
        score += 4
    return score


def rank_youtube_windows(options: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Rank visible window titles for automatic YouTube chess capture.

    Only titles containing YouTube are eligible. Original enumeration order is
    preserved for ties and is the fallback when titles contain no chess terms.
    """
    ranked = []
    for index, (hwnd, title) in enumerate(options):
        words = set(re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)?", title.casefold()))
        if "youtube" not in words:
            continue
        score = _chess_title_score(title)
        ranked.append((-score, index, (hwnd, title)))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked]


def rank_capture_windows(options: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Put chess-related YouTube windows first in the manual chooser too."""
    youtube = rank_youtube_windows(options)
    youtube_handles = {hwnd for hwnd, _ in youtube}
    return youtube + [(hwnd, title) for hwnd, title in options if hwnd not in youtube_handles]


def window_client(hwnd: int) -> Region:
    if sys.platform != "win32":
        raise RuntimeError("Window tracking is available on Windows")
    user32=ctypes.windll.user32
    user32.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
    user32.IsWindow.argtypes=[wintypes.HWND]
    user32.IsIconic.argtypes=[wintypes.HWND]
    if not user32.IsWindow(wintypes.HWND(hwnd)) or user32.IsIconic(wintypes.HWND(hwnd)):
        raise RuntimeError("Selected window is closed or minimized")
    rect=wintypes.RECT();point=wintypes.POINT(0,0)
    if not user32.GetClientRect(wintypes.HWND(hwnd),ctypes.byref(rect)):
        raise ctypes.WinError()
    user32.ClientToScreen(wintypes.HWND(hwnd),ctypes.byref(point))
    return Region(point.x,point.y,rect.right,rect.bottom,window=hwnd)


def containing_window(region: Region) -> int:
    """Remember the visible source window for occasional full-window reacquisition."""
    if sys.platform!='win32':return 0
    x,y=region.left+region.width//2,region.top+region.height//2
    for hwnd,title in windows():
        try:
            r=window_client(hwnd)
            if r.left<=x<r.left+r.width and r.top<=y<r.top+r.height:return hwnd
        except (OSError,RuntimeError):continue
    return 0


def resolve_region(region: Region) -> Region:
    if region.window:
        client=window_client(region.window)
        if region.offset_x or region.offset_y:
            return Region(client.left+region.offset_x,client.top+region.offset_y,region.width,region.height)
        return client
    return region


def recognition_period(settings):
    """Image saving interval must never slow move comparisons below 2 Hz."""
    return min(.5,1/settings.adaptive_fps if settings.adaptive else settings.interval)


class RecordingWorker(QThread):
    frame = Signal(object)
    update = Signal(dict)
    problem = Signal(str)
    region_changed = Signal(object)

    def __init__(self, manager: GameManager, region: Region, preview_only: bool = False):
        super().__init__()
        self.manager, self.region = manager,region
        self.preview_only=preview_only
        self.stopping=threading.Event()
        self.paused=threading.Event()
        self.commands=queue.SimpleQueue()
        from .recovery import RecentFrames,PositionHistory
        self.recent_frames=RecentFrames(12)
        self.position_history=PositionHistory(96)
        self._processed_frames=0;self._late_capture_slots=0
        self.audio=None
        self.audio_info={"status":"Audio cues off","count":0}
        self._audio_enabled=False

    def audio_failed(self,exc):
        logging.warning('Optional audio failed; visual recording continues: %s',exc,exc_info=True)
        audio=self.audio;self.audio=None;self.manager._audio_evidence=None
        if audio:
            try:audio.stop()
            except Exception:logging.exception('Failed to close optional audio')
        self.audio_info={'status':'Audio unavailable; visual recording continues: '+str(exc),'count':0,'available':False}

    def poll_audio(self,discard=False):
        if not self.audio:return []
        try:
            events,self.audio_info=self.audio.poll(discard=discard)
            return events
        except Exception as exc:
            self.audio_failed(exc);return []

    def layout_changed(self):
        """Invalidate geometry-dependent evidence, retaining the game identity."""
        self.manager._audio_evidence=None
        if self.audio:self.poll_audio(discard=True)
        self.manager.cancel_background_recovery()
        self.manager.cancel_saved_join()
        self.manager._evidence_revision+=1
        self.manager.clear_position_recovery();self.manager.reset_settling()
        self._text_detector.invalidate_layout();self._context_stabilizer.reset_candidates()

    def process_observation(self, obs, stable_count):
        """Arm preview at startup and switch to recording on a supported opening."""
        # Validate shared recording state before any error path renders it.
        if not self.manager.check_recording_integrity():
            return {**self.manager.snapshot(),'pipeline_health':{'pgn':'checkpoint restored'}}
        from .integrity import observation_error
        error=observation_error(obs)
        if error:
            self.manager._audio_evidence=None;self.manager.reset_settling()
            self.manager.cancel_background_recovery();self.manager.cancel_saved_join()
            self.manager._evidence_revision+=1
            return {**self.manager.snapshot(),'status':'Recognition error • '+error+'; PGN preserved',
                    'pipeline_health':{'vision':'invalid output','pgn':'preserved'},'audio_cues':self.audio_info}
        audio=getattr(self,'audio',None)
        if audio:
            events=self.poll_audio(discard=self.paused.is_set() or self.preview_only)
            if events:
                self.manager._audio_evidence=(self.manager.current_id,obs.placement(),events[-1]['at'])
        self.manager.observe_frame(obs)
        self.manager.poll_saved_join()
        usable=(not self.manager.premove_state and not self.manager.rewind_state and not self.manager.terminal_message
            and self.manager.lifecycle.phase not in ('uncertain transition','temporarily uncertain','between games','analysis / replay'))
        if stable_count>=2 and usable:
            self.position_history.add(obs,self.manager.current_id,max(.8,self.manager.settings.min_confidence))
        evidence=self.position_history.observations(self.manager.current_id)
        automatic=False
        if (self.preview_only and stable_count>=2 and self.manager.settings.auto_record_opening
                and self.manager.opening_ready(obs)):
            self.preview_only=False;automatic=True
            with self.manager.lock:
                if self.manager.ended and self.manager.headers.get('Result','*')=='*':
                    self.manager.ended=None
                with self.manager.store.transaction() as db:
                    db.execute('UPDATE sessions SET ended=NULL WHERE id=?',(self.manager.session_id,))
            logging.info('Automatic recording started after a supported opening move appeared')
        if stable_count>=2 and not self.preview_only:
            if self.manager.lifecycle_gate(obs):
                if self.manager.lifecycle.phase=='unresolved move gap':
                    self.manager.background_recovery(obs,evidence)
                snapshot=self.manager.lifecycle_snapshot(obs)
            elif self.manager.background_recovery(obs,evidence):
                snapshot={**self.manager.snapshot(),'status':'Recovering a legal gap in background • capture continues',
                          'preview_fen':obs.placement()+' w - - 0 1','preview_moves':[],'preview_last_move':None}
            else:
                snapshot=self.manager.process(obs)
                self.manager.background_recovery(obs,evidence)
        else:
            snapshot={**self.manager.snapshot(),'status':'Waiting for position to settle'}
        if self.preview_only:
            status=('Armed • recording starts when an opening move appears' if self.manager.settings.auto_record_opening else
                    'Previewing selected window • click Start recording')
            snapshot.update(status=status,preview_fen=obs.placement()+' w - - 0 1',preview_moves=[])
        self.recent_frames.mark(self.manager.current_id,not self.manager.premove_state and not self.manager.rewind_state and not self.manager.terminal_message
            and self.manager.lifecycle.phase not in ('uncertain transition','temporarily uncertain','between games'))
        if (stable_count>=2 and not self.manager.premove_state and not self.manager.rewind_state and not self.manager.terminal_message
                and self.manager.lifecycle.phase not in ('uncertain transition','temporarily uncertain','between games','analysis / replay')):
            self.position_history.add(obs,self.manager.current_id,max(.8,self.manager.settings.min_confidence))
        if stable_count>=2 and not self.preview_only:self.manager.queue_checkpoint_join()
        snapshot['audio_cues']=getattr(self,'audio_info',{'status':'Audio cues off','count':0})
        snapshot['buffered_positions']=len(self.position_history.positions)
        if automatic:snapshot['recording_started_automatically']=True
        self.manager.trace_frame(obs,stable_count,snapshot)
        return snapshot

    def scan_context(self,image,rect,obs):
        settings=self.manager.settings
        if getattr(self,"_text_failed",False):return
        if not (settings.detect_results or settings.read_context):return
        if self._context_game!=self.manager.current_id:
            self._context_game=self.manager.current_id;self._text_detector.reset()
        before=self._text_detector.last_scan
        try:
            if rect:self._text_board_rect=rect
            orientation=obs.orientation if obs else (self.manager.last_observation.orientation if self.manager.last_observation else None)
            message=self._text_detector.scan(image,self.manager.result_player(),rect or getattr(self,'_text_board_rect',None),self.manager.observed_names,orientation=orientation)
            if self._text_detector.last_scan!=before:
                if (settings.read_context and obs is not None
                        and obs.confidence>=max(.80,settings.min_confidence)
                        and len(obs.uncertain_squares(max(.80,settings.min_confidence)))<=2
                        and rect is not None):
                    # An obscured or absent board can leave a stale rectangle
                    # pointing at a different tab/overlay. OCR results from
                    # that view must never mutate player IDs or game identity.
                    context=self._context_stabilizer.observe(extract_context(self._text_detector.last_lines,rect,orientation))
                    self.manager.observe_context(context,obs.timestamp)
                    if context.get('clocks') or context.get('names'):
                        logging.info('Visible game context %s',context)
                if message and settings.detect_results:self.manager.declare_end(message,obs)
        except Exception:
            if not getattr(self,'_text_failed',False):
                logging.exception('Local text recognition failed; chess capture continues')
                self.problem.emit('Could not read result messages or clocks. Chess capture continues; see application.log.')
                self._text_failed=True

    def stop(self):
        self.stopping.set()

    def run(self):
        import mss
        store=self.manager.store
        detector=BoardDetector()
        self._text_detector=EndMessageDetector();self._context_stabilizer=ContextStabilizer();self._context_game=None
        recognizer=None
        model_path=None
        board_rect=None
        last_shape=None
        last_pixels=None
        last_obs=None
        stable_key=None
        stable_count=0
        next_saved=0.0
        last_detect=0.0
        context_source_rect=None;context_source_shape=None
        try:
            cv2.setNumThreads(1)
            with mss.mss() as cap:
                while not self.stopping.is_set():
                    tick=time.monotonic()
                    settings=self.manager.settings
                    if settings.audio_cues!=self._audio_enabled:
                        if self.audio:
                            try:self.audio.stop()
                            except Exception as exc:self.audio_failed(exc)
                        self.audio=None;self._audio_enabled=settings.audio_cues
                        self.manager._audio_evidence=None
                        self.audio_info={'status':'Audio cues off','count':0}
                        if settings.audio_cues:
                            from .audio import AudioListener
                            try:
                                self.audio=AudioListener(store.root/'audio-cues.json');self.audio.start()
                            except Exception as exc:self.audio_failed(exc)
                    if self.audio and self.paused.is_set():
                        self.poll_audio(discard=True);self.manager._audio_evidence=None
                    while not self.commands.empty():
                        action,value=self.commands.get()
                        try:
                            if action=="region":
                                self.region=value;board_rect=None;last_shape=None;last_pixels=None;context_source_rect=None;self.layout_changed()
                            elif action=="record":
                                self.preview_only=False;stable_count=0
                                self.manager.clear_position_recovery();self.manager.reset_settling()
                            elif action=="choose":self.manager.choose(value)
                            elif action=="new":self.manager.force_new()
                            elif action=='game_mode':self.manager.set_game_mode(value)
                            elif action=='split_game':
                                if self.manager.current_id!=value[0]:raise ValueError('The active game changed. Select the split move again.')
                                self.manager.split_game_at(value[1])
                            elif action=="repair":self.manager.repair_current()
                            elif action=="join_previous":self.manager.join_previous_recording(background=True)
                            elif action=="correct":
                                if isinstance(value,tuple):self.manager.correct_line(*value)
                                else:self.manager.correct_line(value)
                            elif action=="calibrate":
                                image,orientation=value
                                TemplateRecognizer.calibrate(image,store.root/"custom-templates.npz",orientation)
                                settings.recognition_mode="calibrated"
                                settings.onnx_model=""
                                settings.save(store.root/"settings.json")
                                recognizer=None;last_pixels=None;stable_key=None
                            self.update.emit(self.manager.snapshot())
                        except Exception as e:
                            logging.exception("Capture command %s failed",action)
                            self.problem.emit(str(e))
                    if self.paused.is_set():
                        self.manager.clear_position_recovery();self.manager.reset_settling()
                        self._text_detector.reset()
                        self.stopping.wait(.1)
                        continue
                    configuration=(settings.onnx_model,settings.recognition_mode)
                    if recognizer is None or configuration != model_path:
                        model_path=configuration
                        recognizer=create_recognizer(settings,store.root/"custom-templates.npz")
                        last_pixels=None;last_obs=None;stable_key=None;stable_count=0
                    try:
                        source=resolve_region(self.region)
                        if not source.valid():
                            raise ValueError("Capture area is too small")
                        image=np.asarray(cap.grab({k:getattr(source,k) for k in ["left","top","width","height"]}))[:,:,:3].copy()
                    except Exception as e:
                        self.update.emit({**self.manager.snapshot(),"status":str(e)+" • waiting for source"})
                        self.stopping.wait(.5)
                        continue
                    timestamp=utcnow()
                    captured_at=time.monotonic()
                    if settings.detect_board:
                        if image.shape != last_shape or tick-last_detect>2:
                            previous_rect=board_rect
                            board_rect,quality=detector.detect(image)
                            if board_rect!=previous_rect or image.shape!=last_shape:
                                # Fullscreen can move the board without resizing the
                                # browser client. Reacquire geometry, never game state.
                                stable_key=None;stable_count=0;last_pixels=None
                                self.layout_changed()
                            last_detect=tick
                            last_shape=image.shape
                            if board_rect is None and self.region.tracking_window:
                                try:
                                    parent=window_client(self.region.tracking_window)
                                    full=np.asarray(cap.grab({k:getattr(parent,k) for k in ['left','top','width','height']}))[:,:,:3].copy()
                                    timestamp=utcnow();captured_at=time.monotonic()
                                    found,_=detector.detect(full)
                                    if found:
                                        x,y,w,h=found
                                        self.region=Region(parent.left+x,parent.top+y,w,h,tracking_window=self.region.tracking_window)
                                        self.region_changed.emit(self.region)
                                        image=full[y:y+h,x:x+w].copy();source=self.region
                                        board_rect=(0,0,w,h);last_shape=image.shape;last_pixels=None
                                except (OSError,RuntimeError):pass
                        if board_rect:
                            x,y,w,h=board_rect
                            board_image=image[y:y+h,x:x+w].copy()
                            if checker_score(board_image)<.25 and tick-last_detect>2:
                                board_rect=None
                        else:
                            board_image=None
                    else:
                        board_image=image
                    if image.shape!=context_source_shape:
                        context_source_rect=None;context_source_shape=image.shape
                    if board_rect:context_source_rect=board_rect
                    if not settings.detect_board:context_source_rect=(0,0,image.shape[1],image.shape[0])
                    context_image=image;context_rect=context_source_rect
                    context_due=((settings.read_context or settings.detect_results)
                                 and not getattr(self,'_text_failed',False) and time.monotonic()-self._text_detector.last_scan>=1)
                    if context_due and context_rect:
                        try:
                            context_image,context_rect,newer=capture_context(cap,source,image,context_rect,
                                settings.auto_context,settings.context_padding_percent)
                            if newer:
                                timestamp=utcnow();captured_at=time.monotonic()
                                if board_image is not None:
                                    cx,cy,cw,ch=context_rect
                                    board_image=context_image[cy:cy+ch,cx:cx+cw].copy()
                        except Exception:
                            logging.exception('Could not expand board context; using selected area')
                            context_image=image;context_rect=context_source_rect
                    position_mode=settings.screenshot_mode=="positions"
                    save_due=position_mode or tick>=next_saved
                    snapshot=self.manager.snapshot()
                    obs=None
                    if board_image is not None:
                        changed=last_pixels is None or not np.array_equal(board_image,last_pixels)
                        if changed or last_obs is None:
                            obs=recognizer.recognize(board_image)
                            from .integrity import observation_error
                            if not observation_error(obs):
                                if settings.orientation=="auto":
                                    obs=choose_orientation(obs,self.manager.rec.board if self.manager.rec else None)
                                elif settings.orientation=="black":
                                    obs=obs.flipped()
                            last_pixels=board_image.copy();last_obs=obs
                        else:
                            from .domain import Observation
                            obs=Observation(last_obs.probabilities.copy(),orientation=last_obs.orientation,quality=last_obs.quality)
                        from .integrity import observation_error
                        if observation_error(obs):
                            self.update.emit(self.process_observation(obs,0))
                            last_pixels=None;last_obs=None;stable_key=None;stable_count=0
                            self.stopping.wait(recognition_period(settings))
                            continue
                        obs.timestamp=timestamp
                        self.scan_context(context_image,context_rect,obs)
                        if settings.detect_board and obs.confidence<.6 and tick-last_detect>2:
                            board_rect=None
                        key=obs.placement()
                        stable_count=stable_count+1 if key==stable_key else 1
                        stable_key=key
                        if settings.adaptive and stable_count<2:
                            # Inference itself takes time. If a fresh raw capture is
                            # still identical afterward, that is a stable interval
                            # without waiting for a second full inference cycle.
                            if not self.stopping.wait(max(0,.08-(time.monotonic()-captured_at))):
                                confirm=np.asarray(cap.grab({k:getattr(source,k) for k in ['left','top','width','height']}))[:,:,:3].copy()
                                if settings.detect_board and board_rect:
                                    x,y,w,h=board_rect;confirm=confirm[y:y+h,x:x+w]
                                if np.array_equal(confirm,board_image):stable_count=2
                        if not settings.adaptive and stable_count<2:
                            # A short unsaved confirmation frame avoids committing piece animations.
                            if not self.stopping.wait(.09):
                                confirm=np.asarray(cap.grab({k:getattr(source,k) for k in ["left","top","width","height"]}))[:,:,:3].copy()
                                if settings.detect_board and board_rect:
                                    x,y,w,h=board_rect;confirm=confirm[y:y+h,x:x+w]
                                if np.array_equal(confirm,board_image):stable_count=2
                                else:
                                    second=recognizer.recognize(confirm)
                                    if settings.orientation=="auto":
                                        second=choose_orientation(second,self.manager.rec.board if self.manager.rec else None)
                                    elif settings.orientation=="black":second=second.flipped()
                                    if second.placement()==key:stable_count=2
                        self.recent_frames.add(board_image,obs)
                        snapshot=self.process_observation(obs,stable_count)
                        self.frame.emit(board_image)
                        snapshot.update(confidence=obs.confidence,orientation=obs.orientation,
                                        weakest_confidence=obs.weakest_confidence,
                                        uncertain_squares=obs.uncertain_squares(max(.80,settings.min_confidence)),
                                        recognition_mode=settings.recognition_mode)
                    else:
                        if not self.preview_only:self.manager.clear_position_recovery();self.manager.reset_settling()
                        self.manager.lifecycle.set_phase('temporarily uncertain','Board hidden or not found; current PGN preserved')
                        self.scan_context(context_image,context_rect,None)
                        snapshot=self.manager.snapshot()
                        self.frame.emit(image)
                        snapshot.update(status=(self.manager.last_message if self.manager.terminal_message else "Board hidden / not found • game preserved"),confidence=0)
                    # Position-mode storage never suppresses recognition, search
                    # or evidence metadata. Ignore hidden/unstable board images.
                    if should_save_screenshot(settings,self.preview_only,save_due,position_mode,obs,stable_count):
                        store.save_screenshot(self.manager.session_id,self.manager.current_id,
                            board_image if board_image is not None else image,timestamp,
                            fen=(obs.placement() if obs else None),confidence=(obs.confidence if obs else None),
                            ply=snapshot.get("plies",0),deduplicate=settings.deduplicate,
                            deduplicate_position=bool(obs is not None and stable_count>=2))
                        next_saved=tick+settings.interval
                    if self.audio and obs is None:
                        self.poll_audio(discard=True)
                    snapshot['audio_cues']=self.audio_info
                    snapshot["buffered_frames"]=len(self.recent_frames.frames)
                    snapshot["buffered_bytes"]=sum(frame["image"].nbytes for frame in self.recent_frames.frames)
                    elapsed=time.monotonic()-tick
                    period=recognition_period(settings)
                    self._processed_frames+=1
                    # Estimated missed scheduling slots, not unseen source
                    # video frames. The video frame rate is not observable.
                    self._late_capture_slots+=max(0,int(elapsed/period))
                    snapshot["processing_ms"]=round(elapsed*1000)
                    snapshot["capture_metrics"]={'processed_frames':self._processed_frames,
                        'estimated_late_slots':self._late_capture_slots,'period_ms':round(period*1000)}
                    snapshot["saved_count"]=store.deletion_estimate({"session_id":self.manager.session_id})["count"]
                    self.update.emit(snapshot)
                    self.stopping.wait(max(.005,period-(time.monotonic()-tick)))
        except Exception as e:
            import logging
            logging.exception("Recording worker failed")
            self.problem.emit(f"Recording stopped: {e}. Verified PGN remains saved.")
        finally:
            if self.audio:
                try:self.audio.stop()
                except Exception as exc:self.audio_failed(exc)
            self.manager._audio_evidence=None
            self.manager.cancel_background_recovery()
            self.manager.cancel_saved_join()
            try:
                if not self.preview_only:
                    self.manager.finish()
                    store.finish_session(self.manager.session_id)
                elif not self.manager.rec:
                    store.finish_session(self.manager.session_id)
            except Exception:
                import logging
                logging.exception("Could not finalize recording")
