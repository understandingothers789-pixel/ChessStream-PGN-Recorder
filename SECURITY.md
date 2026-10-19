# Security audit: local recognition

Audit date: 2026-10-19. Scope: the ChessStream PGN Recorder source and its active
`.venv` on this workspace. This report records verified properties and reachable
paths; it is not a claim that the application or its dependencies are completely
secure.

## Dependency inventory

The active environment is Python 3.12.14. The application’s pinned runtime
dependencies are `numpy 2.2.6`, `opencv-python-headless 4.11.0.86`, `chess
1.11.2`, `PySide6-Essentials 6.8.3`, `mss 10.0.0`, `platformdirs 4.3.7`,
`Pillow 13.0.0`, `psutil 7.0.0`, and `onnxruntime 1.23.2`. The local build
environment now uses `pip 26.2.1`.

PaddleOCR, PaddleX, PaddlePaddle, Paddle Serving client/server, and RapidOCR
Python packages are **not installed** in the active app environment. The OCR
assets are pretrained PaddleOCR PP-OCRv4 ONNX weights; ChessStream executes
them with ONNX Runtime and OpenCV. The piece detector is another bundled ONNX
model. No Paddle Python inference package is imported at runtime.

An OSV version query on the direct runtime packages and relevant installed
transitives found advisories matching the former `Pillow 11.2.1` pin and local
build-tool `pip 25.0.1`. Pillow was upgraded to 13.0.0 in the project pins and
the local build environment’s pip was upgraded to 26.2.1. OSV returned no
matches for those updated versions on the audit date. This checks known OSV
records for the reported versions; it does not establish that a package is
free of defects. The shipped Windows portable app contains no pip executable.

## Named CVEs

**[CVE-2026-108961](https://nvd.nist.gov/vuln/detail/CVE-2026-108961) — PaddleX `NormalizeImage.__init__`.** The published record
lists PaddleX 3.7.0 through 3.7.2 and identifies `eval(scale)` in
`paddlex/inference/models/text_detection/processors.py`. A crafted scale value
can execute Python if a vulnerable PaddleX text-detection pipeline loads the
configuration. That path is not present in ChessStream: PaddleX is absent, the
app loads fixed ONNX files and JSON app settings, and the app exposes no model
configuration service or network listener. It is therefore **not reachable in
the audited application**. CVE reachability claims of remote initiation require
some separately exposed or attacker-influenced PaddleX configuration-loading
path; they do not describe ChessStream’s screen-capture flow.

The upstream [PaddleX PR #5212](https://github.com/PaddlePaddle/PaddleX/pull/5212)
was open on the audit date, authored from a fork, unsigned, and had no GitHub
reviews. I reviewed its AST allowlist approach and wrote a stricter downstream
patch. It accepts `1./255.` and basic numeric arithmetic while limiting input
length and AST size/depth, rejecting all names/calls/attribute access/indexing,
division by zero, and non-finite results. The patch and testable parser are in
[`security/`](security/PADDLEX_PATCH.md); the diff was tested against the
PaddleX `release/3.7` source at commit
`ffb64904d23708863ff5b8da312a5cbd52a7f462`. It is an optional vendored-source
patch, not a mutation of this app’s environment or someone’s `site-packages`.

**[CVE-2024-0917](https://nvd.nist.gov/vuln/detail/CVE-2024-0917) / [GHSA-mrmm-qmrj-xgp6](https://github.com/advisories/GHSA-mrmm-qmrj-xgp6) — PaddlePaddle remote code execution.**
The GHSA describes PaddlePaddle versions through 2.6.0 and references its
distributed HDFS helper. Its first-patched-version field is empty, and CVE
records do not agree on the exact affected range. PaddlePaddle and its
distributed/HDFS code are absent from ChessStream, so this CVE is **not
reachable in the audited application**. If PaddlePaddle is installed for a
separate workload, do not infer a safe version from this app’s results; consult
the current Paddle advisory and verify the exact release/fix for that workload.

Paddle Serving is neither installed nor referenced in application source.
There is no local HTTP/gRPC server, account, API key, telemetry, or online OCR
request in the app’s inference path.

## Code and input review

- No `eval()` or `exec()` is used by ChessStream. The optional downstream
  PaddleX patch replaces the affected `eval(scale)` instead of wrapping it.
- NumPy model/template archives are loaded with `allow_pickle=False`. Template
  ZIP entries, compressed file size, expanded size, array shapes, types, and
  label ranges are checked before recognition. Template calibration uses a
  private temporary file and atomic replacement.
- Bundled ONNX models are restricted to the application asset directory and
  checked against SHA-256 digests pinned in code before sessions are created.
  Hashing runs once when each model is initialized, not per frame. A custom ONNX
  file is copied into the private app-data `models` directory and must be a
  regular local `.onnx` file smaller than 512 MiB. It remains a user trust
  choice; do not import models from untrusted sources. Custom files must be
  self-contained because only the selected ONNX file is imported.
- Frame inputs must be three-channel 8-bit BGR (or finite in-range float32 only
  for the internal contrast retry), at most 16,384 pixels on either side and
  at most 64 megapixels. Runtime frames come from the selected visible desktop
  region, not from user-uploaded image files.
- Screenshot browser paths are checked to remain under the screenshot directory
  and saved files must have a bounded size and PNG dimensions before Qt decodes
  them. Captured screenshots cannot write to model/config paths.
- Settings use JSON; PGNs are parsed as notation by python-chess. There is no
  YAML loader, Python pickle loading, model download, or image-file import in
  the application workflow. `subprocess` occurs in development/package scripts
  with explicit argument lists; it is not used by the recording/inference path.

## Changes and verification

- Added the bounded PaddleX scale parser and a reproducible patch against the
  vulnerable `release/3.7` source; did not install PaddleX or PaddlePaddle.
- Added pinned integrity checks for all three bundled ONNX files, custom-model
  path/size validation, a 64-megapixel image bound, and bounded NPZ loading.
- Added guarded screenshot path/PNG-header checks and made calibration writes
  atomic, avoiding symlink-following writes through the old fixed `.tmp` path.
- Updated Pillow to 13.0.0 and the build environment/Windows workflow pip to
  26.2.1.
- `tests/test_security.py` covers arithmetic equivalence, non-executing
  malicious scale strings, invalid syntax, model hash/location checks, image
  limits, NPZ expansion limits, and screenshot path boundaries. The existing
  native Chess.com OCR fixture tests check retained result/name reading.

Final test totals, the tagged PaddleX patch applicability check, and measured
startup/hash overhead are recorded in the release notes for this change.

## Remaining risks

The custom ONNX option intentionally permits user-selected model files; ONNX
Runtime and its model parser remain part of that trust boundary. Screen capture
and local screenshot decoding rely on OpenCV/Qt security updates. Local files
and the SQLite database are private to the current user but are not encrypted.
No static or dynamic security review can rule out unknown bugs in native
dependencies, the operating system, or future model/config formats. Keep Python,
ONNX Runtime, OpenCV, Qt, Pillow, and the Windows runtime updated as new advisories
are published.
