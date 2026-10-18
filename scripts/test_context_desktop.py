"""Actual MSS desktop test: tight board selection -> temporary context, two sizes.

DISPLAY=:93 python scripts/test_context_desktop.py
Displays a retained native browser capture; no network or DOM supplies OCR input.
"""
from pathlib import Path
import json
import time
import cv2
import mss
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication,QLabel
from chessstream.context_capture import capture_context
from chessstream.domain import Region
from chessstream.results import LocalTextReader,extract_context

ROOT=Path(__file__).resolve().parents[1]


def main():
    app=QApplication([]);view=QLabel();view.setWindowFlags(Qt.FramelessWindowHint);view.setScaledContents(True)
    view.setPixmap(QPixmap(str(ROOT/'tests/fixtures/results/native-bot-clock.png')))
    reader=LocalTextReader();cases=[]
    with mss.mss() as cap:
        for width,height,left,top in [(1200,1000,20,10),(800,667,80,50)]:
            view.setGeometry(left,top,width,height);view.show();view.raise_();app.processEvents();time.sleep(.2);app.processEvents()
            sx,sy=width/1200,height/1000
            source=Region(left+round(108*sx),top+round(66*sy),round(568*sx),round(568*sy))
            board=np.asarray(cap.grab({key:getattr(source,key) for key in ['left','top','width','height']}))[:,:,:3].copy()
            start=time.perf_counter();image,rect,newer=capture_context(cap,source,board,(0,0,source.width,source.height))
            lines=reader.read(image)
            context=extract_context(lines,rect,'white')
            passed=context['clocks']=={'white':596,'black':597} and context['names']=={'white':'Guest','black':'Martinfoot'}
            cases.append({'source_size':[width,height],'board_selection':[source.left,source.top,source.width,source.height],
                          'temporary_context_size':[image.shape[1],image.shape[0]],'extra_capture':newer,'context':context,
                          'capture_and_ocr_ms':round((time.perf_counter()-start)*1000,1),'passed':passed})
    view.close();app.processEvents()
    report={'method':'Actual X11 desktop MSS capture of a displayed retained native Chess.com frame. Only the 64-square board is selected; the production margin helper captures external names/clocks. Window moved and resized between two cases. No source pixels are directly supplied to OCR. Not a YouTube first-game or physical Windows acceptance test.',
            'cases':cases,'passed':all(case['passed'] for case in cases)}
    (ROOT/'docs/context-v1.5.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));assert report['passed']

if __name__=='__main__':main()
