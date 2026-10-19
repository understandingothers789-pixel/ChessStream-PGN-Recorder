# PaddleX `NormalizeImage.scale` patch

PaddleX 3.7.0, 3.7.1, and 3.7.2 contain `eval(scale)` in
`paddlex/inference/models/text_detection/processors.py`. If an attacker can
cause a detector to load a crafted model configuration, that expression can
execute Python during preprocessing setup (CVE-2026-108961).

This repository carries a downstream patch in
`security/patches/paddlex-3.7-safe-scale.patch`. It was reviewed against the
upstream PaddleX PR #5212 but is independently bounded: scale strings are at
most 128 characters and 32 AST nodes / 12 levels; only numeric literals and
`+`, `-`, `*`, `/`, and unary signs are accepted; the result must be finite.
It accepts the existing `1./255.` model configuration form. Names, function
calls, attributes, indexing, exponentiation, non-finite values, and division
by zero fail with `ValueError`.

Apply this patch while building a vendored PaddleX source tree for an isolated
environment, then pin that patched source revision in the build lockfile. For
example, from the root of a clean PaddleX 3.7 source checkout:

```text
git apply --check /path/to/ChessStream/security/patches/paddlex-3.7-safe-scale.patch
git apply /path/to/ChessStream/security/patches/paddlex-3.7-safe-scale.patch
```

Do not use this patch by editing `site-packages` at runtime. The patch has no
effect on ChessStream itself: this application does not install or import
PaddleOCR, PaddleX, or PaddlePaddle. Its PP-OCRv4 weights run through ONNX
Runtime. That is why the patch is kept as a separately documented downstream
artifact instead of adding PaddleX to the application.

The upstream PR is [PaddleX #5212](https://github.com/PaddlePaddle/PaddleX/pull/5212).
At the audit date it was open, had no GitHub reviews, and its commit was
unsigned and authored from a fork. This project does not treat it as an
official released fix.
