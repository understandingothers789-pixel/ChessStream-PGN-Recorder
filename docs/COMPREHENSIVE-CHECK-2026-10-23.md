# Comprehensive check — 1.6.24.dev3

Reviewed development build `1.6.24.dev2` / `1e8cc44`, implemented the fixes below,
and validated the resulting `1.6.24.dev3`. Work remains on
`fix/non-destructive-pgn-gap-joins`; main has not been merged or changed.
Tests used temporary libraries and retained public browser fixtures, not the
user's recordings. Measurements are in [the JSON report](comprehensive-check-2026-10-23.json).

## Problems found and fixed

### A witnessed bishop could freeze the PGN after a short capture gap

The broader image replay exposed this sequence in the Opera game:

```text
Observed: ...Bg4
Next sampled board, two plies later: dxe5 Bxf3
```

The old check concatenated the previous pending `Bg4` with the new gap and
treated the bishop's two moves as an entirely unseen excursion. The accepted
PGN stopped at five plies while matching pending hypotheses grew through the
end of the game. This was not a piece-recognition failure.

Each pending branch now records whether one of its individual unobserved gaps
needs confirmation. A witnessed intermediate board separates those gaps.
The evidence flag survives save/reload, opening backfill, repair and joining.
An entirely unseen repeated-piece route still needs confirmation; later frames
cannot silently certify it. Legacy states without per-gap evidence are handled
conservatively, so an already ambiguous old recording may still need review.

The retained 33-ply Opera sequence now completes in one PGN when every other
frame is omitted, with the existing final-move confirmation policy preserved.
The complete sequence, exported PGN and final full FEN match the fixture.

### Native dependency advisories missed by the Python package scanner

The initial scanner reported no findings for the 17-package runtime dependency
closure. Direct vendor review nevertheless found reasons to update three pins:

| Component | Previous | New pin | Finding and reachability |
| --- | --- | --- | --- |
| OpenCV headless | 4.11.0.86 | 4.12.0.88 | CVE-2025-53644 affects the JPEG 2000 decoder and was fixed in 4.12. Live MSS pixel arrays do not enter that decoder. Crafted local files passed to a decoder remain a relevant boundary; no exploit was run. |
| ONNX Runtime | 1.23.2 | 1.24.4 | Upstream PR #26776 validates external tensor-data paths. Bundled models are hash-pinned; a user-selected malicious custom model is the relevant boundary. The maintained 1.24 patch series also includes follow-up validation fixes. |
| PySide6 Essentials / Qt | 6.8.3 | 6.12.0 | The old Qt version is within vendor advisory ranges for SVG/XML/JSON denial of service, including CVE-2026-8168, CVE-2026-16762 and CVE-2026-101201. The current UI generates its own board SVG and uses Python JSON parsing, so those external-document paths were not established as reachable. The available 6.12.0 wheels are outside the cited affected ranges; 6.11.3 wheels were not available on PyPI. |

Sources: [OpenCV disclosure and fixed release](https://securitylab.github.com/advisories/GHSL-2025-057_OpenCV/),
[ONNX Runtime path-validation fix](https://github.com/microsoft/onnxruntime/pull/26776),
[Qt vendor advisory list](https://wiki.qt.io/List_of_known_vulnerabilities_in_Qt_products),
[Qt JSON advisory](https://www.qt.io/blog/security-advisory-cve-2026-101201).

The post-update Python advisory scan found no published findings for the new
15-package runtime closure. That is a scanner result, not a security guarantee
for every native library in the wheels. Custom ONNX files remain a trust decision.

### Error handling and local inference hardening

- Replay rejects non-finite/non-positive intervals and frame rates, and malformed
  crop dimensions. Video handles are released on validation failures; database
  handles are closed if model initialization fails. Invalid video metadata is
  rejected before creating a recording session or running retention.
- Custom-model import closes its temporary file descriptor if the selected
  source disappears before it can be opened, and removes the temporary file.
- All three ONNX session constructors explicitly disable runtime telemetry.
  A regression test forbids Python socket connections, binds and listeners while
  actual bundled board and OCR inference runs. This does not monitor native
  Windows operating-system events.
- The duplicate-instance warning now displays paragraph breaks correctly.
- Portable manifests include the application version and exact source revision;
  Windows CI checks both against the build input before accepting the package.
- The portable builder refreshes wheel downloads and rejects cached duplicate,
  incompatible or incorrectly pinned wheels. Otherwise an old Qt 6.8 wheel can
  sort after 6.12 and overwrite it during extraction, undoing the security update.
- Rewrote stale limitations text that incorrectly described automatic arbitrary
  tie-breaking, older opening limits and unconditional timed splits.

## Validation performed

| Area | Result |
| --- | --- |
| Complete automated suite | **229 passed** in an isolated environment with the updated dependencies. |
| Piece-output equivalence | **120 images / 7,680 squares**, identical labels and complete probability arrays; maximum absolute difference **0.0**. |
| Native OCR equivalence | All four retained native screenshots returned identical context and result data before/after dependency updates. |
| Extended continuity replay | **14/14 sequences**, **116 evaluated positions**, no raw square errors on this retained corpus. |
| Controlled recognition faults | **5/5** specified weak-square faults recovered; these are injected scores, not a real-stream accuracy statistic. |
| Browser game sequences | All four sequences, all PGN round trips and all four every-other-frame gap runs matched. Final pending moves were explicitly confirmed as the evaluator specifies. |
| Random legal search comparison | **60** deterministic one-to-three-ply gaps, **74** shortest routes: complete path sets matched the reference implementation. |
| False history safeguards | Existing false-queen, hidden repeated-piece, incomplete-search, ambiguous-order, premove and rewind tests passed, along with new witnessed-gap/legacy-state tests. |
| Lifecycle and library behavior | Existing opponent/reset, archive contamination, analysis variation, live join cancellation, preserved-source, navigation, keyboard, screenshot selection/deletion and default-no-image tests passed. |
| Abrupt shutdown | A child recorder exited without cleanup after committed moves. SQLite integrity was `ok`; the PGN and three accepted plies restored correctly. This was not a physical disk-full/power-loss test. |
| Diagnostics | Exported ZIP passed archive validation, contained the expected game, and excluded screenshots and the live SQLite database. Screenshot files saved in the durability check: **0**. |
| Security boundaries | Model digest, path, image/resource, safe-scale and file-handling tests passed. Static Python review completed; scanner findings were manually assessed. |
| Dependency consistency | Updated requirements installed in a new isolated environment; `pip check` passed. Source compilation and `git diff --check` passed. |
| GUI | Offscreen application launch/render succeeded and was visually inspected; automated desktop interaction tests passed with Qt 6.12. |

Windows packaging validation is performed by the action run associated with this
commit. Its source tests, bundled inference/OCR, GUI command launcher, shortcut
artwork and manifest identity gates must all pass before calling the portable
artifact ready. This is separate from physical Windows acceptance.

### Paddle advisories and code review

PaddleOCR, PaddleX, PaddlePaddle and Paddle Serving are absent from this runtime.
The OCR models run through the local ONNX adapter. The published records for
[CVE-2026-108961](https://www.cve.org/CVERecord?id=CVE-2026-108961) and
[CVE-2024-0917](https://www.cve.org/CVERecord?id=CVE-2024-0917) were checked;
they do not establish a reachable Paddle-package attack in this build.
PaddleX PR #5212 remained open and unmerged when checked. The separate documented
safe-scale patch/parser remains tested; it is not an installed Paddle dependency.

Runtime source review found no Python configuration `eval`/`exec`, pickle loading
or inference network service. Qt `.exec()` calls are event loops/dialogs. Template
loading uses non-pickle NPZ data with expansion limits. The PowerShell shortcut
script is fixed code receiving JSON over stdin, without shell interpolation of
selected names or paths. Bandit reported 11 findings: fixed/allowlisted SQL
assembly, hotkey constants misidentified as passwords, and subprocess warnings.
SQL values remain parameterized; the subprocess warnings were reviewed rather
than suppressed or treated as proof of exploitation.

### Performance

Two interleaved warmed local CPU timing runs per dependency set measured:

| Operation | Previous median | Updated median |
| --- | ---: | ---: |
| Board inference | 6.935 ms | 7.150 ms |
| OCR on the retained full native result screenshot | 429.685 ms | 378.433 ms |

These small samples include scheduling variability. Board inference differed by
about 0.2 ms; this is not a full recording performance benchmark. Model weights,
preprocessing and recognition outputs remain unchanged. The prior legal-search
optimization remains in place and its complete-path regression tests pass.

## Remaining risks and unchecked behavior

- No new arbitrary-YouTube, physical Windows fullscreen/mixed-DPI/hotkey,
  hour-long CPU/RAM, physical disk-full or installer/uninstaller acceptance run
  was performed. CI package checks do not replace those tests.
- Recognition and game identity can remain ambiguous; finite searches cannot
  prove an unseen move order. Legacy records without witnessed-gap metadata
  remain conservative. A passing corpus is not an overall accuracy claim.
- Observation/audit tables can grow independently of the capped 10,000-entry
  board trace. Optional saved images follow the user's retention settings.
- Distribution remains unsigned. Build hashes record wheel/runtime inputs, but
  transitive dependencies are not yet protected by a complete hash lockfile.
  Native codecs and trusted custom models still require ongoing security review.
- Monitor OpenCV, Qt, ONNX Runtime and the bundled CPython/native libraries for
  later advisories. These selected pins address the reviewed issues; they do
  not establish that all future security updates are unnecessary.

No untrusted advisory proof of concept was executed. This check does not claim
that ChessStream is completely secure or that every prior recording error is fixed.

## Changed files

Recording/evidence: `reconstruction.py`, `games.py`; resource/security handling:
`replay.py`, `model_security.py`, `vision.py`, `results.py`; GUI version/warning:
`gui.py`, `__main__.py`; dependency/version pins: `requirements.txt`,
`pyproject.toml`, `packaging/installer.nsi`; portable provenance:
`scripts/build_windows.py`, `.github/workflows/windows.yml`; regressions:
`test_witnessed_gaps.py`, `test_replay_resources.py`, `test_storage_security.py`,
`test_portable_inputs.py`;
documentation: README, known limitations, this report and its JSON results.
