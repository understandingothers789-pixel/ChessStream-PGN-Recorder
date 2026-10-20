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


def _result_line_is_an_announcement(value):
    """Reject ordinary prose, navigation and win/draw/loss lists as results.

    This is purposely conservative: a false positive permanently terminates
    the live PGN, while a missed caption merely leaves its result unknown.
    """
    text=re.sub(r'\\s+',' ',str(value).strip().replace('–','-').replace('−','-'))
    if not text:return False
    if re.search(r'(?i)\\b(?:wins?\\s*[/|]\\s*draw|draw\\s*[/|]\\s*loss|win\\s*[/|]\\s*loss|database|variation|percentage|statistics)\\b',text):
        return False
    if re.fullmatch(r'(?i)(?:1\\s*-\\s*0|0\\s*-\\s*1|1\\s*/\\s*2\\s*-\\s*1\\s*/\\s*2|½\\s*-\\s*½|draw|drawn|stalemate|checkmate|you\\s+(?:won|lost)|white\\s+won|black\\s+won|game\\s+(?:over|ended|drawn|aborted|abandoned))\\s*[!.]?',text):
        return True
    if len(text.split())>9:return False
    return bool(re.fullmatch(
        r'(?i)(?:(?:you|white|black|[A-Za-z0-9_]{3,24})\\s+)?'
        r'(?:won|lost|wins|resigned|abandoned|timeout|timed out|checkmate|stalemate|drawn|draw)'
        r'(?:\\s+(?:by|on|via|due to)\\s+(?:checkmate|resignation|timeout|time|repetition|agreement|stalemate|insufficient material))?'
        r'[!.]?',text))


def parse_end_message(lines, player_color=None, names=None):
    """Only strong end-message vocabulary can terminate a game, never arbitrary digits."""
    strong=[(re.sub(r'\b(You|White|Black|Game)(Won|Lost|Aborted|Abandoned)\b',r'\1 \2',str(text).strip().replace('–','-').replace('−','-'),flags=re.I),score) for text,score,*_ in lines if score >= .80]
    strong=[(text,score) for text,score in strong if _result_line_is_an_announcement(text)]
    good=[text for text,score in strong]
    text=" | ".join(good)
    normalized=re.sub(r"\s+"," ",text.lower().replace('½','1/2').replace('–','-').replace('−','-'))
    if not normalized:return None
    aborted=bool(re.search(r'\b(game\s+)?abort(?:ed)?\b',normalized))
    context=bool(re.search(r'\b(won|wins|lost|draw|drawn|stalemate|checkmate|abandoned|resigned|resignation|timeout|time out|game over|game ended|aborted)\b',normalized))
    if not context and not re.fullmatch(r'(?:1-0|0-1|1/2-1/2)',normalized.replace(' ','')):return None
    reason=next((word for word in ['aborted','abandoned','checkmate','stalemate','resignation','timeout'] if word in normalized),'game ended')
    if re.search(r'\bresign(?:ed|ation)\b',normalized):reason='resignation'
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
    if 'abandoned' in normalized or reason=='resignation':return EndMessage('*',reason,text,confidence,'winner color unknown; edit result in library')
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

    def scan(self,image,player_color=None,board_rect=None,names=None,orientation=None):
        now=self.clock()
        if now-self.last_scan<1:return None
        self.last_scan=now
        if self.reader is None:self.reader=LocalTextReader()
        if self._pixels is None or not np.array_equal(self._pixels,image):
            self.last_lines=self.reader.read(image);self._pixels=image.copy()
            message=parse_end_message(self.last_lines,player_color,names)
            # Full-window downsampling can erase a small resignation subtitle.
            # Retry the actual board at native scale; map coordinates back so
            # context extraction keeps its ordinary spatial restrictions.
            if board_rect and (message is None or message.reason=='game ended'):
                x,y,w,h=map(int,board_rect)
                x0=max(0,x);y0=max(0,y);x1=min(image.shape[1],x+w);y1=min(image.shape[0],y+h)
                if x1-x0>=64 and y1-y0>=64:
                    crop=image[y0:y1,x0:x1]
                    for line in self.reader.read(crop):
                        if len(line)<3:self.last_lines.append(line);continue
                        text,score,(a,b,c,d)=line
                        self.last_lines.append((text,score,(a+x0,b+y0,c+x0,d+y0)))
            # Player names sit on narrow strips directly above or below the
            # board, often at the opposite end of the clock. Read those strips
            # at native resolution when whole-frame OCR missed a player. The
            # result-message reader's board-only retry does not cover them.
            if board_rect and orientation in ('white','black'):
                found=extract_context(self.last_lines,board_rect,orientation).get('names',{})
                bands=player_info_bands(image.shape,board_rect)
                for side,color in (('top','black' if orientation=='white' else 'white'),
                                   ('bottom',orientation)):
                    if color in found:continue
                    x0,y0,x1,y1=bands[side]
                    if x1-x0<80 or y1-y0<18:continue
                    for line in self.reader.read(image[y0:y1,x0:x1]):
                        if len(line)<3:continue
                        text,score,(a,b,c,d)=line
                        absolute=(a+x0,b+y0,c+x0,d+y0)
                        # Avoid duplicating a line from the whole-frame pass.
                        if any(old[0]==text and len(old)>2
                               and max(abs(old[2][i]-absolute[i]) for i in range(4))<12
                               for old in self.last_lines):
                            continue
                        self.last_lines.append((text,score,absolute))
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

    def invalidate_layout(self):
        self.reset();self._pixels=None;self.last_lines=[];self.last_scan=-100.


def player_info_bands(image_shape, board_rect):
    """Narrow native-resolution OCR regions above/below the detected board.

    Avoid a whole-video OCR resize, which shrinks clock-adjacent usernames.
    Each rectangle is (x0, y0, x1, y1) in the context image coordinates.
    No pixels inside the playable board are required for the name search.
    """
    height,width=image_shape[:2]
    bx,by,bw,bh=map(int,board_rect)
    x0=max(0,bx-round(bw*.12))
    x1=min(width,bx+bw+round(bw*.12))
    margin=max(24,round(bh*.22))
    overlap=round(bh*.025)
    top=(x0,max(0,by-margin),x1,min(height,by+overlap))
    bottom=(x0,max(0,by+bh-overlap),x1,min(height,by+bh+margin))
    return {"top":top,"bottom":bottom}


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
    names={};name_confidence={}
    excluded={'white','black','game review','review','rematch','new game','you won','you lost','game abandoned','game aborted','analysis','resign','draw','share','settings','play','play bots','computer','stockfish','unknown','hidden','redacted','censored','rapid','blitz','bullet','classical','chess','you tube','youtube'}
    for color in ('white','black'):
        clock=clock_lines.get(color)
        if clock:
            _,rect,_,_=clock;cx=(rect[0]+rect[2])/2;cy=(rect[1]+rect[3])/2
        else:
            cx=bx+bw*.9;cy=by+bh*1.06 if color==orientation else by-bh*.06
        masked=False
        for side,text,r,score in candidates:
            compact=re.sub(r'[\W_]+','',text.lower())
            if side==color and abs((r[1]+r[3])/2-cy)<bh*.14 and any(marker in compact for marker in ['nameblurred','namehidden','usernamehidden','namecensored','redacted','definitelynot']):masked=True
        if masked:continue
        nearby=[]
        for side,text,r,score in candidates:
            if side!=color:continue
            if not clock and (score<.9 or not bx-bw*.1<=(r[0]+r[2])/2<=bx+bw*1.1):continue
            clean=re.sub(r'^(GM|IM|FM|NM|CM|WGM|WIM)\s+','',text.strip().rstrip(' :;|•'))
            clean=re.sub(r'\s*(?:\(\d{2,4}\)|\s\d{2,4})\s*$','',clean)
            # Overlay controls, URLs, and app labels are *not* player IDs.
            # False names here corrupt lifecycle identity and may split a real
            # game despite a perfectly legal board continuation.
            folded=re.sub(r'\s+',' ',clean.casefold()).strip()
            if (folded in {'flip','copy fen','copy pgn','youtube chess recording',
                           'download','share','next','previous','play','pause',
                           'game in progress','chessstream','copy','settings'}
                    or re.search(r'(?i)(?:https?://|www\.|youtube\.com|\.pgn$|\.exe$)',folded)
                    or folded.startswith(('copy fen ', 'youtube chess recording ', 'flip board '))):
                continue
            # Reject overlay metadata even when OCR finds a nearby clock.
            if (re.fullmatch(r'(?i)v(?:ersion)?\s*\d+(?:\.\d+){1,4}', clean)
                    or re.search(r'(?i)\b(chess\s+speedrun|speedrun|live\s+stream|streaming|subscribe|playlist|tournament\s+coverage)\b', clean)):
                continue

            if not clock and re.search(r'\b(game|analyzing|analysis|review|speedrun|subscribe|watch|playlist|minutes|min)\b',clean,re.I):continue
            # Stream headlines, browser tabs, visible PGN move lists and
            # multiword prompts regularly appear near a captured board. A
            # high OCR score cannot turn that surrounding prose into an ID.
            if (len(clean.split())>3
                    or re.search(r'\b(?:codex|python|prompt|candidate|slowkaru|download[s]?|file explorer|open alongside|optimi[sz]e|work with)\b',clean,re.I)
                    or re.search(r'\b\d+\s*\.\s*(?:\.\s*\.)?\s*[a-hKQRBNOP][\w+#=-]*',clean,re.I)
                    or (not clock and len(clean)<3)):
                continue
            if clean.lower() in excluded or not re.fullmatch(r'[\w .-]{2,40}',clean) or not any(c.isalpha() for c in clean):continue
            if any(word in clean.lower() for word in ['won','aborted','abandoned','minutes','new game','time control','name blurred','name hidden','username hidden','name censored','definitely not ']):continue
            x=(r[0]+r[2])/2;y=(r[1]+r[3])/2
            if bx<=cx<=bx+bw and not bx-bw*.1<=x<=bx+bw*1.1:continue
            if abs(y-cy)<bh*.14 and abs(x-cx)<bw*1.05:
                nearby.append((abs(y-cy)*4+abs(x-cx),clean,score))
        if nearby:
            _,names[color],name_confidence[color]=min(nearby)
    return {'clocks':{c:v[0] for c,v in clock_lines.items()},'names':names,'name_confidence':name_confidence}


class ContextStabilizer:
    def __init__(self):self.names={}
    def observe(self,context):
        stable={};current=dict(self.names)
        for color in list(current):
            if color not in context.get('names',{}):current.pop(color)
        for color,name in context.get('names',{}).items():
            old,count=current.get(color,('',0));count=count+1 if old==name else 1
            current[color]=(name,count)
            if count>=3:stable[color]=name
        self.names=current
        return {**context,'names':stable,'raw_names':dict(context.get('names',{})),'names_stable':True}

    def reset_candidates(self):self.names={}
