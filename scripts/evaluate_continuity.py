"""Compare legal continuity against the previous exact-label reconstruction.

The image corpus is retained browser captures. Deliberately altered classifier
scores form a separate fault-injection experiment, never a stream accuracy claim.
Only a JSON report is written; no screenshot images are created.
"""
import argparse
import json
import platform
from pathlib import Path
import time
import chess
import cv2
import numpy as np
import psutil
from chessstream.domain import LABELS,Observation,board_labels
from chessstream.reconstruction import Reconstructor
from chessstream.vision import ScreenshotRecognizer

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'tests/fixtures'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'docs/recognition-continuity-v1.6.4.json')
    args=parser.parse_args()
    model=ScreenshotRecognizer();cache={};samples={};latencies=[];before_ms=[];after_ms=[];sequences=[]
    process=psutil.Process();started=time.perf_counter();cpu_started=sum(process.cpu_times()[:2])

    def observe(group,frame):
        key=(group,frame['file'],frame['orientation'])
        if key not in cache:
            image=cv2.imread(str(FIXTURES/group/frame['file']))
            if image is None:raise ValueError('Missing browser capture: '+frame['file'])
            tick=time.perf_counter();cache[key]=model.recognize(image,frame['orientation'])
            latencies.append((time.perf_counter()-tick)*1000)
        if frame.get('kind')!='hover':
            samples[key]=int(np.count_nonzero(cache[key].labels!=board_labels(chess.Board(frame['fen']))))
        return cache[key]

    def replay(group,name,frames,initial_fen=chess.STARTING_FEN):
        initial=chess.Board(initial_fen);ground=initial.copy();expected=[]
        old=Reconstructor(initial,confirmation_plies=1);new=Reconstructor(initial,confirmation_plies=1)
        old_correct=new_correct=True
        for frame in frames:
            if frame.get('kind')!='hover' and frame['fen'].split()[0]!=ground.board_fen():
                moves=[]
                for move in ground.legal_moves:
                    board=ground.copy();board.push(move)
                    if board.board_fen()==frame['fen'].split()[0]:moves.append(move)
                if len(moves)!=1:raise ValueError('Non-unique ground-truth transition in '+frame['file'])
                expected.append(moves[0].uci());ground.push(moves[0])
            raw=observe(group,frame)
            for _ in range(8 if frame.get('kind')=='hover' else 1):
                tick=time.perf_counter();old._observe_exact(raw);before_ms.append((time.perf_counter()-tick)*1000)
                tick=time.perf_counter();new.observe(raw);after_ms.append((time.perf_counter()-tick)*1000)
                old_correct &= old.verified==expected[:len(old.verified)]
                new_correct &= new.verified==expected[:len(new.verified)]
        def endpoint_matches(rec):
            return bool(rec.branches and all(b.board().board_fen()==ground.board_fen() for b in rec.branches))
        sequences.append({'id':name,'expected_plies':len(expected),
            'baseline_verified_plies':len(old.verified),'updated_verified_plies':len(new.verified),
            'baseline_every_verified_prefix_correct':old_correct,
            'updated_every_verified_prefix_correct':new_correct,
            'baseline_final_candidate_matches':endpoint_matches(old),'updated_final_candidate_matches':endpoint_matches(new)})

    for group,filename in [('real','manifest.json'),('themes','manifest.json'),
                           ('themes','chesscom-ocean-manifest.json'),('confirmation','manifest.json')]:
        manifest=json.loads((FIXTURES/group/filename).read_text())
        for game in manifest.get('games',manifest.get('cases',[])):
            replay(group,game['id'],game['frames'],game.get('initial_fen',chess.STARTING_FEN))
            for extra in game.get('extra_frames',[]):
                if 'drag' in extra['file']:continue  # held drags have dedicated sequences above
                prefix=game['frames'][:extra['after_ply']+1]
                frame={**prefix[-1],'file':extra['file'],'kind':'annotation'}
                replay(group,extra['file'],prefix+[frame])

    faults=[]
    for name,line,square,wrong,alternative in [
        ('missing queen','e4',chess.D1,'.','Q'),
        ('queen mistaken for knight','e4 e5',chess.D1,'N','Q'),
        ('queen color flip','e4 e5',chess.D1,'q','Q'),
        ('phantom extra knight','e4',chess.H3,'N','.'),
        ('capture without queen sacrifice detour','e4 d5 exd5',chess.D1,'.','Q')]:
        ground=chess.Board();old=Reconstructor(ground);new=Reconstructor(ground);recovered=[]
        for san in line.split():
            ground.push_san(san);raw=Observation.from_board(ground)
            raw.probabilities[square]=.02/(len(LABELS)-2)
            raw.probabilities[square,LABELS.index(wrong)]=.82
            raw.probabilities[square,LABELS.index(alternative)]=.16
            old._observe_exact(raw);update=new.observe(raw)
            recovered.extend(chess.square_name(s) for s in update.ignored_squares)
        expected=[move.uci() for move in ground.move_stack]
        faults.append({'case':name,'expected':expected,'baseline':old.verified,'updated':new.verified,
            'baseline_correct':old.verified==expected,'updated_correct':new.verified==expected,
            'uncertain_squares':sorted(set(recovered))})

    elapsed=time.perf_counter()-started;cpu=sum(process.cpu_times()[:2])-cpu_started
    report={'version':'1.6.4','environment':{'platform':platform.platform(),'python':platform.python_version(),
        'execution':'Linux cloud CPU; local images, excluding desktop capture and GUI'},
        'baseline':'Identical bundled model and legal search, with the new continuity retry disabled.',
        'browser_captures':{'unique_images_including_held_drags':len(cache),'positions_evaluated':len(samples),
            'square_classifications_evaluated':64*len(samples),'raw_model_square_errors_before':sum(samples.values()),
            'raw_model_square_errors_after':sum(samples.values()),'sequences':sequences},
        'controlled_classifier_faults':{'method':'Synthetic score faults, not newly captured visual errors: wrong label 0.82, existing legal label 0.16, others share 0.02.',
            'cases':faults,'baseline_correct':sum(row['baseline_correct'] for row in faults),
            'updated_correct':sum(row['updated_correct'] for row in faults)},
        'performance':{'model_mean_ms':float(np.mean(latencies)),
            'baseline_reconstruction_mean_ms':float(np.mean(before_ms)),
            'updated_reconstruction_mean_ms':float(np.mean(after_ms)),
            'updated_reconstruction_p95_ms':float(np.percentile(after_ms,95)),
            'wall_seconds':elapsed,'process_cpu_seconds':cpu,'resident_memory_mb':process.memory_info().rss/1024**2},
        'limitations':['The model weights and raw classifier accuracy did not change. These captures already have zero raw square errors; this establishes regression coverage, not an improvement percentage on real videos.',
            'Fault-injection recovery counts describe only the specified controlled score errors.',
            'The retry carries at most two uncertain unchanged squares, checks at most two new plies and is bounded by 50 ms and 8000 nodes.',
            'Strong contradictions, heavy overlays, uncertain move endpoints and unseen themes may still require more evidence or manual correction.',
            'The initial FEN is known in this reconstruction comparison. Initial detection/recognition remains covered separately by desktop tests.',
            'Timing and memory are Linux process measurements; Windows/YouTube hardware behavior requires live acceptance.']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'positions':len(samples),'raw_square_errors':sum(samples.values()),
        'sequences_correct':sum(s['updated_every_verified_prefix_correct'] and s['updated_final_candidate_matches'] for s in sequences),
        'sequences':len(sequences),'faults_before':report['controlled_classifier_faults']['baseline_correct'],
        'faults_after':report['controlled_classifier_faults']['updated_correct'],'performance':report['performance']},indent=2))
    if not all(s['updated_every_verified_prefix_correct'] and s['updated_final_candidate_matches'] for s in sequences):
        raise SystemExit('Actual browser capture reconstruction regression')
    if not all(row['updated_correct'] for row in faults):raise SystemExit('Controlled continuity recovery regression')


if __name__=='__main__':main()
