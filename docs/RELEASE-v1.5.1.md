# ChessStream PGN Recorder v1.5.1

This security update keeps the existing local ONNX recognition flow and adds
checks around the files and image data it consumes.

- Pins SHA-256 checks for the three bundled ONNX models before loading them.
- Limits image dimensions and bounds NPZ template decompression before NumPy
  reads the arrays. Calibration now writes through a private temporary file
  and atomic replacement.
- Imports custom ONNX files into a private app-data `models` folder, validates
  their path and size, and confines screenshot previews to bounded PNG files
  inside screenshot storage.
- Updates Pillow from 11.2.1 to 13.0.0 and the build pip to 26.2.1.
- Includes a reviewed downstream PaddleX patch for the `eval(scale)` issue in
  CVE-2026-108961. PaddleX is not installed or used by this app, so the patch is
  separately documented for vendored PaddleX source and is not applied to
  `site-packages`.
- Documents CVE-2024-0917 and why PaddlePaddle’s distributed HDFS helper is not
  part of this app’s reachable code path.

The workspace suite passed **126 tests**. The native Chess.com fixture OCR
tests and real screenshot model tests passed with expected names, clocks,
results, and board positions. The standalone PaddleX patch was applied to the
PaddleX `release/3.7` source snapshot at
`ffb64904d23708863ff5b8da312a5cbd52a7f462`; the resulting source compiled and
the `eval(scale)` call was absent. Harmless malicious-expression strings were
passed only to the allowlist parser and rejected without running.

SHA-256 verification of all three bundled models took 14.79 ms on the audit
workspace for one initialization pass. This is a one-time model startup check,
not per-frame work. The model preprocessing and inference calculations were
not changed. An OSV query for 15 direct/runtime-relevant packages returned no
matches for the updated versions at release preparation.

PaddleOCR/PaddleX/PaddlePaddle inference packages are not installed in the
workspace, so this release does not claim to test native Paddle inference. It
tests the application’s bundled PaddleOCR PP-OCRv4 ONNX models through ONNX
Runtime. Windows CI gates the portable package on the existing inference,
GUI, launcher, and full test checks before publication.
