"""Measured recognition regression suite on browser-captured textured boards."""
from pathlib import Path
import io
import json
import platform
import tempfile
import time
import chess
import chess.pgn
import cv2
import numpy as np
import psutil
from chessstream.domain import Settings, board_labels
from chessstream.games import GameManager
from chessstream.storage import Store
from chessstream.vision import ScreenshotRecognizer, TemplateRecognizer, choose_orientation

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'tests/fixtures/themes'


def main():
    manifests=[json.loads((FIXTURES/name).read_text()) for name in ['manifest.json','chesscom-ocean-manifest.json']]
    neural=ScreenshotRecognizer();legacy=TemplateRecognizer();rows=[];milliseconds=[]
    with tempfile.TemporaryDirectory() as temporary:
        for game in [g for manifest in manifests for g in manifest['games']]:
            store=Store(Path(temporary)/game['id']);manager=GameManager(store,Settings());ground=chess.Board();frames=[];extra=[]
            for frame in game['frames']:
                if frame['san']:ground.push_san(frame['san'])
                image=cv2.imread(str(FIXTURES/frame['file']));started=time.perf_counter()
                observed=neural.recognize(image,frame['orientation']);milliseconds.append((time.perf_counter()-started)*1000)
                old=legacy.recognize(image,frame['orientation']);expected=board_labels(ground)
                manager.process(observed)
                frames.append({'file':frame['file'],'new_square_errors':int((observed.labels!=expected).sum()),
                               'legacy_square_errors':int((old.labels!=expected).sum()),'weakest_score':observed.weakest_confidence})
            expected_moves=[move.uci() for move in ground.move_stack]
            pgn=store.game(manager.current_id)['pgn'] if manager.current_id else ''
            parsed=chess.pgn.read_game(io.StringIO(pgn))
            for sample in game.get('extra_frames',[]):
                probe_store=Store(Path(temporary)/sample['file']);probe=GameManager(probe_store,Settings())
                for frame in game['frames'][:sample['after_ply']+1]:
                    probe.process(neural.recognize(cv2.imread(str(FIXTURES/frame['file'])),frame['orientation']))
                previous=list(probe.rec.verified)
                observed=choose_orientation(neural.recognize(cv2.imread(str(FIXTURES/sample['file']))),probe.rec.board)
                probe.process(observed)
                extra.append({'file':sample['file'],'scenario':sample['scenario'],
                              'verified_prefix_preserved':probe.rec.verified==previous,'status':probe.last_message,
                              'weakest_score':observed.weakest_confidence})
                probe_store.close()
            compression=[]
            for frame in [game['frames'][0],game['frames'][-1]]:
                image=cv2.resize(cv2.imread(str(FIXTURES/frame['file'])),(416,416),interpolation=cv2.INTER_AREA)
                _,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,40])
                observed=neural.recognize(cv2.imdecode(encoded,cv2.IMREAD_COLOR),frame['orientation'])
                compression.append({'file':frame['file'],'size':416,'jpeg_quality':40,
                                    'square_errors':int((observed.labels!=board_labels(chess.Board(frame['fen']))).sum())})
            rows.append({'id':game['id'],'texture':game['texture'],'calibration':False,'frames':frames,
                         'expected_plies':len(expected_moves),'verified_plies':len(manager.rec.verified) if manager.rec else 0,
                         'complete_sequence_correct':bool(manager.rec and manager.rec.verified==expected_moves),
                         'pgn_roundtrip_correct':bool(parsed and not parsed.errors and [m.uci() for m in parsed.mainline_moves()]==expected_moves),
                         'extra_frames':extra,'compressed_frames':compression})
            if pgn:(ROOT/'examples'/f'{game["id"]}-theme.pgn').write_text(pgn+'\n')
            store.close()
    report={'version':'1.1.0','environment':platform.platform(),'dataset_provenance':manifests,
            'model':json.loads((ROOT/'chessstream/assets/models/chess-tiles-v2.json').read_text()),
            'metrics':{'clear_frames':sum(len(r['frames']) for r in rows),'evaluated_squares':64*sum(len(r['frames']) for r in rows),
                       'legacy_template_square_errors':sum(f['legacy_square_errors'] for r in rows for f in r['frames']),
                       'new_model_square_errors':sum(f['new_square_errors'] for r in rows for f in r['frames']),
                       'correct_complete_sequences':sum(r['complete_sequence_correct'] for r in rows),
                       'sequences':len(rows),'mean_inference_ms':float(np.mean(milliseconds)),
                       'p95_inference_ms':float(np.percentile(milliseconds,95)),
                       'process_rss_mb':psutil.Process().memory_info().rss/1024**2},
            'games':rows,'limitations':['Controlled browser captures, not a YouTube reliability study.',
                'Posted inline samples were visually inspected; executable tests use the corresponding captured Chess.com piece style, not byte-identical copies of those inline uploads.',
                'Compressed checks are degradations of real browser captures, not real video recordings.',
                'A model score is not a calibrated accuracy probability; unseen sets and heavy overlays can still fail.',
                'Timing is Linux CPU inference, excluding capture and GUI. RSS includes both new and legacy recognizers.']}
    (ROOT/'docs/recognition-v1.1.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['metrics'],indent=2))


if __name__=='__main__':main()
