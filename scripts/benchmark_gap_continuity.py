"""Compare identical exhaustive searches with/without the travel lower bound."""
import argparse
import json
from pathlib import Path
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chess
from chessstream.domain import Observation
from chessstream.reconstruction import LegalSearcher


def played(line,source=None):
    board=source.copy() if source else chess.Board()
    for san in line.split():board.push_san(san)
    return board


def benchmark(repeats):
    tactical=played('e4 e5 Nf3 Nc6 Bc4 Bc5 Bxf7+')
    middlegame=chess.Board('r3r1k1/1p1qppbp/p1n2np1/1B1p2N1/3P1B2/1Q2P2P/PP3PP1/2R2RK1 b - - 1 25')
    targets=[('routine_two_plies',chess.Board(),played('e4 e5'),4),
        ('six_ply_capture_gap',tactical,played('Kxf7 Nxe5+ Nxe5 d4 Bxd4 Qxd4',tactical),6),
        ('saved_middlegame_gap',middlegame,chess.Board('r3r1k1/3qppbp/p1p2np1/3p2N1/3P1B2/1Q2P2P/PP3PP1/2R2RK1 w - - 0 1'),9)]
    report={}
    for name,source,target,depth in targets:
        outcomes={};routes={}
        for optimized in (False,True):
            results=[LegalSearcher(depth,600000,5000,path_limit=256,travel_bound=optimized).search(source,Observation.from_board(target))
                     for _ in range(repeats)]
            if not all(result.exhaustive for result in results):raise RuntimeError('Benchmark did not complete within its budget')
            routes[optimized]={tuple(move.uci() for move in path) for path in results[-1].paths}
            outcomes['travel_bound' if optimized else 'baseline']={
                'mean_ms':round(statistics.mean(result.elapsed_ms for result in results),3),
                'worst_ms':round(max(result.elapsed_ms for result in results),3),
                'nodes':results[-1].nodes,'depth':results[-1].depth,'paths':len(routes[optimized])}
        if routes[False]!=routes[True]:raise RuntimeError('Optimization changed shortest alternatives')
        outcomes['same_shortest_paths']=True;report[name]=outcomes
    return {'repeats':repeats,'scope':'Local CPU search only, identical fixtures and budgets, no OCR/capture/video accuracy measurement',
            'results':report}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    if not 1<=args.repeats<=20:parser.error('repeats must be between 1 and 20')
    output=json.dumps(benchmark(args.repeats),indent=2)
    if args.output:args.output.write_text(output+'\n',encoding='utf-8')
    print(output)
