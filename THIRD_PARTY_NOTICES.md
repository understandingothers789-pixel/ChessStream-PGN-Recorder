# Third-party notices

ChessStream's source is GPL-3.0-or-later. Full project license: `LICENSE`.

## Bundled pretrained screenshot model

`chessstream/assets/models/chess-tiles-v2.onnx` is the fenshot screenshot tile classifier by scoriiu / coachess.app, MIT. Source: https://github.com/scoriiu/fenshot at revision `04d8bbb365e1abc679007cb1ac836fa2dc1e40ac`. Full license: `chessstream/assets/licenses/MIT-fenshot.txt`. Pinned hash, input normalization and class mapping: `chessstream/assets/models/chess-tiles-v2.json`. The upstream training and export pipeline is available in `tools/tile-classifier` in that repository. Only the published trained weights are redistributed; third-party training sprites are not bundled. The Python preprocessing follows the upstream floating-point BT.601 / bilinear tile contract.

## Bundled artwork and optional recognition templates

Downloaded from `https://github.com/lichess-org/lila/tree/49fca53ebe4c1466b0ce723bbdf5ee4165d96c39/public/piece`. The precise files and SHA-256 hashes are in `chessstream/assets/provenance.json`.

- **Cburnett**: Colin M. L. Burnett, GPL-2.0-or-later. Used for recognition and the application icon.
- **Merida**: Armando Hernandez Marroquin, GPL-2.0-or-later.
- **Chessnut**: Alexis Luengas, Apache-2.0.
- **Fantasy and Spatial**: Maurizio Monge, MIT; https://github.com/maurimo/chess-art.

The template bank is generated from this credited artwork at multiple scales; it carries the corresponding artwork licenses. Exact upstream SVG sources are bundled, so the bank can be regenerated. License texts and Lichess's attribution table are in `chessstream/assets/licenses/`. The application does not bundle Chess.com's piece artwork or calibrated Neo templates. A user can create a local template bank from their own visible starting board.

## Dependencies

- python-chess / `chess`, Niklas Fiekas and contributors: GPL-3.0-or-later.
- PySide6 Essentials, Shiboken6 and Qt: LGPL-3.0 / GPL options and applicable Qt exceptions. The installer uses the unmodified, dynamically linked official wheels, retaining their notices and license files. Python sources, DLLs and plugins remain individually accessible under `runtime/Lib/site-packages`; users can replace compatible Qt/PySide binaries. Qt source and licensing information: https://code.qt.io/ and https://www.qt.io/licensing/open-source-lgpl-obligations.
- ONNX Runtime, Microsoft and contributors: MIT, with its wheel notices and third-party license files retained.
- OpenCV: Apache-2.0; NumPy: BSD-3-Clause; Pillow: HPND; MSS: MIT; platformdirs: MIT; psutil: BSD-3-Clause.
- CPython: PSF license and included third-party notices, retained in `runtime/LICENSE.txt`.
- NSIS installer tooling: zlib/libpng license; other bundled installer components under their respective licenses.

Dependency wheels are unmodified apart from normal extraction/installation. Their `*.dist-info` license and notice files remain in the packaged runtime. Windows C++ runtime DLLs are included app-locally as supplied in the official Python and Qt distributions.

## Evaluation screenshots

`tests/fixtures/real` and `tests/fixtures/themes` contain limited screenshots of publicly accessible Lichess and Chess.com analysis interfaces, captured for testing and interoperability evaluation. Site names, logos and interface artwork belong to their owners. These fixtures are not application recognition assets and are not included in the installed application. The sites do not endorse this project. Test moves/positions and screenshot provenance are in the fixture manifest.

Playwright, CairoSVG, pytest and PyInstaller are development dependencies and are not needed in the installed application. The fenshot weights above are bundled and are the default production classifier.
