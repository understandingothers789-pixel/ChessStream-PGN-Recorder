"""Runtime checks for bundled models and image arrays consumed by inference."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile

import numpy as np


MAX_IMAGE_PIXELS = 64 * 1024 * 1024
MAX_IMAGE_SIDE = 16_384
MAX_CUSTOM_ONNX_BYTES = 512 * 1024 * 1024

# Digests are pinned in application code as well as the human-readable model
# provenance files, so changing a model and its JSON metadata is not enough to
# bypass the runtime check.
BUNDLED_MODEL_SHA256 = {
    "chess-tiles-v2.onnx": "883f6a8e639e6d6b6399b3fda0508ad772e3c6f9cefa2e678a13f27b9fa6248d",
    "result-text-det.onnx": "d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9",
    "result-text-rec.onnx": "48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b",
}


def validate_bgr_image(image: np.ndarray, *, max_pixels: int = MAX_IMAGE_PIXELS,
                       allow_float: bool = False) -> tuple[int, int]:
    """Reject malformed or oversized frame arrays before OpenCV/inference work."""
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Image must be a three-channel BGR array")
    height, width = image.shape[:2]
    if height < 1 or width < 1 or max(height, width) > MAX_IMAGE_SIDE:
        raise ValueError("Image dimensions are outside the supported range")
    if height * width > max_pixels:
        raise ValueError("Image exceeds the 64-megapixel processing limit")
    if image.dtype != np.uint8:
        if not allow_float or image.dtype != np.float32:
            raise ValueError("Image must use 8-bit pixels")
        if image.size and (not np.isfinite(image).all() or image.min() < 0 or image.max() > 255):
            raise ValueError("Floating-point image values must be finite and between 0 and 255")
    return height, width


def verify_bundled_model(path: Path, asset_root: Path, *, max_bytes: int = 64 * 1024 * 1024) -> Path:
    """Require a known bundled ONNX asset, fixed location, size, and SHA-256."""
    root = Path(asset_root).resolve(strict=True)
    candidate = Path(path)
    if candidate.is_symlink():
        raise RuntimeError("Bundled model must not be a symbolic link")
    try:
        resolved = candidate.resolve(strict=True)
        name = resolved.name
        expected = BUNDLED_MODEL_SHA256[name]
    except (FileNotFoundError, KeyError) as exc:
        raise RuntimeError("Bundled model is missing or is not on the model allowlist") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise RuntimeError("Bundled model path is outside the trusted assets directory")
    size = resolved.stat().st_size
    if size <= 0 or size > max_bytes:
        raise RuntimeError("Bundled model file size is outside the supported limit")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError(f"Bundled model integrity check failed: {name}")
    return resolved


def validate_custom_model(path: str | Path, trusted_root: Path | None = None) -> Path:
    """Validate an explicitly selected local ONNX file before creating a session.

    Custom models remain a user trust decision. This check rejects missing,
    non-regular, linked, remote/UNC-like, wrong-extension, and oversized files.
    """
    raw_path = str(path)
    if raw_path.startswith(("\\\\", "//")):
        raise ValueError("Custom ONNX models must be stored on a local drive")
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise ValueError("Custom ONNX models must be regular local files, not links")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Custom ONNX model is not a readable local file") from exc
    if not resolved.is_file() or resolved.suffix.lower() != ".onnx":
        raise ValueError("Custom model must be a regular .onnx file")
    if resolved.stat().st_size <= 0 or resolved.stat().st_size > MAX_CUSTOM_ONNX_BYTES:
        raise ValueError("Custom ONNX model must be smaller than 512 MiB")
    if trusted_root is not None:
        root = Path(trusted_root).resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise ValueError(f"Import custom models into the trusted folder: {root}")
    return resolved


def import_custom_model(source: str | Path, trusted_root: Path) -> Path:
    """Copy a user-selected model atomically into the app-managed models folder."""
    source_path = validate_custom_model(source)
    trusted_root = Path(trusted_root)
    trusted_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = trusted_root.resolve(strict=True)
    if source_path.is_relative_to(root):
        return validate_custom_model(source_path, root)

    fd, temporary = tempfile.mkstemp(dir=root, prefix=".model-", suffix=".tmp")
    digest = hashlib.sha256()
    total = 0
    try:
        with source_path.open("rb") as incoming, os.fdopen(fd, "wb") as outgoing:
            while chunk := incoming.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_CUSTOM_ONNX_BYTES:
                    raise ValueError("Custom ONNX model must be smaller than 512 MiB")
                digest.update(chunk)
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        destination = root / f"custom-{digest.hexdigest()}.onnx"
        if destination.exists():
            if destination.is_symlink() or not destination.is_file():
                raise ValueError("Existing model entry in trusted folder is not a regular file")
            check = hashlib.sha256()
            with destination.open("rb") as existing:
                for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                    check.update(chunk)
            if check.hexdigest() != digest.hexdigest():
                raise RuntimeError("Existing custom model failed its content integrity check")
            os.unlink(temporary)
        else:
            os.replace(temporary, destination)
        return validate_custom_model(destination, root)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
