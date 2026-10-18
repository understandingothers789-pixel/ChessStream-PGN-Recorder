"""Local template model, board localization and optional ONNX tile inference.

Template scores are similarities, not statistically calibrated probabilities.
Legality and repeated stable evidence are required by the recorder as well.
"""
from __future__ import annotations

from pathlib import Path
import math
import cv2
import chess
import numpy as np
from .domain import LABELS, Observation

ASSETS = Path(__file__).parent / "assets"


def image_to_squares(image: np.ndarray) -> list[np.ndarray]:
    h, w = image.shape[:2]
    if min(h, w) < 80:
        raise ValueError("Board must be at least 80 pixels across")
    return [image[round(r*h/8):round((r+1)*h/8), round(c*w/8):round((c+1)*w/8)]
            for r in range(8) for c in range(8)]


def background(tile: np.ndarray) -> np.ndarray:
    n = max(2, round(min(tile.shape[:2]) * .08))
    points = [tile[:n, :n], tile[:n, -n:], tile[-n:, :n], tile[-n:, -n:]]
    # Each corner gets one vote; coordinates or a cursor rarely cover all four.
    return np.median([np.median(x.reshape(-1, 3), axis=0) for x in points], axis=0)


def checker_score(image: np.ndarray) -> float:
    if min(image.shape[:2]) < 80:
        return 0.0
    cells = cv2.resize(image, (128,128), interpolation=cv2.INTER_AREA).reshape(8,16,8,16,3).transpose(0,2,1,3,4).reshape(64,16,16,3)
    corners = np.stack([cells[:,:2,:2],cells[:,:2,-2:],cells[:,-2:,:2],cells[:,-2:,-2:]],axis=1)
    colors = np.median(np.median(corners.reshape(64,4,4,3),axis=2),axis=1)
    parity = np.array([(r+c) % 2 for r in range(8) for c in range(8)])
    a, b = np.median(colors[parity == 0], axis=0), np.median(colors[parity == 1], axis=0)
    contrast = np.linalg.norm(a - b)
    errors = np.linalg.norm(colors - np.where(parity[:, None] == 0, a, b), axis=1)
    # Ignore several highlighted squares, but not a photograph with two colors.
    consistency = float(np.mean(np.sort(errors)[:48]) + .35*np.mean(errors))
    return float(np.clip((contrast-12) / 60, 0, 1) * math.exp(-consistency/18))


class BoardDetector:
    """Find axis-aligned 2D stream boards. No camera/perspective assumptions."""
    def detect(self, image: np.ndarray) -> tuple[tuple[int, int, int, int] | None, float]:
        h, w = image.shape[:2]
        factor = min(1.0, 800 / max(h, w))
        small = cv2.resize(image, None, fx=factor, fy=factor) if factor < 1 else image
        sh, sw = small.shape[:2]
        candidates: set[tuple[int, int, int, int]] = set()
        if abs(h-w) / max(h, w) < .07:
            candidates.add((0, 0, sw, sh))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 45, 140)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        tiles = []
        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            if min(cw, ch) > 12 and abs(cw-ch) / max(cw, ch) < .12:
                if min(cw, ch) >= 100:
                    candidates.add((x, y, cw, ch))
                if 14 < cw < min(sh, sw)/5 and cv2.contourArea(contour) > cw*ch*.60:
                    tiles.append((x, y, (cw+ch)/2))
        # A checkerboard often has disconnected square outlines, not an outer border.
        if tiles:
            sizes = [t[2] for t in tiles]
            bins = sorted(set(round(v/2)*2 for v in sizes), key=lambda n: -sum(abs(v-n)<3 for v in sizes))[:4]
            for side in sorted(set(v+delta for v in bins for delta in [-2,-1.5,-1,-.5,0])):
                cells = [(x, y) for x, y, sz in tiles if abs(sz-side-1) < 3]
                for x, y in cells[:50]:
                    for row in range(8):
                        for col in range(8):
                            bx, by, bs = round(x-col*side), round(y-row*side), round(side*8)
                            if bx >= -2 and by >= -2 and bx+bs <= sw+2 and by+bs <= sh+2:
                                candidates.add((max(0, bx), max(0, by), min(bs, sw-max(0,bx)), min(bs,sh-max(0,by))))
        # Canny rectangles include both boundary pixels; their inclusive width is
        # often one pixel larger than the checker spacing. Rank all candidate
        # grids using vectorized corner sampling before the more robust check.
        def rank_candidates(source, rectangles):
            if not rectangles:return []
            if len(rectangles)>1024:
                best=[]
                for index in range(0,len(rectangles),1024):best.extend(rank_candidates(source,rectangles[index:index+1024]))
                return rank_candidates(source,best)
            rects=np.asarray(list(rectangles),dtype=np.int32)
            parity=np.array([(r+c)%2 for r in range(8) for c in range(8)])
            cols=np.tile(np.arange(8),8);rows=np.repeat(np.arange(8),8)
            ox=np.array([.06,.94,.06,.94]);oy=np.array([.06,.06,.94,.94])
            xs=rects[:,0,None,None]+(cols[None,:,None]+ox[None,None,:])*rects[:,2,None,None]/8
            ys=rects[:,1,None,None]+(rows[None,:,None]+oy[None,None,:])*rects[:,3,None,None]/8
            pixels=source[np.clip(ys.astype(int),0,source.shape[0]-1),np.clip(xs.astype(int),0,source.shape[1]-1)].astype(float)
            colors=np.median(pixels,axis=2)
            a=np.median(colors[:,parity==0],axis=1);b=np.median(colors[:,parity==1],axis=1)
            expected=np.where(parity[None,:,None]==0,a[:,None],b[:,None])
            distances=np.linalg.norm(colors-expected,axis=2)
            errors=np.sort(distances,axis=1)[:,:48].mean(axis=1)+.35*distances.mean(axis=1)
            contrast=np.linalg.norm(a-b,axis=1)
            scores=np.clip((contrast-12)/60,0,1)*np.exp(-errors/18)
            order=np.argsort(-scores,kind='stable')[:40]
            return [tuple(int(v) for v in rects[i]) for i in order]
        # Bound expensive scoring when menus/text create small square candidates.
        best, best_score = None, .0
        for rect in rank_candidates(small,sorted(candidates)):
            x, y, cw, ch = rect
            if min(cw, ch) < 100:
                continue
            score = checker_score(small[y:y+ch, x:x+cw])
            if score > best_score:
                best, best_score = rect, score
        if best is None or best_score < .38:
            return None, best_score
        x, y, cw, ch = best
        x,y,cw,ch=round(x/factor),round(y/factor),round(cw/factor),round(ch/factor)
        # Final few-pixel refinement operates on original pixels, not the reduced grid.
        side=round((cw+ch)/2)
        refined={(x+dx,y+dy,side+ds,side+ds) for dx in range(-3,4) for dy in range(-3,4) for ds in range(-4,5)
                 if x+dx>=0 and y+dy>=0 and x+dx+side+ds<=w and y+dy+side+ds<=h}
        final=(x,y,cw,ch)
        for rect in rank_candidates(image,sorted(refined)):
            rx,ry,rw,rh=rect
            score=checker_score(image[ry:ry+rh,rx:rx+rw])
            if score>best_score:final,best_score=rect,score
        return final,best_score


class TemplateRecognizer:
    def __init__(self, custom_bank: Path | None = None):
        banks = [ASSETS / "templates.npz"]
        if custom_bank and custom_bank.exists():
            banks.append(custom_bank)
        rgba, labels = [], []
        for bank in banks:
            if bank.exists():
                with np.load(bank, allow_pickle=False) as data:
                    rgba.extend(data["rgba"])
                    labels.extend(data["labels"])
        if not rgba:
            raise RuntimeError("Piece template bank is missing. Run scripts/fetch_assets.py.")
        self.rgba = np.asarray(rgba, dtype=np.float32) / 255
        self.labels = np.asarray(labels, dtype=np.int8)
        self.alpha = self.rgba[:, :, :, 3]
        self.gray = np.sum(self.rgba[:, :, :, :3] * np.array([.299, .587, .114]), axis=3)
        self.weight = np.ones((32, 32), dtype=np.float32)
        self.weight[:2] = self.weight[-2:] = .08
        self.weight[:, :2] = self.weight[:, -2:] = .08

    def classify(self, tiles: list[np.ndarray]) -> np.ndarray:
        results = []
        for tile in tiles:
            bg = float(background(tile) @ np.array([.114, .587, .299]) / 255)
            gray = cv2.resize(cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY), (32, 32), interpolation=cv2.INTER_AREA) / 255
            target = gray - bg
            predicted = self.alpha * (self.gray - bg)
            # Small shifts tolerate video resampling and imperfect region boundaries.
            errors = np.full(len(self.labels), np.inf)
            for dy, dx in [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)]:
                shifted = np.roll(target, (dy, dx), axis=(0, 1))
                mse = np.mean((predicted-shifted)**2*self.weight, axis=(1, 2))
                errors = np.minimum(errors, mse)
            class_errors = np.array([np.min(errors[self.labels == k]) if np.any(self.labels == k) else 1 for k in range(13)])
            class_errors[0] = float(np.mean(target**2*self.weight))
            # Templates within a class compete; multiple copies do not inflate scores.
            logits = -(class_errors - class_errors.min()) / .0025
            p = np.exp(np.clip(logits, -60, 0))
            p /= p.sum()
            # Severe mismatch reduces trust even when the nearest piece wins by far.
            fit = min(.995, math.exp(-max(0, float(class_errors.min())-.006)/.025))
            p = p*fit + (1-fit)/13
            results.append(p)
        return np.asarray(results, dtype=np.float32)

    def recognize(self, image: np.ndarray, orientation: str = "white") -> Observation:
        image_order = self.classify(image_to_squares(image))
        # Image indices a8..h1 -> chess indices a1..h8.
        canonical = image_order.reshape(8, 8, 13)[::-1].reshape(64, 13).copy()
        obs = Observation(canonical, orientation="white", quality=min(1, checker_score(image)/.5))
        return obs.flipped() if orientation == "black" else obs

    @staticmethod
    def calibrate(image: np.ndarray, path: Path, orientation: str = "white") -> None:
        """Explicitly user-confirmed initial position; never guesses labels on live boards."""
        from .domain import atomic_text
        samples, labels = [], []
        initial = chess.Board()
        for index, tile in enumerate(image_to_squares(image)):
            row, col = divmod(index, 8)
            sq = chess.square(col, 7-row)
            if orientation == "black":
                sq = 63-sq
            piece = initial.piece_at(sq)
            if not piece:
                continue
            rgb = cv2.cvtColor(cv2.resize(tile, (32, 32)), cv2.COLOR_BGR2RGB)
            bg = background(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))[::-1]
            diff = np.linalg.norm(rgb.astype(float)-bg, axis=2)
            alpha = np.clip((diff-8)/12, 0, 1)
            rgba = np.dstack([rgb, np.uint8(alpha*255)]).astype(np.uint8)
            samples.append(rgba)
            labels.append(LABELS.index(piece.symbol()))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".tmp").open("wb") as f:
            np.savez_compressed(f, rgba=np.asarray(samples), labels=np.asarray(labels))
        path.with_suffix(".tmp").replace(path)


class OnnxRecognizer:
    """User-supplied model contract: float32 RGB [N,3,H,W], 13 logits (LABELS order)."""
    def __init__(self, path: str):
        try:
            import onnxruntime as ort
        except ImportError as e:
            raise RuntimeError("Install the 'onnx' extra to use an ONNX model") from e
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(path, sess_options=options, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.name = inp.name
        self.h = inp.shape[2] if isinstance(inp.shape[2], int) else 64
        self.w = inp.shape[3] if isinstance(inp.shape[3], int) else 64
        self.batch = inp.shape[0]

    def recognize(self, image: np.ndarray, orientation: str = "white") -> Observation:
        tiles = np.asarray([cv2.resize(cv2.cvtColor(t, cv2.COLOR_BGR2RGB), (self.w,self.h))
                            for t in image_to_squares(image)], dtype=np.float32)/255
        values = tiles.transpose(0, 3, 1, 2)
        if self.batch == 1:
            logits = np.concatenate([self.session.run(None, {self.name: v[None]})[0] for v in values])
        else:
            logits = self.session.run(None, {self.name: values})[0]
        if logits.shape != (64, 13):
            raise ValueError("ONNX model must return [64,13] logits or [1,13] for batch-one models")
        p = np.exp(logits-logits.max(axis=1, keepdims=True))
        p /= p.sum(axis=1, keepdims=True)
        obs = Observation(p.reshape(8,8,13)[::-1].reshape(64,13).copy())
        return obs.flipped() if orientation == "black" else obs


def choose_orientation(obs: Observation, previous: chess.Board | None = None) -> Observation:
    if previous:
        expected = np.array([LABELS.index(p.symbol()) if (p:=previous.piece_at(s)) else 0 for s in chess.SQUARES])
        def score(o):
            return float(np.log(np.maximum(o.probabilities[np.arange(64), expected], 1e-6)).sum())
        return obs if score(obs) >= score(obs.flipped()) else obs.flipped()
    # Starting ranks provide strong orientation evidence; midgames may remain uncertain.
    labels = obs.labels
    rank_bias = sum((3.5-chess.square_rank(s)) * (1 if 0 < labels[s] < 7 else -1)
                    for s in chess.SQUARES if labels[s])
    return obs if rank_bias >= 0 else obs.flipped()
