"""Measured OCR evaluation on native Chromium Chess.com screenshots, no network."""
from pathlib import Path
import hashlib
import json
import time
import psutil
import cv2
from chessstream.results import LocalTextReader,parse_end_message,extract_context

ROOT=Path(__file__).resolve().parents[1]

def main():
    process=psutil.Process();before=process.memory_info().rss;start=time.perf_counter();reader=LocalTextReader();init=time.perf_counter()-start
    cases=[]
    expected={
        'native-bot-start.png':(None,{'black':600,'white':597}),
        'native-bot-clock.png':(None,{'black':597,'white':596}),
        'native-bot-aborted.png':('*',{'black':599,'white':594}),
        'native-bot-resigned.png':('0-1',{'black':595,'white':593}),
    }
    for file,(result,clocks) in expected.items():
        path=ROOT/'tests/fixtures/results'/file;image=cv2.imread(str(path));t=time.perf_counter();cpu=process.cpu_times()
        lines=reader.read(image);context=extract_context(lines,(108,66,568,568),'white')
        message=parse_end_message(lines,'white',context['names']);elapsed=time.perf_counter()-t;after_cpu=process.cpu_times()
        case={'file':file,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'expected_result':result,'detected_result':message.result if message else None,'expected_clocks':clocks,'observed_clocks':context['clocks'],'observed_names':context['names'],'elapsed_ms':round(elapsed*1000,1),'cpu_seconds':round(after_cpu.user+after_cpu.system-cpu.user-cpu.system,4)}
        case['passed']=case['expected_result']==case['detected_result'] and clocks==context['clocks'] and context['names']=={'white':'Guest','black':'Martinfoot'}
        cases.append(case)
    report={'method':'Four native Chromium Chess.com guest bot screenshots: genuine game-aborted and named-winner resignation dialogs, genuine clocks/names. Ocean/Walnut artwork chosen with CSS for recognition; no text or result injection. Expected clocks manually transcribed from retained images. Controlled corpus; not an arbitrary-stream accuracy estimate.','initialization_ms':round(init*1000,1),'cpu_provider':'ONNX Runtime CPUExecutionProvider, two inference threads','rss_after_mb':round(process.memory_info().rss/1e6,1),'rss_increase_mb':round((process.memory_info().rss-before)/1e6,1),'cases':cases,'passed':all(c['passed'] for c in cases),'limitations':'English horizontal text, selected area must include context. Clock readings are sampled, not exact release times. GPU utilization and full Windows capture load were not measured.'}
    (ROOT/'docs/context-v1.4.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));assert report['passed']

if __name__=='__main__':main()
