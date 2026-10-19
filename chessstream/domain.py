from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import logging
import math
import os
import tempfile
import chess
import numpy as np

# The same order is used for templates, observations and optional ONNX output.
LABELS = ".PNBRQKpnbrqk"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@dataclass
class Region:
    left: int
    top: int
    width: int
    height: int
    window: int = 0
    # Window offsets are physical pixels relative to the current client origin.
    offset_x: int = 0
    offset_y: int = 0
    tracking_window: int = 0

    def valid(self) -> bool:
        return self.width >= 80 and self.height >= 80


@dataclass
class Settings:
    interval: float = 1.0
    adaptive: bool = True
    adaptive_fps: int = 6
    deduplicate: bool = False
    screenshot_mode: str = "positions"
    save_screenshots: bool = False
    confirm_on_reply: bool = True
    unresolved_fen_seconds: float = 15.0
    new_game_change_seconds: float = 5.0
    new_game_min_changed_squares: int = 4
    detect_results: bool = True
    read_context: bool = True
    auto_context: bool = True
    context_padding_percent: int = 18
    result_player_color: str = "initial-bottom"
    review_seconds: int = 120
    orientation: str = "auto"
    detect_board: bool = True
    max_plies: int = 4
    search_nodes: int = 60000
    search_ms: int = 350
    min_confidence: float = 0.70
    retention_days: int = 0
    export_dir: str = ""
    auto_export: bool = True
    onnx_model: str = ""
    recognition_mode: str = "neural"
    initial_fen: str = ""
    start_hotkey: str = "F8"
    stop_hotkey: str = "F9"
    region_hotkey: str = "Ctrl+Shift+R"
    region: dict | None = None

    @classmethod
    def load(cls, path: Path) -> Settings:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logging.warning("Saved settings are not an object; using defaults")
                return cls()
        except (OSError,UnicodeError,json.JSONDecodeError):
            logging.warning("Could not read saved settings; using defaults",exc_info=True)
            return cls()

        # A single hand-edited or truncated value should not discard every other
        # user preference or prevent the desktop from launching.
        result=cls()
        for key in cls.__dataclass_fields__:
            if key in data:setattr(result,key,data[key])

        def bounded(key,cast,low,high):
            try:
                value=cast(getattr(result,key))
                if isinstance(value,float) and not math.isfinite(value):raise ValueError
            except (ValueError,TypeError,OverflowError):
                value=getattr(cls(),key)
                logging.warning("Invalid saved setting %s; using its safe default",key)
            setattr(result,key,max(low,min(high,value)))

        bounded("interval",float,.1,60)
        bounded("adaptive_fps",int,2,15)
        bounded("max_plies",int,1,6)
        bounded("unresolved_fen_seconds",float,0,600)
        bounded("new_game_change_seconds",float,1,120)
        bounded("new_game_min_changed_squares",int,1,32)
        bounded("context_padding_percent",int,0,50)
        bounded("review_seconds",int,0,3600)
        bounded("search_ms",int,50,5000)
        bounded("search_nodes",int,1000,1000000)
        bounded("min_confidence",float,.5,.99)
        bounded("retention_days",int,0,36500)
        for key,allowed,fallback in (
            ("result_player_color",["initial-bottom","white","black","unknown"],"unknown"),
            ("screenshot_mode",["positions","interval"],"positions"),
            ("orientation",["auto","white","black"],"auto"),
            ("recognition_mode",["neural","calibrated"],"neural")):
            if getattr(result,key) not in allowed:
                setattr(result,key,fallback);logging.warning("Invalid saved setting %s; using its safe default",key)
        for key in ("adaptive","deduplicate","save_screenshots","confirm_on_reply","detect_results","read_context","auto_context",
                    "detect_board","auto_export"):
            if not isinstance(getattr(result,key),bool):
                setattr(result,key,getattr(cls(),key));logging.warning("Invalid saved setting %s; using its safe default",key)
        for key in ("export_dir","onnx_model","initial_fen","start_hotkey","stop_hotkey","region_hotkey"):
            if not isinstance(getattr(result,key),str):
                setattr(result,key,getattr(cls(),key));logging.warning("Invalid saved setting %s; using its safe default",key)
        if result.initial_fen:
            try:
                if not chess.Board(result.initial_fen).is_valid():
                    result.initial_fen="";logging.warning("Invalid saved initial FEN; ignoring it")
            except ValueError:
                result.initial_fen="";logging.warning("Invalid saved initial FEN; ignoring it")
        if result.region is not None:
            try:
                if not isinstance(result.region,dict):raise ValueError
                required=("left","top","width","height")
                if any(key not in result.region for key in required):raise ValueError
                fields=Region.__dataclass_fields__
                values={key:int(value) for key,value in result.region.items() if key in fields}
                region=Region(**values)
                result.region=asdict(region) if region.valid() else None
            except (TypeError,ValueError,OverflowError):
                result.region=None;logging.warning("Invalid saved capture region; asking the user to select it again")
        return result

    def save(self, path: Path) -> None:
        atomic_text(path, json.dumps(asdict(self), indent=2))


def board_labels(board: chess.Board) -> np.ndarray:
    return np.array([LABELS.index(p.symbol()) if (p := board.piece_at(s)) else 0
                     for s in chess.SQUARES], dtype=np.int8)


@dataclass
class Observation:
    # Rows follow chess square indexing (a1=0), not image row indexing.
    probabilities: np.ndarray
    timestamp: str = field(default_factory=utcnow)
    orientation: str = "white"
    quality: float = 1.0

    @property
    def labels(self) -> np.ndarray:
        return self.probabilities.argmax(axis=1).astype(np.int8)

    @property
    def confidence(self) -> float:
        return float(np.mean(self.probabilities.max(axis=1))) * self.quality

    @property
    def weakest_confidence(self) -> float:
        return float(self.probabilities.max(axis=1).min()) * self.quality

    def uncertain_squares(self, threshold: float = .80) -> list[str]:
        return [chess.square_name(s) for s in np.flatnonzero(
            self.probabilities.max(axis=1) * self.quality < threshold)]

    def flipped(self) -> Observation:
        return Observation(self.probabilities[::-1].copy(), self.timestamp,
                           "black" if self.orientation == "white" else "white", self.quality)

    def with_unknown(self, squares) -> Observation:
        """Retain raw evidence separately while marking disputed squares unknown."""
        probabilities=self.probabilities.copy()
        probabilities[list(squares)]=1/len(LABELS)
        return Observation(probabilities,self.timestamp,self.orientation,self.quality)

    def placement(self) -> str:
        b = chess.Board(None)
        for s, label in enumerate(self.labels):
            if label:
                b.set_piece_at(s, chess.Piece.from_symbol(LABELS[label]))
        return b.board_fen()

    def matches(self, board: chess.Board, threshold: float = .70) -> bool:
        certain = self.probabilities.max(axis=1) >= threshold
        # Too much obstruction is never evidence of a move.
        return bool(certain.sum() >= 60 and np.all(self.labels[certain] == board_labels(board)[certain]))

    @classmethod
    def from_board(cls, board: chess.Board, confidence: float = .999) -> Observation:
        p = np.full((64, 13), (1 - confidence) / 12, dtype=np.float32)
        p[np.arange(64), board_labels(board)] = confidence
        return cls(p)
