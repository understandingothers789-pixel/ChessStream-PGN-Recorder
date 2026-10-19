"""Offline text recognition of end-of-game messages; no chess-site integration."""
from dataclasses import dataclass
from pathlib import Path
import re
import time
import cv2
import numpy as np
from .model_security import validate_bgr_image, verify_bundled_model


@dataclass(frozen=True)
class EndMessage:
    result: str
    reason: str
    text: str
    confidence: float
    color_basis: str = "explicit result text"


def parse_end_message(lines, player_color=None, names=None):
    """Only strong end-message vocabulary can terminate a game, never arbitrary digits."""
    strong=[(re.sub(r'\b(You|White|Black|Game)(Won|Lost|Aborted|Abandoned)\b',r'\1 \2',str(text).strip().replace('–','-').replace('−','-'),flags=re.I),score) for text,score,*_ in lines if score >= .80]
    strong=[(text,score) for text,score in strong if re.search(r'\b(won|wins|lost|draw|drawn|stalemate|checkmate|abandoned|resigned|resignation|timeout|time out|game over|game ended|aborted)\b',text,re.I) or re.fullmatch(r'\s*(?:1\s*-\s*0|0\s*-\s*1|1/2\s*-\s*1/2|½\s*-\s*½)\s*',text)]
    good=[text for text,score in strong]
    text=" | ".join(good)
    normalized=re.sub(r"\s+"," ",text.lower().replace('½','1/2').replace('–','-').replace('−','-'))
    if not normalized:return None
    aborted=bool(re.search(r'\b(game\s+)?abort(?:ed)?\b',normalized))
    context=bool(re.search(r'\b(won|wins|lost|draw|drawn|stalemate|checkmate|abandoned|resigned|resignation|timeout|time out|game over|game ended|aborted)\b',normalized))
    if not context and not re.fullmatch(r'(?:1-0|0-1|1/2-1/2)',normalized.replace(' ','')):return None
    reason=next((word for word in ['aborted','abandoned','checkmate','stalemate','resignation','timeout'] if word in normalized),'game ended')
    confidence=min(score for _,score in strong)
    if aborted:return EndMessage('*','aborted',text,confidence)
    if re.search(r'(?<!\d)1\s*/\s*2\s*-\s*1\s*/\s*2(?!\d)|\b(draw|drawn|stalemate)\b',normalized):
        return EndMessage('1/2-1/2',reason,text,confidence)
    scores=set(re.findall(r'(?<![\d/])([01]\s*-\s*[01])(?![\d/])',normalized))
    scores={s.replace(' ','') for s in scores}&{'1-0','0-1'}
    if len(scores)==1:return EndMessage(scores.pop(),reason,text,confidence)
    if len(scores)>1:return None
    for color,result in [('white','1-0'),('black','0-1')]:
        if re.search(r'\b'+color+r'\s+(won|wins)\b',normalized):return EndMessage(result,reason,text,confidence)
        name=(names or {}).get(color)
        if name and re.search(r'(?<!\w)'+re.escape(name.lower())+r'\s+(won|wins)\b',normalized):
            return EndMessage(result,reason,text,confidence,'winner name matched a previously observed player name')
    if re.search(r'\byou\s+(won|win|lost|lose)\b',normalized):
        if player_color not in ['white','black']:
            return EndMessage('*',reason,text,confidence,'winner color unknown; edit result in library')
        won=bool(re.search(r'\byou\s+(won|win)\b',normalized))
        white_wins=(player_color=='white')==won
        return EndMessage('1-0' if white_wins else '0-1',reason,text,confidence,'You Won/Lost mapped using configured player color')
    # Abandonment without a named winner still proves that play ended.
    if 'abandoned' in normalized:return EndMessage('*',reason,text,confidence,'winner color unknown; edit result in library')
    return None


class LocalTextReader:
    """PP-OCRv4 DB/CTC models; bounded CPU inference using the existing ONNX runtime.

    Only horizontal text is needed here. DB components are expanded as rectangles,
    avoiding a dependency on geometry libraries or a separately installed OCR app.
    """
    def __init__(self):
        import onnxruntime as ort
        root=Path(__file__).parent/'assets/models'
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        detector=verify_bundled_model(root/'result-text-det.onnx',root)
        recognizer=verify_bundled_model(root/'result-text-rec.onnx',root)
        self.det=ort.InferenceSession(str(detector),options,providers=['CPUExecutionProvider'])
        self.rec=ort.InferenceSession(str(recognizer),options,providers=['CPUExecutionProvider'])
        self.characters=['blank']+self.rec.get_modelmeta().custom_metadata_map['character'].splitlines()+[' ']

    def read(self,image):
        h,w=validate_bgr_image(image);scale=min(1.5,736/max(h,w))
        rw=max(32,round(w*scale/32)*32);rh=max(32,round(h*scale/32)*32)
        resized=cv2.resize(image,(rw,rh))
        data=(resized.astype(np.float32)/127.5-1).transpose(2,0,1)[None]
        probability=self.det.run(None,{'x':data})[0][0,0]
        mask=cv2.dilate((probability>.30).astype(np.uint8),np.ones((2,2),np.uint8))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        boxes=[]
        for contour in contours:
            x,y,bw,bh=cv2.boundingRect(contour)
            if bh<3 or bw<5 or bw/bh<1.2 or cv2.mean(probability[y:y+bh,x:x+bw])[0]<.5:continue
            pad=max(2,int(bh*.65))
            x0=max(0,int((x-pad)*w/rw));y0=max(0,int((y-pad)*h/rh))
            x1=min(w,int((x+bw+pad)*w/rw));y1=min(h,int((y+bh+pad)*h/rh))
            boxes.append((y0,x0,y1,x1))
        lines=[]
        for y0,x0,y1,x1 in sorted(boxes)[:40]:
            crop=image[y0:y1,x0:x1];height,width=crop.shape[:2]
            target_w=min(1024,max(16,int(48*width/height)))
            tile=cv2.resize(crop,(target_w,48)).astype(np.float32)/127.5-1
            pred=self.rec.run(None,{'x':tile.transpose(2,0,1)[None]})[0][0]
            ids=pred.argmax(axis=1);scores=pred.max(axis=1)
            keep=(ids!=0)&np.r_[True,ids[1:]!=ids[:-1]]
            if keep.any():
                text=''.join(self.characters[i] for i in ids[keep]);score=float(scores[keep].mean())
                if score>=.65:lines.append((text,score,(x0,y0,x1,y1)))
        return lines


class EndMessageDetector:
    def __init__(self,reader=None,clock=time.monotonic):
        self.reader=reader;self.clock=clock;self.last_scan=-100.;self.pending=None;self.pending_since=None
        self.last_lines=[];self._pixels=None

    def scan(self,image,player_color=None,board_rect=None,names=None):
        now=self.clock()
        if now-self.last_scan<1:return None
        self.last_scan=now
        if self.reader is None:self.reader=LocalTextReader()
        if self._pixels is None or not np.array_equal(self._pixels,image):
            self.last_lines=self.reader.read(image);self._pixels=image.copy()
        relevant=self.last_lines
        if board_rect:
            x,y,w,h=board_rect
            relevant=[line for line in relevant if len(line)<3 or (x-w*.15<=(line[2][0]+line[2][2])/2<=x+w*1.45 and y-h*.05<=(line[2][1]+line[2][3])/2<=y+h*1.05)]
        message=parse_end_message(relevant,player_color,names)
        key=(message.result,message.reason,message.color_basis) if message else None
        if key is None:self.pending=None;self.pending_since=None;return None
        if key!=self.pending:
            self.pending=key;self.pending_since=now;return None
        if now-self.pending_since>=.9:return message
        return None

    def reset(self):
        self.pending=None;self.pending_since=None


def clock_seconds(text):
    compact=re.sub(r'\s+','',text)
    match=re.fullmatch(r'(\d{1,2}):([0-5]\d)(?::([0-5]\d))?(?:[.,](\d{1,2}))?',compact)
    if not match:return None
    first,second,third,fraction=match.groups()
    seconds=int(first)*60+int(second) if third is None else int(first)*3600+int(second)*60+int(third)
    if fraction:seconds+=int(fraction)/(10**len(fraction))
    return seconds


def extract_context(lines,board_rect,orientation):
    """Associate clocks and adjacent names spatially, never using names to find moves."""
    if board_rect is None or orientation not in ['white','black']:return {'clocks':{},'names':{}}
    bx,by,bw,bh=board_rect;mid=by+bh/2
    clock_lines={};candidates=[]
    for line in lines:
        if len(line)<3:continue
        text,score,rect=line
        if score<.85:continue
        x0,y0,x1,y1=rect;x=(x0+x1)/2;y=(y0+y1)/2
        # Context must be outside the 64 squares and near the selected board.
        if bx<x<bx+bw and by<y<by+bh:continue
        if not bx-bw*.65<x<bx+bw*1.65 or not by-bh*.40<y<by+bh*1.40:continue
        color=orientation if y>=mid else ('black' if orientation=='white' else 'white')
        seconds=clock_seconds(text)
        if seconds is not None:
            distance=abs(y-(by+bh if y>=mid else by))
            if color not in clock_lines or distance<clock_lines[color][3]:clock_lines[color]=(seconds,rect,score,distance)
        else:candidates.append((color,text,rect,score))
    names={}
    excluded={'white','black','game review','review','rematch','new game','you won','you lost','game abandoned','game aborted','analysis','resign','draw','share','settings','play','play bots','computer','stockfish','unknown','hidden','redacted','censored'}
    for color,clock in clock_lines.items():
        _,rect,_,_=clock;cx=(rect[0]+rect[2])/2;cy=(rect[1]+rect[3])/2
        masked=False
        for side,text,r,score in candidates:
            compact=re.sub(r'[\W_]+','',text.lower())
            if side==color and abs((r[1]+r[3])/2-cy)<bh*.14 and any(marker in compact for marker in ['nameblurred','namehidden','usernamehidden','namecensored','redacted','definitelynot']):masked=True
        if masked:continue
        nearby=[]
        for side,text,r,score in candidates:
            if side!=color:continue
            clean=re.sub(r'^(GM|IM|FM|NM|CM|WGM|WIM)\s+','',text.strip().rstrip(' :;|•'))
            clean=re.sub(r'\s*(?:\(\d{2,4}\)|\s\d{2,4})\s*$','',clean)
            if clean.lower() in excluded or not re.fullmatch(r'[\w .-]{2,40}',clean) or not any(c.isalpha() for c in clean):continue
            if any(word in clean.lower() for word in ['won','aborted','abandoned','minutes','new game','time control','name blurred','name hidden','username hidden','name censored','definitely not ']):continue
            x=(r[0]+r[2])/2;y=(r[1]+r[3])/2
            if bx<=cx<=bx+bw and not bx-bw*.1<=x<=bx+bw*1.1:continue
            if abs(y-cy)<bh*.14 and abs(x-cx)<bw*1.05:
                nearby.append((abs(y-cy)*4+abs(x-cx),clean))
        if nearby:names[color]=min(nearby)[1]
    return {'clocks':{c:v[0] for c,v in clock_lines.items()},'names':names}


class ContextStabilizer:
    def __init__(self):self.names={}
    def observe(self,context):
        stable={};current=dict(self.names)
        for color,name in context.get('names',{}).items():
            old,count=current.get(color,('',0));count=count+1 if old==name else 1
            current[color]=(name,count)
            if count>=3:stable[color]=name
        self.names=current
        return {**context,'names':stable}
