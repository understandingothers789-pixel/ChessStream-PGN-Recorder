from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
import json
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
            result = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            result.interval = max(0.1, min(60, float(result.interval)))
            result.adaptive_fps = max(2, min(15, int(result.adaptive_fps)))
            result.max_plies = max(1, min(6, int(result.max_plies)))
            result.search_ms = max(50, min(5000, int(result.search_ms)))
            result.search_nodes = max(1000, min(1000000, int(result.search_nodes)))
            return result
        except (ValueError, TypeError):
            return cls()

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

    def flipped(self) -> Observation:
        return Observation(self.probabilities[::-1].copy(), self.timestamp,
                           "black" if self.orientation == "white" else "white", self.quality)

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
