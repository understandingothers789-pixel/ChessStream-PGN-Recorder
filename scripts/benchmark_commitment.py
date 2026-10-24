"""Small reproducible CPU search benchmark; no screen capture or network."""
import argparse
import json
from pathlib import Path
import statistics
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chess
import chess.pgn
from chessstream.commitment import assess_search
from chessstream.domain import Observation
from chessstream.gap_join import _gap_search
from chessstream.reconstruction import LegalSearcher
from chessstream.games import GameManager
from chessstream.storage import Store
from chessstream.domain import Settings,utcnow


def played(line):
    board=chess.Board()
    for san in line.split():board.push_san(san)
    return board


def benchmark(repeats):
    start=chess.Board()
    two=Observation.from_board(played('e4 e5'))
    four=Observation.from_board(played('Nf3 Nf6 Nc3 Nc6'))
    source=chess.Board('r3r1k1/1p1qppbp/p1n2np1/1B1p2N1/3P1B2/1Q2P2P/PP3PP1/2R2RK1 b - - 1 25')
    target=chess.pgn.Game()
    target.setup(chess.Board('r3r1k1/3qppbp/p1p2np1/3p2N1/3P1B2/1Q2P2P/PP3PP1/2R2RK1 w - - 0 1'))
    cases=[
        ('unique_two_plies',start,two,lambda:LegalSearcher().search(start,two)),
        ('ambiguous_four_knights',start,four,lambda:LegalSearcher().search(start,four)),
        ('live_checkpoint_budget_75ms',source,Observation.from_board(target.board()),
         lambda:_gap_search(source,target,LegalSearcher(4,8000,75),deep_search=False)),
        ('background_saved_gap_budget_5000ms',source,Observation.from_board(target.board()),
         lambda:_gap_search(source,target,LegalSearcher())),
    ]
    output={}
    for label,board,obs,run in cases:
        timings=[];result=None
        for _ in range(repeats):
            began=perf_counter();result=run();timings.append((perf_counter()-began)*1000)
        output[label]={'mean_ms':round(statistics.mean(timings),3),'worst_ms':round(max(timings),3),
                       'nodes':result.nodes,'paths':len(result.paths),'exhaustive':result.exhaustive,
                       'classification':assess_search(board,result,obs).kind,'stop_reason':result.stop_reason}
    with TemporaryDirectory() as folder:
        store=Store(Path(folder));manager=GameManager(store,Settings())
        manager._create(chess.Board(),utcnow());timings=[]
        for index in range(64):
            began=perf_counter()
            manager.trace_frame(two,2,{'status':f'diagnostic timing group {index//4}'})
            timings.append((perf_counter()-began)*1000)
        output['fen_trace_64_comparisons']={
            'mean_ms':round(statistics.mean(timings),3),'worst_ms':round(max(timings),3),
            'retained_transitions':store.query('SELECT COUNT(*) AS n FROM board_trace')[0]['n'],
            'metadata_bytes':store.query('SELECT SUM(LENGTH(detail)) AS n FROM board_trace')[0]['n']}
        store.close()
    return {'repeats':repeats,'scope':'Local legal search and SQLite metadata tracing; excludes OCR, capture, and real-video acceptance','results':output}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not 1<=args.repeats<=20:parser.error('repeats must be between 1 and 20')
    report=json.dumps(benchmark(args.repeats),indent=2)
    if args.output:args.output.write_text(report+'\n',encoding='utf-8')
    print(report)
