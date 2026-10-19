"""Optional developer benchmark; never part of normal application startup/tests.

The optional baseline is imported from an explicitly selected trusted Git ref.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import chess
from chessstream.domain import Observation
from chessstream.reconstruction import LegalSearcher


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline-ref',help='Trusted local Git revision to compare with')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    if not 1<=args.repeats<=20:parser.error('repeats must be between 1 and 20')
    implementations={'optimized':LegalSearcher}
    with tempfile.TemporaryDirectory() as folder:
        if args.baseline_ref:
            source=subprocess.run(['git','show',f'{args.baseline_ref}:chessstream/reconstruction.py'],
                                  check=True,capture_output=True).stdout
            path=Path(folder)/'baseline.py';path.write_bytes(source)
            spec=importlib.util.spec_from_file_location('chessstream._benchmark_baseline',path)
            module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
            spec.loader.exec_module(module)
            implementations['baseline']=module.LegalSearcher
        cases=[('reported_Qxd4','e4 e6 d4 d5 e5 c5 Bb5+ Bd7 a4 cxd4','Qxd4'),
               ('pending_plus_Qxd4','e4 e6 d4 d5 e5 c5 Bb5+ Bd7 a4','cxd4 Qxd4'),
               ('three_missing_plies','e4 e5 Nf3 Nc6 Bc4 Bc5 d4 Bxd4 c3 Bb6','Ng5 Nh6 Qf3'),
               ('four_ply_equal_orders','','Nf3 Nf6 Nc3 Nc6'),
               ('unrelated_opening','e4',None)]
        report={'environment':platform.platform(),'python':platform.python_version(),
                'baseline_ref':args.baseline_ref,'repeats':args.repeats,
                'limits':{'max_plies':4,'nodes':60000,'milliseconds':350},
                'provenance':'Qxd4 source/target placements transcribed from user screenshots; remaining cases are controlled legal positions.',
                'cases':[]}
        for name,prefix,line in cases:
            board=chess.Board()
            for san in prefix.split():board.push_san(san)
            target=board.copy() if line else chess.Board()
            for san in (line or 'd4').split():target.push_san(san)
            item={'name':name,'source_fen':board.fen(),'target_fen':target.fen(),'results':{}}
            exact={}
            for label,cls in implementations.items():
                runs=[cls(4,60000,350).search(board,Observation.from_board(target)) for _ in range(args.repeats)]
                last=runs[-1]
                item['results'][label]={'median_ms':round(statistics.median(r.elapsed_ms for r in runs),3),
                    'median_nodes':statistics.median(r.nodes for r in runs),'paths':len(last.paths),
                    'exhaustive':last.exhaustive,'depth':last.depth}
                if last.exhaustive:exact[label]={tuple(move.uci() for move in path) for path in last.paths}
            if len(exact)==2:assert exact['optimized']==exact['baseline'],name
            report['cases'].append(item)
    output=json.dumps(report,indent=2)+'\n'
    if args.output:args.output.write_text(output,encoding='utf-8')
    else:print(output)


if __name__=='__main__':main()
