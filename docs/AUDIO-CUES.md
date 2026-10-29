# Experimental playback audio cues — 1.6.24-dev5

Enable **Audio move cues (experimental)** above the boards on the Live recording page. It immediately listens for the built-in Chess.com and Lichess default sounds. There are no learning buttons or calibration steps. Old user calibration files are ignored. The status shows the playback device and cue count.

Bundled identification fingerprints cover Lichess standard Move/Capture and Chess.com default move-self/move-opponent/capture/castle/move-check. Source URLs and original file SHA-256 hashes are recorded in `chessstream/assets/audio-presets.json`. Only numerical spectral fingerprints are distributed; source audio is not bundled. The application performs no audio downloads or network requests. Different sound themes, playback speeds, heavy commentary, music, or muted videos can cause missed detections. Default self/opponent sounds can be identical, so audio does not identify whose turn it is.

Windows WASAPI output loopback listens to the default playback device, including other apps playing through it. It does not isolate the selected browser tab. No microphone is opened and there is no microphone fallback. A separate thread handles capture; short audio buffers stay in memory. No audio recording or user calibration is saved. Normal board/FEN diagnostic traces include status, count, level and device information, without audio samples. Disable the option to stop listening. After changing output devices, toggle it off and on. Linux/macOS report audio unavailable; ordinary visual recording continues.

A recent matching sound supports a confidently recognized, unique, single legal move after at least 80 ms of visual stability instead of waiting 0.5 seconds. Existing confirmation frames, legal-search checks, and premove/rewind/analysis safeguards still apply. Cues expire after one second, are bound to the current game and visible placement, and are consumed after acceptance. They do not fabricate moves, decide ambiguous move orders, or prove a premove executed. Cue counts remain diagnostic hints rather than a hard move-count constraint. A 300 ms cooldown can merge very rapid sounds.

Validation includes the automated visual-evidence and simulated loopback tests. All seven published sounds were tested with the built-in presets at 40% amplitude, a quiet background tone, and 0/7/13 ms offsets: **21/21 controlled trials detected one cue**. Results are in `docs/audio-presets-evaluation.json`. These trials do not establish accuracy underneath commentary. Real speakers/headsets and full videos still need user testing. Windows CI checks packaged imports and simulated devices, not physical loopback capture.

## Board timing and replay hints

Cues arriving while the old board is still visible are retained in RAM for at
most one second, then associated once with the next confidently recognized board
change. This accommodates animation and capture timing without allowing old
sounds to support later unrelated moves. The queue holds at most 32 timestamps;
it stores no sound samples. Game changes, capture layout changes, uncertain or
missing boards, recording pauses, audio failures and disabling audio clear this
support. Revisited accepted positions and detected replay/rewind states discard
cues rather than accelerating acceptance. Existing legal and ambiguity checks
remain authoritative.

The audio status also reports an unchanged board after two seconds (thinking or
paused), revisited positions, and several cues between boards (possible skipped
moves). These are diagnostic hints: silence cannot distinguish a video pause
from a player thinking, and a replay can play the same sounds as live moves.
Audio does not determine rewind direction, delete history, split games, or force
a move count. Muted playback continues through the normal visual pipeline.
