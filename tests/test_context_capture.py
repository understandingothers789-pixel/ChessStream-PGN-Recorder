from pathlib import Path
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import cv2
import numpy as np
from chessstream.context_capture import capture_context,context_region
from chessstream.domain import Region,Settings
from chessstream.results import LocalTextReader,extract_context


class Screen:
    def __init__(self,image,left=0,top=0):
        self.image=image;self.calls=[];self.monitors=[dict(left=left,top=top,width=image.shape[1],height=image.shape[0])]
    def grab(self,region):
        self.calls.append(region)
        x=region['left']-self.monitors[0]['left'];y=region['top']-self.monitors[0]['top']
        return self.image[y:y+region['height'],x:x+region['width']]


def test_tight_board_selection_reads_native_external_clocks_without_changing_board_crop():
    frame=cv2.imread(str(Path(__file__).parent/'fixtures/results/native-bot-clock.png'))
    source=Region(108,66,568,568);board=frame[66:634,108:676].copy();screen=Screen(frame)
    expanded,rect,newer=capture_context(screen,source,board,(0,0,568,568))
    assert newer and len(screen.calls)==1
    x,y,w,h=rect
    assert np.array_equal(expanded[y:y+h,x:x+w],board)
    assert expanded.shape[0]>568 and expanded.shape[1]>568
    context=extract_context(LocalTextReader().read(expanded),rect,'white')
    assert context['clocks']=={'white':596,'black':597}
    assert context['names']=={'white':'Guest','black':'Martinfoot'}


def test_existing_wide_selection_reuses_pixels_and_disabled_mode_stays_selected():
    image=np.zeros((1000,1200,3),np.uint8);screen=Screen(image);source=Region(0,0,1200,1000)
    crop,rect,newer=capture_context(screen,source,image,(108,66,568,568))
    assert not newer and not screen.calls
    assert crop.shape[0]>568 and rect[2:]==(568,568)
    selected=Region(108,66,568,568);board=image[66:634,108:676]
    result,rect,newer=capture_context(screen,selected,board,(0,0,568,568),False)
    assert result is board and rect==(0,0,568,568) and not newer and not screen.calls


def test_context_clips_desktop_edges_and_tracks_physical_resize_and_negative_origins():
    desktop=dict(left=-1920,top=-200,width=3840,height=1280)
    region,rect=context_region(Region(-1910,-190,600,600),(0,0,600,600),desktop)
    assert region.left==-1920 and region.top==-200 and rect[:2]==(10,10)
    assert region.width==718 and region.height==718
    region,rect=context_region(Region(200,100,900,900),(20,20,800,800),desktop)
    assert rect==(144,144,800,800)
    assert region.left==76 and region.top==-24


def test_new_context_frame_board_pixels_are_available_to_avoid_stale_move_evidence():
    desktop=np.zeros((700,700,3),np.uint8);screen=Screen(desktop)
    source=Region(100,100,400,400);old=np.zeros((400,400,3),np.uint8)
    desktop[100:500,100:500]=123
    frame,rect,newer=capture_context(screen,source,old,(0,0,400,400))
    x,y,w,h=rect
    assert newer and np.all(frame[y:y+h,x:x+w]==123) and np.all(old==0)


def test_visible_masking_labels_remain_unknown_while_clock_reading_survives():
    lines=[('NAME BLURRED BECAUSE BAD (492)',.99,(40,5,300,25)),('9:59',.99,(350,5,400,25)),
           ('DEFINITELY NOT HIKARU (508)',.99,(40,465,290,485)),('9:42',.99,(350,465,400,485))]
    context=extract_context(lines,(40,40,400,400),'white')
    assert context['clocks']=={'black':599,'white':582} and context['names']=={}


def test_context_settings_default_and_bounds_survive_save(tmp_path):
    path=tmp_path/'settings.json';settings=Settings();assert settings.auto_context and settings.context_padding_percent==18
    settings.context_padding_percent=999;settings.save(path)
    assert Settings.load(path).context_padding_percent==50


def test_production_worker_uses_temporary_margin_and_saves_only_board(tmp_path,monkeypatch):
    import time
    import mss
    from PySide6.QtWidgets import QApplication
    from chessstream.capture import RecordingWorker
    from chessstream.games import GameManager
    from chessstream.storage import Store
    app=QApplication.instance() or QApplication([])
    frame=cv2.imread(str(Path(__file__).parent/'fixtures/results/native-bot-clock.png'))
    class Capture(Screen):
        def __enter__(self):return self
        def __exit__(self,*args):pass
    screen=Capture(frame);monkeypatch.setattr(mss,'mss',lambda:screen)
    store=Store(tmp_path);manager=GameManager(store,Settings(detect_board=False,orientation='white'))
    worker=RecordingWorker(manager,Region(108,66,568,568));start=time.monotonic()
    def update(snapshot):
        if manager.headers.get('Black')=='Martinfoot' or time.monotonic()-start>8:worker.stop()
    worker.update.connect(update);worker.run()
    assert manager.headers['White']=='Guest' and manager.headers['Black']=='Martinfoot'
    assert manager.latest_context['clocks']=={'white':596,'black':597}
    wide=[call for call in screen.calls if call['width']>568]
    assert 3<=len(wide)<=5
    shots=store.screenshots()
    assert len(shots)==1
    saved=cv2.imread(str(tmp_path/shots[0]['path']))
    assert saved.shape[:2]==(568,568)
    store.close()
