The original recognizer could miss light pieces and confuse piece types on textured Chess.com themes. This update replaces the production default with a bundled pretrained screenshot CNN and ONNX Runtime for offline CPU inference. Existing calibration files no longer override that default.

The first position now requires reliable evidence on every square. An uncertain initial board stays pending while screenshots continue to be saved. The interface displays the weakest square score and names uncertain squares. Optional manual template calibration remains available in Settings.

Validation includes the existing browser sequences without calibration, additional textured themes, Chess.com Ocean pieces on Walnut/Burled Wood, both orientations, compression, analysis arrows, a held-piece drag, and a stream-like mouse pointer. The tagged download is built only after Windows tests, packaged neural inference and the GUI smoke check pass. These controlled tests do not establish accuracy on all YouTube streams or all piece sets.

Download `ChessStream-PGN-Recorder-Portable.zip`, right-click it and choose **Extract All**, then open **Launch ChessStream.cmd** in the extracted folder. No installer, admin rights or separate Python setup is needed. The package includes its own Python runtime. If Windows blocks a downloaded launcher, check **Properties → Unblock** on the ZIP before extracting again, where that option is offered.

For an existing recording whose first position was recognized incorrectly by version 1.0, start a fresh recording in the new version. Old PGNs and screenshots are kept; the update cannot recover unwitnessed moves or silently rewrite old recordings.
