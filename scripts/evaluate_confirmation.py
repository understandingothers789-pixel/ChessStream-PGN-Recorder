"""Reproduce held-drag and arrow regressions through the production pipeline.

The fixtures are actual browser captures; controlled test moves are not used by
the application. Hover frames are evaluated for safety, not against a fictitious
completed-move FEN. No manual final confirmation is applied in this report.
"""
from pathlib import Path
import json
import platform
import tempfile
import chess
import cv2
from chessstream.domain import Settings,board_labels
from chessstream.games import GameManager
from chessstream.storage import Store
from chessstream.vision import ScreenshotRecognizer

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'tests/fixtures/confirmation'


def main():
    manifest=json.loads((FIXTURES/'manifest.json').read_text())
    model=ScreenshotRecognizer();cases=[]
    with tempfile.TemporaryDirectory() as temporary:
        for case in manifest['cases']:
            store=Store(Path(temporary)/case['id'])
            manager=GameManager(store,Settings(initial_fen=case['initial_fen']))
            rows=[]
            for frame in case['frames']:
                image=cv2.imread(str(FIXTURES/frame['file']))
                observed=model.recognize(image,frame['orientation'])
                repeat=8 if frame['kind']=='hover' else 1
                for _ in range(repeat):
                    snapshot=manager.process(observed)
                    if frame['kind']=='hover':assert not manager.rec.verified
                    store.save_screenshot(manager.session_id,manager.current_id,image,
                                          observed.timestamp,observed.placement(),observed.confidence,
                                          len(manager.rec.verified),deduplicate_position=True)
                rows.append({'file':frame['file'],'kind':frame['kind'],'processed_frames':repeat,
                             'square_errors':None if frame['kind']=='hover' else int((observed.labels!=board_labels(chess.Board(frame['fen']))).sum()),
                             'verified_moves':snapshot['moves'],'pending_moves':snapshot['pending_moves'],
                             'status':snapshot['status']})
            expected=['Ng5','Nh6','Qf3'] if case['id']=='italian' else ['Bb4']
            assert snapshot['moves']==expected
            assert snapshot['pending_moves']==(['d6'] if case['id']=='italian' else ['a3'])
            cases.append({'id':case['id'],'frames':rows,'expected_verified_moves':expected,
                          'saved_images':len(store.screenshots()),'passed':True})
            store.close()
    report={'version':'1.2.0','environment':platform.platform(),'provenance':manifest['method'],
            'confirmation_policy':'Opponent response required; final reply remains provisional. No explicit confirmation applied.',
            'cases':cases,'limitations':[
                'Controlled reproductions on the real Chess.com UI, not a full YouTube stream benchmark.',
                'Inline user screenshots are not byte-identical to these test captures.',
                'Stable held hover can be visually identical to a released piece; time is not confirmation.',
                'Storage follows recognized positions, so provisional hover images may be kept for review.',
                'Heavy occlusion can still stall recognition or bounded reconstruction.'
            ]}
    (ROOT/'docs/confirmation-v1.2.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({c['id']:{'verified':c['frames'][-1]['verified_moves'],
                             'pending':c['frames'][-1]['pending_moves'],
                             'saved_images':c['saved_images'],'passed':c['passed']} for c in cases},indent=2))


if __name__=='__main__':main()
