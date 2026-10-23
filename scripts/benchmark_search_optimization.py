"""Compare the current search with our trusted, committed pre-optimization code.

Run from the repository root with the project Python environment. The reference
is deliberately pinned to a reviewed local Git commit, never downloaded code.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chessstream.reconstruction import LegalSearcher
from scripts import benchmark_gap_continuity as fixture
revision='ed253d6e2ff7c7fe4b0f808eb285a376b3a62114'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repeats',type=int,default=5)
parser.add_argument('--output',type=Path)
args=parser.parse_args()
if not 1<=args.repeats<=20:parser.error('repeats must be between 1 and 20')
with tempfile.TemporaryDirectory() as temporary:
    path=Path(temporary)/'reference.py'
    path.write_bytes(subprocess.check_output(['git','show',f'{revision}:chessstream/reconstruction.py']))
    spec=importlib.util.spec_from_file_location('chessstream._benchmark_reference',path)
    reference=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=reference
    spec.loader.exec_module(reference)
    runs={'before':[],'after':[]}
    for repeat in range(args.repeats):
        # Alternate order to reduce systematic warmup and scheduling bias.
        order=('before','after') if repeat%2==0 else ('after','before')
        for name in order:
            fixture.LegalSearcher=reference.LegalSearcher if name=='before' else LegalSearcher
            runs[name].append(fixture.benchmark(1)['results'])
    report={'reference_commit':revision,'repeats':args.repeats,'scope':'Interleaved local CPU search only; no capture, OCR or video benchmark','results':{}}
    for case in runs['before'][0]:
        values={}
        for name in ('before','after'):
            outcomes=[run[case]['travel_bound'] for run in runs[name]]
            assert all(result['paths_sha256']==outcomes[0]['paths_sha256'] for result in outcomes)
            values[name]={'mean_ms':round(statistics.mean(result['mean_ms'] for result in outcomes),3),'worst_ms':max(result['worst_ms'] for result in outcomes),'nodes':outcomes[0]['nodes'],'paths':outcomes[0]['paths'],'paths_sha256':outcomes[0]['paths_sha256']}
        assert values['before']['paths_sha256']==values['after']['paths_sha256']
        values['same_shortest_paths']=True
        values['time_reduction_percent']=round(100*(1-values['after']['mean_ms']/values['before']['mean_ms']),1)
        report['results'][case]=values
    output=json.dumps(report,indent=2)+'\n'
    if args.output:args.output.write_text(output,encoding='utf-8')
    print(output)
