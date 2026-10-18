"""Reproducible end-to-end evaluation on actual captured browser board images."""
from __future__ import annotations
from pathlib import Path
import argparse
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
from chessstream.domain import Settings,board_labels
from chessstream.games import GameManager
from chessstream.storage import Store
from chessstream.vision import ScreenshotRecognizer,BoardDetector,choose_orientation

ROOT=Path(__file__).resolve().parents[1]
REAL=ROOT/'tests/fixtures/real'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'docs/evaluation.json');args=parser.parse_args()
    manifest=json.loads((REAL/'manifest.json').read_text())
    process=psutil.Process();start=time.perf_counter();cpu_start=sum(process.cpu_times()[:2]);samples=[]
    stats=[];detected=[];verified_correct=0;verified_total=0;piece_correct=0;piece_total=0;exact_frames=0;frames_total=0;interventions=0
    example=ROOT/'examples';example.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        for game in manifest['games']:
            store=Store(Path(td)/game['id']);settings=Settings();manager=GameManager(store,settings)
            recognizer=ScreenshotRecognizer();calibration='none'
            times=[];bad=0;exact=0;expected=[];ground=chess.Board();last_verified=0
            for frame in game['frames']:
                if frame['san']:
                    move=ground.parse_san(frame['san']);expected.append(move.uci());ground.push(move)
                image=cv2.imread(str(REAL/frame['file']));t=time.perf_counter();obs=recognizer.recognize(image)
                obs=choose_orientation(obs,manager.rec.board if manager.rec else None)
                manager.process(obs);times.append((time.perf_counter()-t)*1000)
                correct=int(np.sum(obs.labels==board_labels(chess.Board(frame['fen']))));bad+=64-correct;exact+=int(correct==64)
                frames_total+=1
                piece_correct+=correct;piece_total+=64;exact_frames+=int(correct==64)
                if manager.rec:
                    moves=manager.rec.verified
                    for i in range(last_verified,len(moves)):
                        verified_total+=1;verified_correct+=int(i<len(expected) and moves[i]==expected[i])
                    last_verified=len(moves)
            automatic_plies=len(manager.rec.verified) if manager.rec else 0
            final_review=bool(manager.rec and manager.rec.verified==expected[:-1] and manager.snapshot().get('provisional'))
            if final_review:manager.choose(0)
            complete=bool(manager.rec and manager.rec.verified==expected)
            if final_review or not complete:interventions+=1
            row=store.game(manager.current_id)
            pgn=chess.pgn.read_game(io.StringIO(row['pgn'])) if row else None
            roundtrip=bool(pgn and not pgn.errors and list(pgn.mainline_moves())==[chess.Move.from_uci(m) for m in expected])
            if row:(example/(game['id']+'.pgn')).write_text(row['pgn']+'\n')
            # Test a two-ply gap on the same real images with the same recognizer.
            gap_store=Store(Path(td)/(game['id']+'-gaps'));gap_manager=GameManager(gap_store,settings)
            indices=sorted(set([0]+list(range(2,len(game['frames']),2))+[len(game['frames'])-1]))
            for index in indices:
                image=cv2.imread(str(REAL/game['frames'][index]['file']));obs=recognizer.recognize(image)
                obs=choose_orientation(obs,gap_manager.rec.board if gap_manager.rec else None);gap_manager.process(obs)
            if gap_manager.snapshot().get('provisional') and gap_manager.rec.verified==expected[:-1]:gap_manager.choose(0)
            gaps_correct=bool(gap_manager.rec and gap_manager.rec.verified==expected)
            stats.append({'id':game['id'],'calibration':calibration,'frames':len(game['frames']),
                'square_errors':bad,'exact_positions':exact,'verified_plies':len(manager.rec.verified) if manager.rec else 0,
                'expected_plies':len(expected),'automatic_verified_plies':automatic_plies,'final_confirmation_required':final_review,'complete_sequence_correct':complete,'pgn_roundtrip_correct':roundtrip,
                'two_ply_gap_sequence_correct':gaps_correct,'mean_processing_ms':float(np.mean(times)),
                'p95_processing_ms':float(np.percentile(times,95))})
            # Localization is assessed separately on full browser screenshots.
            page=REAL/(game['id']+'-page.png')
            image=cv2.imread(str(page));t=time.perf_counter();rect,score=BoardDetector().detect(image)
            detection={'file':page.name,'found':rect is not None,'rect':rect,'checker_score':score,'ms':(time.perf_counter()-t)*1000}
            if rect:
                x,y,w,h=rect;obs=recognizer.recognize(image[y:y+h,x:x+w]);detection['correct_position_after_crop']=obs.placement()==chess.Board().board_fen()
            detected.append(detection)
            print(json.dumps(stats[-1]),flush=True)
            store.close();gap_store.close()
    elapsed=time.perf_counter()-start;cpu_seconds=sum(process.cpu_times()[:2])-cpu_start
    report={'recording_policy':'Conservative opponent-response confirmation; evaluator explicitly confirms each final pending ply once. Automatic move accuracy excludes those manual final confirmations.','environment':{'os':platform.platform(),'python':platform.python_version(),'cpu_count':psutil.cpu_count(),
                'execution':'Linux cloud CPU, sequential image replay; not a Windows/YouTube live benchmark'},
            'dataset':{'source':manifest['method'],'captured_at':manifest['captured_at'],'frames':frames_total,'games':len(stats),
                'evaluated_frames_excluding_calibration':piece_total//64,
                'scope':'Three complete short/classic Lichess games and one 16-ply Chess.com opening; all 64 PNG frames evaluated without calibration. Additional textured theme captures are evaluated separately in recognition-v1.2.json. Not a YouTube benchmark.'},
            'metrics':{'square_accuracy':piece_correct/piece_total,'evaluated_squares':piece_total,'exact_position_accuracy':exact_frames/(piece_total//64),
                'verified_move_accuracy':verified_correct/verified_total if verified_total else None,
                'complete_sequence_accuracy':sum(g['complete_sequence_correct'] for g in stats)/len(stats),
                'sequence_intervention_rate':interventions/len(stats),'localization_found_rate':sum(d['found'] for d in detected)/len(detected),
                'one_time_setup_calibrations':0,
                'sequences_requiring_any_manual_confirmation_rate':interventions/len(stats),
                'localization_followed_by_correct_recognition_rate':sum(d.get('correct_position_after_crop',False) for d in detected)/len(detected),
                'wall_seconds':elapsed,'process_cpu_seconds':cpu_seconds,'mean_process_cpu_percent_of_one_core':cpu_seconds/elapsed*100,
                'resident_memory_mb_at_end':process.memory_info().rss/1024**2,'gpu_utilization':'not measured; CPU inference only'},
            'games':stats,'board_detection':detected,
            'limitations':['Small controlled suite; these values are not general stream accuracy claims.',
                'The 16-ply Chess.com opening is a complete captured sequence, not a completed game.',
                'PNG browser captures do not represent video compression, occlusion and animations in YouTube.',
                'UI, desktop capture overhead and Windows GPU/CPU behavior are excluded from this benchmark.']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2))
    print('Report:',args.output)


if __name__=='__main__':main()
