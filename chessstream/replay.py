"""The live vision and reconstruction pipeline can also consume a local video."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import math
import cv2
from .domain import Settings
from .storage import Store
from .games import GameManager
from .vision import create_recognizer,BoardDetector,choose_orientation


def replay_video(path:Path,root:Path,region=None,interval=1.0,orientation='auto'):
    if not math.isfinite(interval) or interval<=0:raise ValueError('Screenshot interval must be finite and positive')
    settings=Settings.load(root/'settings.json');settings.orientation=orientation
    capture=cv2.VideoCapture(str(path))
    store=None
    try:
        if not capture.isOpened():raise ValueError(f'Cannot open video: {path}')
        fps=capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps<=0:raise ValueError('Video does not provide a valid frame rate')
        step=max(1,round(fps/settings.adaptive_fps));index=0;next_saved=0
        rect=tuple(map(int,region.split(','))) if region else None
        if rect is not None and (len(rect)!=4 or min(rect[:2])<0 or min(rect[2:])<80):
            raise ValueError('Video region must be x,y,width,height with nonnegative coordinates and at least 80 pixels per side')
        store=Store(root);manager=GameManager(store,settings)
        store.run_retention(settings.retention_days)
        recognizer=create_recognizer(settings,root/'custom-templates.npz');detector=BoardDetector()
        start=datetime.now(timezone.utc);previous=None;stable=0
        while True:
            ok,image=capture.read()
            if not ok:break
            if index%step:index+=1;continue
            seconds=index/fps
            if rect is None:rect,_=detector.detect(image)
            board=image
            if rect:
                x,y,w,h=rect;board=image[y:y+h,x:x+w]
            else:index+=1;continue
            obs=recognizer.recognize(board)
            if orientation=='auto':obs=choose_orientation(obs,manager.rec.board if manager.rec else None)
            elif orientation=='black':obs=obs.flipped()
            obs.timestamp=(start+timedelta(seconds=seconds)).isoformat(timespec='milliseconds')
            stable=stable+1 if obs.placement()==previous else 1;previous=obs.placement()
            if stable>=2:manager.process(obs)
            position_mode=settings.screenshot_mode=='positions'
            if settings.save_screenshots and ((position_mode and stable>=2) or (not position_mode and seconds>=next_saved)):
                store.save_screenshot(manager.session_id,manager.current_id,board,obs.timestamp,obs.placement(),obs.confidence,
                    len(manager.rec.verified) if manager.rec else 0,settings.deduplicate,position_mode)
                next_saved=seconds+interval
            index+=1
        manager.finish();store.finish_session(manager.session_id)
        print(f'Processed {index} video frames. {len(store.games())} games. PGNs: {root / "pgn"}')
    finally:
        capture.release()
        if store is not None:store.close()
