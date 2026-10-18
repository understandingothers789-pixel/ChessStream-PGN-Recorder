"""Regression checks for the production recognizer, not a synthetic-only model test."""
from pathlib import Path
import hashlib
import json
import chess
import cv2
import numpy as np
import pytest
from chessstream.domain import Observation, Settings, board_labels
from chessstream.games import GameManager
from chessstream.storage import Store
from chessstream.vision import ScreenshotRecognizer, BoardDetector, choose_orientation, create_recognizer

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def recognizer():
    return ScreenshotRecognizer()


def test_bundled_model_integrity_and_probability_contract(recognizer):
    assets = Path(__file__).parents[1] / "chessstream/assets"
    metadata = json.loads((assets / "models/chess-tiles-v2.json").read_text())
    assert hashlib.sha256((assets / "models/chess-tiles-v2.onnx").read_bytes()).hexdigest() == metadata["sha256"]
    assert (assets / "licenses/MIT-fenshot.txt").exists()
    obs = recognizer.recognize(cv2.imread(str(FIXTURES / "real/chesscom-ruy-000.png")))
    assert obs.placement() == chess.Board().board_fen()
    np.testing.assert_allclose(obs.probabilities.sum(axis=1), 1, atol=1e-5)
    assert obs.weakest_confidence > .85  # Applying softmax twice breaks this.


def test_old_calibration_does_not_override_new_default(tmp_path):
    bank = tmp_path / "custom-templates.npz"
    bank.write_bytes(b"stale or damaged old templates")
    assert isinstance(create_recognizer(Settings(), bank), ScreenshotRecognizer)


@pytest.mark.parametrize("game", json.loads((FIXTURES / "real/manifest.json").read_text())["games"], ids=lambda g:g["id"])
def test_every_existing_real_frame_without_calibration(game, recognizer):
    for frame in game["frames"]:
        obs = recognizer.recognize(cv2.imread(str(FIXTURES / "real" / frame["file"])), frame["orientation"])
        np.testing.assert_array_equal(obs.labels, board_labels(chess.Board(frame["fen"])), err_msg=frame["file"])


def test_one_uncertain_queen_cannot_be_hidden_in_a_high_average(tmp_path):
    store = Store(tmp_path);manager = GameManager(store, Settings())
    obs = Observation.from_board(chess.Board())
    obs.probabilities[chess.D8] = .01
    obs.probabilities[chess.D8, 8] = .55  # A queen incorrectly called a knight.
    obs.probabilities[chess.D8, 11] = .34
    assert obs.confidence > .97
    manager.process(obs)
    assert manager.rec is None and not store.games()
    assert "d8" in manager.last_message
    manager.process(Observation.from_board(chess.Board()))
    assert manager.rec.initial_fen == chess.STARTING_FEN
    store.close()


def test_missing_white_pieces_do_not_create_a_bogus_midgame(tmp_path):
    store = Store(tmp_path);manager = GameManager(store, Settings())
    obs = Observation.from_board(chess.Board())
    for square in [chess.B1, chess.D1, chess.F1, chess.G1]:
        obs.probabilities[square] = .01
        obs.probabilities[square, 0] = .60
    assert obs.confidence > .96
    manager.process(obs)
    assert manager.rec is None
    assert "uncertain squares" in manager.last_message
    store.close()


THEMES = sum([json.loads((FIXTURES / "themes" / name).read_text())["games"]
              for name in ["manifest.json", "chesscom-ocean-manifest.json"]], [])


@pytest.mark.parametrize("game", THEMES, ids=lambda g:g["id"])
def test_textured_boards_shaded_pieces_and_actual_flips(game, recognizer, tmp_path):
    store = Store(tmp_path);manager = GameManager(store, Settings());ground = chess.Board()
    for frame in game["frames"]:
        if frame["san"]:ground.push_san(frame["san"])
        image = cv2.imread(str(FIXTURES / "themes" / frame["file"]))
        obs = choose_orientation(recognizer.recognize(image), manager.rec.board if manager.rec else None)
        assert obs.orientation == frame["orientation"]
        np.testing.assert_array_equal(obs.labels, board_labels(ground), err_msg=frame["file"])
        manager.process(obs)
    assert manager.rec and manager.rec.verified == [m.uci() for m in ground.move_stack[:-1]]
    manager.choose(0)
    assert manager.rec.verified == [m.uci() for m in ground.move_stack]
    store.close()


@pytest.mark.parametrize("game", THEMES, ids=lambda g:g["id"])
def test_actual_textured_full_page_localization(game, recognizer):
    page = cv2.imread(str(FIXTURES / "themes" / (game["id"] + "-page.png")))
    rect, _ = BoardDetector().detect(page)
    assert rect is not None
    x,y,w,h = rect
    obs = choose_orientation(recognizer.recognize(page[y:y+h,x:x+w]))
    assert obs.placement() == chess.Board().board_fen()


@pytest.mark.parametrize("game", THEMES, ids=lambda g:g["id"])
def test_compressed_scaled_real_capture(game, recognizer):
    frame = game["frames"][-1]
    image = cv2.imread(str(FIXTURES / "themes" / frame["file"]))
    image = cv2.resize(image, (416,416), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 40])
    assert ok
    decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    obs = recognizer.recognize(decoded, frame["orientation"])
    np.testing.assert_array_equal(obs.labels, board_labels(chess.Board(frame["fen"])), err_msg=frame["file"])


@pytest.mark.parametrize("name", ["lichess-legal-dots.png", "lichess-arrow.png"])
def test_obstructed_real_ui_does_not_add_false_moves(name, recognizer):
    from chessstream.reconstruction import Reconstructor
    reconstruction = Reconstructor(chess.Board())
    reconstruction.observe(recognizer.recognize(cv2.imread(str(FIXTURES / "real" / name))))
    assert not reconstruction.verified
    reconstruction.observe(recognizer.recognize(cv2.imread(str(FIXTURES / "real/lichess-fools-001.png"))))
    assert reconstruction.verified == ["f2f3"]


EXTRAS = [(game, frame) for game in THEMES for frame in game.get("extra_frames", [])]


@pytest.mark.parametrize("game,extra", EXTRAS, ids=[f[1]["file"] for f in EXTRAS])
def test_chesscom_annotation_drag_and_cursor_preserve_moves(game, extra, recognizer, tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());ground=chess.Board()
    for frame in game['frames'][:extra['after_ply']+1]:
        if frame['san']:ground.push_san(frame['san'])
        manager.process(recognizer.recognize(cv2.imread(str(FIXTURES/'themes'/frame['file'])),frame['orientation']))
    expected=[move.uci() for move in ground.move_stack]
    assert manager.rec.verified==expected[:-1]
    observed=choose_orientation(recognizer.recognize(cv2.imread(str(FIXTURES/'themes'/extra['file']))),manager.rec.board)
    manager.process(observed)
    assert manager.rec.verified==expected[:-1],extra['scenario']
    clear=game['frames'][extra['after_ply']+1]
    ground.push_san(clear['san'])
    manager.process(recognizer.recognize(cv2.imread(str(FIXTURES/'themes'/clear['file'])),clear['orientation']))
    assert manager.rec.verified==[move.uci() for move in ground.move_stack[:-1]]
    store.close()
