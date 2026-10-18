from __future__ import annotations

from dataclasses import asdict
import ctypes
from ctypes import wintypes
import queue
import sys
import threading
import time
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from .domain import Region, utcnow
from .games import GameManager
from .vision import BoardDetector, TemplateRecognizer, create_recognizer, choose_orientation, checker_score


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

    def __init__(self, manager: GameManager, region: Region):
        super().__init__()
        self.manager, self.region = manager,region
        self.stopping=threading.Event()
        self.paused=threading.Event()
        self.commands=queue.SimpleQueue()

    def stop(self):
        self.stopping.set()

    def run(self):
        import mss
        store=self.manager.store
        detector=BoardDetector()
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
                                self.region=value;board_rect=None;last_shape=None;last_pixels=None
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
                            self.problem.emit(str(e))
                    if self.paused.is_set():
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
                        if stable_count>=2:
                            snapshot=self.manager.process(obs)
                        else:
                            snapshot={**snapshot,"status":"Waiting for position to settle"}
                        self.frame.emit(board_image)
                        snapshot.update(confidence=obs.confidence,orientation=obs.orientation,
                                        weakest_confidence=obs.weakest_confidence,
                                        uncertain_squares=obs.uncertain_squares(max(.80,settings.min_confidence)),
                                        recognition_mode=settings.recognition_mode)
                    else:
                        self.frame.emit(image)
                        snapshot.update(status="Board hidden / not found • game preserved",confidence=0)
                    # Position-mode storage never suppresses recognition, search
                    # or evidence metadata. Ignore hidden/unstable board images.
                    if save_due and (not position_mode or obs is not None and stable_count>=2):
                        store.save_screenshot(self.manager.session_id,self.manager.current_id,
                            board_image if board_image is not None else image,timestamp,
                            fen=(obs.placement() if obs else None),confidence=(obs.confidence if obs else None),
                            ply=snapshot.get("plies",0),deduplicate=settings.deduplicate,
                            deduplicate_position=position_mode)
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
                self.manager.finish()
                store.finish_session(self.manager.session_id)
            except Exception:
                import logging
                logging.exception("Could not finalize recording")
