"""Developer-only regeneration of bundled audio fingerprints; requires ffmpeg.
Downloads published default sounds, records source hashes, and updates the preset JSON.
The desktop application never downloads or learns sounds.
"""
import json,urllib.request,subprocess,hashlib,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chessstream.audio import CueDetector,RATE,BLOCK
out=[]
items=[('Lichess','Move','move','https://lichess1.org/assets/sound/standard/Move.ogg'),('Lichess','Capture','capture','https://lichess1.org/assets/sound/standard/Capture.ogg')]
items += [('Chess.com',name,kind,'https://images.chesscomfiles.com/chess-themes/sounds/_MP3_/default/'+name+'.mp3') for name,kind in [('move-self','move'),('move-opponent','move'),('capture','capture'),('castle','move'),('move-check','move')]]
for site,name,kind,url in items:
 data=urllib.request.urlopen(url,timeout=20).read()
 sound=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i','pipe:0','-f','f32le','-ac','1','-ar',str(RATE),'-'],input=data),np.float32)
 d=CueDetector();d.learn(kind,0)
 x=np.concatenate([np.zeros(RATE//2),sound,np.zeros(RATE)])
 for i in range(0,len(x),BLOCK):
  block=x[i:i+BLOCK]
  if len(block)<BLOCK:block=np.pad(block,(0,BLOCK-len(block)))
  d.feed(block,(i+BLOCK)/RATE)
 assert kind in d.templates,(site,name,d.status)
 out.append(dict(name=site+' '+name,kind=kind,source=url,sha256=hashlib.sha256(data).hexdigest(),vector=np.round(d.templates[kind],7).tolist()))
 print(site,name,len(data))
(ROOT/'chessstream/assets/audio-presets.json').write_text(json.dumps(dict(version=1,description='Normalized spectral identification features only; no playable audio.',templates=out),separators=(',',':'))+'\n')
