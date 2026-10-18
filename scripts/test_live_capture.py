"""Linux virtual-desktop acceptance: actual MSS pixels -> worker -> legal PGN.

Run under an X display, e.g. DISPLAY=:93 python scripts/test_live_capture.py.
Chromium is headed. No DOM data is supplied to the recognizer; the page API is
used only to drive known test moves, like clicking pieces in the test fixture.
"""
from pathlib import Path
import io
import json
import os
import tempfile
import time
import chess
import chess.pgn
import mss
import cv2
import numpy as np
from playwright.sync_api import sync_playwright
from PySide6.QtCore import QCoreApplication
from chessstream.domain import Settings,Region
from chessstream.storage import Store
from chessstream.games import GameManager
from chessstream.capture import RecordingWorker

ROOT=Path(__file__).resolve().parents[1]


def main():
    if not os.environ.get('DISPLAY'):raise RuntimeError('An X display is required for actual desktop capture')
    app=QCoreApplication.instance() or QCoreApplication([])
    with tempfile.TemporaryDirectory() as td, sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=False,args=['--no-sandbox','--window-size=1400,1000','--window-position=0,0'])
        page=browser.new_page(viewport={'width':1300,'height':880})
        page.goto('https://lichess.org/analysis',wait_until='domcontentloaded',timeout=60000);page.wait_for_selector('cg-board');page.wait_for_timeout(1800)
        store=Store(Path(td));settings=Settings();manager=GameManager(store,settings)
        with mss.mss() as cap:
            monitor=cap.monitors[1]
            screen=np.asarray(cap.grab(monitor))[:,:,:3].copy()
            cv2.imwrite(str(ROOT/'docs/live-screen-capture.png'),screen)
        worker=RecordingWorker(manager,Region(monitor['left'],monitor['top'],monitor['width'],monitor['height']))
        errors=[];updates=[];worker.problem.connect(errors.append);worker.update.connect(updates.append);worker.start()
        def pump(seconds):
            end=time.monotonic()+seconds
            while time.monotonic()<end:app.processEvents();page.wait_for_timeout(40)
        try:
            deadline=time.monotonic()+8
            while not manager.rec and time.monotonic()<deadline:pump(.1)
            assert manager.rec,'The actual desktop board was not initialized'
            ground=chess.Board();expected=[]
            pairs=['e4 e5','Nf3 Nc6','Bb5 a6','Ba4 Nf6']
            for i,pair in enumerate(pairs):
                if i==2:
                    worker.paused.set();pump(.3);before=len(store.screenshots());pump(.8)
                    assert len(store.screenshots())==before,'Pause continued saving screenshots'
                    worker.paused.clear();page.keyboard.press('f');pump(.45)
                    assert page.locator('.cg-wrap.orientation-black').count()>0,'The test board did not actually flip'
                for san in pair.split():
                    move=ground.parse_san(san);expected.append(move.uci());ground.push(move)
                    page.evaluate('(uci)=>window.lichess.analysis.playUci(uci)',move.uci());pump(.10)
                pump(.85)
            pump(.8)
        finally:
            worker.stop();assert worker.wait(10000),'Worker did not stop';app.processEvents()
        assert not errors,errors
        assert manager.rec.verified==expected,(manager.rec.verified,expected,manager.snapshot())
        row=store.game(manager.current_id);game=chess.pgn.read_game(io.StringIO(row['pgn']))
        assert [move.uci() for move in game.mainline_moves()]==expected
        shots=store.screenshots({'session_id':manager.session_id})
        assert len(shots)>=3
        assert len(updates)>len(shots),'Temporary adaptive frames were not independently processed'
        worker_fen=manager.rec.board.fen()
        report={'method':'Headed Chromium on Xvfb, actual MSS screen capture through RecordingWorker, no image injection',
            'display':os.environ['DISPLAY'],'expected_plies':len(expected),'verified_plies':len(manager.rec.verified),
            'saved_screenshots':len(shots),'processed_updates':len(updates),'board_flipped_midgame':True,
            'pause_resume_checked':True,
            'pgn_roundtrip_correct':True,'final_fen':worker_fen,'passed':True,
            'platform_limit':'Linux/X11 integration only; Windows desktop capture and scaling remain unvalidated'}
        (ROOT/'docs/live-capture-result.json').write_text(json.dumps(report,indent=2))
        (ROOT/'examples/live-screen-capture.pgn').write_text(row['pgn']+'\n')
        store.close();browser.close();print(json.dumps(report,indent=2))


if __name__=='__main__':main()
