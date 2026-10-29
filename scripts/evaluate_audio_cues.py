"""Evaluate local Lichess Move.ogg/Capture.ogg samples; no automatic download.

Usage: python scripts/evaluate_audio_cues.py --sound-dir /path/to/samples
Requires ffmpeg for this developer evaluation only, not for the application.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chessstream.audio import CueDetector,RATE,BLOCK


def feed(detector,samples,start):
    for index in range(0,len(samples),BLOCK):
        block=samples[index:index+BLOCK]
        if len(block)<BLOCK:block=np.pad(block,(0,BLOCK-len(block)))
        detector.feed(block,start+(index+BLOCK)/RATE)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sound-dir',required=True,type=Path)
    args=parser.parse_args();report=[]
    for name in ('Move','Capture'):
        path=next((args.sound_dir/(name+ext) for ext in ('.ogg','.mp3')
                   if (args.sound_dir/(name+ext)).exists()), args.sound_dir/(name+'.ogg'))
        raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-ac','1','-ar',str(RATE),'-'])
        sound=np.frombuffer(raw,np.float32)
        learned=CueDetector();learned.learn(name.lower() if name=='Capture' else 'move',0)
        feed(learned,np.zeros(RATE//2),0);feed(learned,np.pad(sound,(0,RATE)),.5)
        if not learned.templates:raise RuntimeError(f'Could not learn {name}')
        for offset in (0,112,208):
            detector=CueDetector();detector.templates=dict(learned.templates)
            samples=np.pad(sound*.4,(RATE//2+offset,RATE//2));t=np.arange(len(samples))/RATE
            samples+=.001*(np.sin(2*np.pi*145*t)+np.sin(2*np.pi*290*t))
            before=time.perf_counter();feed(detector,samples,2);elapsed=time.perf_counter()-before
            report.append({'sound':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'offset_ms':offset/RATE*1000,'cues':detector.count,'events':list(detector.events),
                'cpu_ms_per_audio_second':round(elapsed*1000/(len(samples)/RATE),3)})
    print(json.dumps(report,indent=2))
    if any(item['cues']!=1 for item in report):raise SystemExit('Sound trials failed')


if __name__=='__main__':main()
