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

    def process_observation(self, obs, stable_count):
        """Arm preview at startup and switch to recording on a supported opening."""
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
            snapshot=self.manager.process(obs)
        else:
            snapshot={**self.manager.snapshot(),'status':'Waiting for position to settle'}
        if self.preview_only:
            status=('Armed • recording starts when an opening move appears' if self.manager.settings.auto_record_opening else
                    'Previewing selected window • click Start recording')
            snapshot.update(status=status,preview_fen=obs.placement()+' w - - 0 1',preview_moves=[])
        if automatic:snapshot['recording_started_automatically']=True
        return snapshot

    def scan_context(self,image,rect,obs):
        settings=self.manager.settings
        if getattr(self,"_text_failed",False):return
        if not self.manager.rec or not (settings.detect_results or settings.read_context):return
        if self._context_game!=self.manager.current_id:
            self._context_game=self.manager.current_id;self._text_detector.reset()
        before=self._text_detector.last_scan
        try:
            if rect:self._text_board_rect=rect
            message=self._text_detector.scan(image,self.manager.result_player(),rect or getattr(self,'_text_board_rect',None),self.manager.observed_names)
            if self._text_detector.last_scan!=before:
                if settings.read_context:
                    orientation=obs.orientation if obs else (self.manager.last_observation.orientation if self.manager.last_observation else None)
                    context=self._context_stabilizer.observe(extract_context(self._text_detector.last_lines,rect,orientation))
                    self.manager.observe_context(context,obs.timestamp if obs else utcnow())
                    if context.get('clocks') or context.get('names'):
                        logging.info('Visible game context %s',context)
                if message and settings.detect_results and not self.manager.pending_identity:self.manager.declare_end(message,obs)
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
                    while not self.commands.empty():
                        action,value=self.commands.get()
                        try:
                            if action=="region":
                                self.region=value;board_rect=None;last_shape=None;last_pixels=None;context_source_rect=None;self._text_detector.reset()
                            elif action=="record":
                                self.preview_only=False;stable_count=0
                                self.manager.clear_position_recovery()
                            elif action=="choose":self.manager.choose(value)
                            elif action=="new":self.manager.force_new()
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
                        self.manager.clear_position_recovery()
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
                        if image.shape != last_shape or board_rect is None and tick-last_detect>2:
                            board_rect,quality=detector.detect(image)
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
                    context_due=(not self.preview_only and self.manager.rec is not None and (settings.read_context or settings.detect_results)
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
                            if settings.orientation=="auto":
                                obs=choose_orientation(obs,self.manager.rec.board if self.manager.rec else None)
                            elif settings.orientation=="black":
                                obs=obs.flipped()
                            last_pixels=board_image.copy();last_obs=obs
                        else:
                            from .domain import Observation
                            obs=Observation(last_obs.probabilities.copy(),orientation=last_obs.orientation,quality=last_obs.quality)
                        obs.timestamp=timestamp
                        if not self.preview_only:self.scan_context(context_image,context_rect,obs)
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
                        snapshot=self.process_observation(obs,stable_count)
                        self.frame.emit(board_image)
                        snapshot.update(confidence=obs.confidence,orientation=obs.orientation,
                                        weakest_confidence=obs.weakest_confidence,
                                        uncertain_squares=obs.uncertain_squares(max(.80,settings.min_confidence)),
                                        recognition_mode=settings.recognition_mode)
                    else:
                        if not self.preview_only:self.manager.clear_position_recovery()
                        if not self.preview_only:self.scan_context(context_image,context_rect,None)
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
                    snapshot["processing_ms"]=round((time.monotonic()-tick)*1000)
                    snapshot["saved_count"]=store.deletion_estimate({"session_id":self.manager.session_id})["count"]
                    self.update.emit(snapshot)
                    period=1/settings.adaptive_fps if settings.adaptive else settings.interval
                    self.stopping.wait(max(.005,period-(time.monotonic()-tick)))
        except Exception as e:
            import logging
            logging.exception("Recording worker failed")
            self.problem.emit(f"Recording stopped: {e}. Verified PGN remains saved.")
        finally:
            try:
                if not self.preview_only:
                    self.manager.finish()
                    store.finish_session(self.manager.session_id)
                elif not self.manager.rec:
                    store.finish_session(self.manager.session_id)
            except Exception:
                import logging
                logging.exception("Could not finalize recording")
