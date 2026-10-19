from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import cv2

from chessstream.model_security import (
    BUNDLED_MODEL_SHA256,
    MAX_IMAGE_PIXELS,
    import_custom_model,
    validate_bgr_image,
    validate_custom_model,
    verify_bundled_model,
)
from chessstream.vision import ASSETS, TemplateRecognizer
from chessstream.domain import Settings
from chessstream.vision import create_recognizer
from chessstream.storage import Store
from security.paddlex_safe_scale import parse_scale_expression


def test_scale_parser_preserves_expected_numeric_preprocessing():
    scale = parse_scale_expression("1./255.")
    assert scale == 1 / 255
    pixels = np.array([0, 1, 127, 255], dtype=np.uint8).astype(np.float32)
    np.testing.assert_array_equal(pixels * np.float32(scale), pixels * np.float32(1 / 255))
    assert parse_scale_expression("-(2 - 3) / 4") == .25


@pytest.mark.parametrize("expression", [
    "__import__('pathlib').Path('/tmp/paddlex-scale-test').touch()",
    "math.sqrt(4)",
    "(1).__class__",
    "[1][0]",
    "1 ** 2",
    "1 / 0",
    "1e999",
    "nan",
    "1 + " + "1 + " * 20 + "1",
    "-" * 20 + "1",
    "1" * 129,
])
def test_scale_parser_rejects_dynamic_or_invalid_expressions(expression):
    with pytest.raises(ValueError):
        parse_scale_expression(expression)


def test_malicious_scale_text_is_inert(tmp_path):
    marker = tmp_path / "must-not-exist"
    expression = f"__import__('pathlib').Path({str(marker)!r}).touch()"
    with pytest.raises(ValueError):
        parse_scale_expression(expression)
    assert not marker.exists()


def test_paddlex_patch_is_a_documented_replacement_not_an_eval_wrapper():
    patch = (Path(__file__).parents[1] / "security/patches/paddlex-3.7-safe-scale.patch").read_text()
    assert "-            scale = eval(scale)" in patch
    assert "+            scale = _parse_scale_expression(scale)" in patch
    assert "ast.Call" not in patch


def test_all_bundled_onnx_assets_match_pinned_digests():
    models = ASSETS / "models"
    for name, digest in BUNDLED_MODEL_SHA256.items():
        path = verify_bundled_model(models / name, models)
        assert path.is_file()
        assert len(digest) == 64


def test_modified_bundled_model_fails_integrity_check(tmp_path):
    path = tmp_path / "chess-tiles-v2.onnx"
    path.write_bytes(b"not the pinned model")
    with pytest.raises(RuntimeError, match="integrity"):
        verify_bundled_model(path, tmp_path)


def test_bundled_model_cannot_be_loaded_from_outside_assets(tmp_path):
    source = ASSETS / "models/chess-tiles-v2.onnx"
    path = tmp_path / source.name
    path.write_bytes(source.read_bytes())
    with pytest.raises(RuntimeError, match="outside"):
        verify_bundled_model(path, ASSETS)


def test_custom_model_must_be_a_bounded_local_onnx_file(tmp_path):
    model = tmp_path / "trusted.onnx"
    model.write_bytes(b"model")
    assert validate_custom_model(model) == model.resolve()
    wrong_extension = tmp_path / "settings.json"
    wrong_extension.write_text("{}")
    with pytest.raises(ValueError, match=".onnx"):
        validate_custom_model(wrong_extension)
    with pytest.raises(ValueError, match="local drive"):
        validate_custom_model(r"\\server\share\model.onnx")
    with pytest.raises(ValueError, match="trusted folder"):
        validate_custom_model(model, tmp_path / "app/models")


def test_imported_custom_model_is_copied_into_app_managed_directory(tmp_path):
    source = tmp_path / "downloaded.onnx"
    source.write_bytes(b"user-selected model")
    models = tmp_path / "app-data" / "models"
    imported = import_custom_model(source, models)
    assert imported.is_relative_to(models.resolve())
    assert imported.read_bytes() == source.read_bytes()
    assert imported.name.startswith("custom-")
    with pytest.raises(ValueError, match="trusted folder"):
        create_recognizer(Settings(onnx_model=str(source)), tmp_path / "custom-templates.npz")


def test_image_input_shape_type_and_pixel_limits_are_checked():
    image = np.zeros((80, 100, 3), dtype=np.uint8)
    assert validate_bgr_image(image) == (80, 100)
    with pytest.raises(ValueError, match="three-channel"):
        validate_bgr_image(np.zeros((80, 100), dtype=np.uint8))
    with pytest.raises(ValueError, match="8-bit"):
        validate_bgr_image(np.zeros((80, 100, 3), dtype=np.float32))
    base = np.zeros((1, 1, 3), dtype=np.uint8)
    huge = np.lib.stride_tricks.as_strided(
        base, shape=(8193, 8193, 3), strides=(0, 0, 1), writeable=False
    )
    assert huge.shape[0] * huge.shape[1] > MAX_IMAGE_PIXELS
    with pytest.raises(ValueError, match="64-megapixel"):
        validate_bgr_image(huge)


def test_template_archive_is_loaded_without_pickle_and_with_expansion_limits(tmp_path):
    path = ASSETS / "templates.npz"
    rgba, labels = TemplateRecognizer._load_bank(path)
    assert rgba.shape[1:] == (32, 32, 4)
    assert labels.shape == (rgba.shape[0],)

    bad = tmp_path / "oversized.npz"
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("rgba.npy", b"0" * (8 * 1024 * 1024 + 1))
        archive.writestr("labels.npy", b"")
    bad.write_bytes(payload.getvalue())
    with pytest.raises(ValueError, match="expands"):
        TemplateRecognizer._load_bank(bad)


def test_screenshot_file_resolution_rejects_paths_outside_storage(tmp_path):
    store = Store(tmp_path)
    session = store.session()
    ok, image = cv2.imencode(".png", np.zeros((80, 80, 3), dtype=np.uint8))
    assert ok
    store.save_screenshot(session, None, cv2.imdecode(image, cv2.IMREAD_COLOR),
                          "2026-10-19T00:00:00.000+00:00")
    row = store.screenshots()[0]
    path = store.screenshot_file(row["path"])
    assert path.is_relative_to(store.images)
    with pytest.raises(ValueError, match="inside screenshot storage"):
        store.screenshot_file("../application.log")
    store.close()
