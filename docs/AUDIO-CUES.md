# Experimental playback audio cues — 1.6.24-dev4

On the Live recording page:

1. Enable **Audio move cues (experimental)**.
2. Pause the video just before a move. Click **Learn move sound**, then resume it within 10 seconds. Keep commentary and other sounds quiet for this short learning step.
3. Watch the audio status and cue count. If it learned commentary or does not detect subsequent moves, learn again.
4. Optionally repeat with **Learn capture sound** just before a capture. Each button replaces that sound's previous calibration.

The calibration persists between launches. Changes of sound theme or video playback speed may require learning again. Different move/capture sounds need separate calibration. Muted videos produce no cues. Switching output devices requires toggling the option off and on. If the listener reports unavailable, ordinary visual recording continues.

## What it does

Windows WASAPI output loopback listens to the default playback device, including other applications playing through that device. It does not isolate the selected browser tab. No microphone is opened, and there is no microphone fallback. Listening starts only when explicitly enabled and a preview/recording worker is active; stopping that worker closes the listener. Pausing recording discards cue evidence.

A separate thread receives 20 ms blocks, retains at most one second of mono samples plus a bounded device queue, and matches normalized spectral features of learned 240 ms sounds. Matching searches within callback boundaries to accommodate arbitrary sound onset. Matches have a 300 ms cooldown, so rapid successive sounds can merge. Input overflow/discontinuity clears the matching window. Learning expires after 10 seconds and requires a distinct onset; learning underneath speech/music can fail or learn the wrong sound.

A recent cue can support a confidently recognized, unique, single legal move after at least 80 ms of visual stability, instead of waiting 0.5 seconds. Existing visual confirmation frames are still required. Legal search must be complete, and the board must match. Premove, rewind, review, uncertain-transition and hidden-board safeguards remain applicable. Cues expire after one second and are bound to the observed placement and current game. A cue is consumed after acceptance.

Cues cannot choose between alternative move orders, authorize an unseen piece excursion, fabricate an opponent move before a premove, infer the winner, or split/join games. Cue counts are diagnostic hints, not a requirement that exactly that many moves must exist. Existing gap recovery handles skipped positions. Additional use of audio counts to constrain gap search is deferred until cue precision is measured on real videos.

## Storage and dependencies

No WAV, recording, or PCM is saved. Only two normalized spectral feature vectors persist in `audio-cues.json` in the application data directory. These features describe the learned sound. Ordinary board traces include listener status/count/device/level/drop information, without audio samples. Disable the feature to stop listening while continuing normal recording.

The Windows portable includes `PyAudioWPatch==0.2.12.9` and its PortAudio dependency. Linux/macOS show an unavailable status if enabled; visual recording works normally. The app performs no audio-related network requests. No third-party sound samples are bundled.

## Validation

- Automated tests cover learning, saved feature validation, playback volume changes, background tone/noise, arbitrary callback alignment of short clicks, bounded memory, silence, learning timeout, expired/wrong-game/wrong-position cues, disabled mode, incomplete search, flagged detours, premoves, rewinds, and ambiguous paths.
- A mocked Windows device verifies explicit loopback selection and stream/PortAudio cleanup; a non-loopback device is refused.
- Actual Lichess standard `Move.ogg` and `Capture.ogg` were downloaded for development-only evaluation from `https://lichess1.org/assets/sound/standard/`. Neither sample is distributed. Both were learned and detected at 40% amplitude with a low background tone and 0/7/13 ms alignment offsets: 6/6 single-cue trials. These controlled samples are not a measurement of accuracy under commentary. See `scripts/evaluate_audio_cues.py` to repeat against locally downloaded samples.
- Chess.com default `move-self.mp3` and `capture.mp3` from `https://images.chesscomfiles.com/chess-themes/sounds/_MP3_/default/` also passed the same six trials (12/12 total across both sites). These samples are not distributed. Other sound variants and real commentary still need testing.
- The matcher took approximately 20–32 ms per second of audio on the development machine in those trials; this excludes the Windows device driver and is not a full recording performance benchmark.
- Real Windows speakers/headsets, long commentary-heavy videos, sound device switching, and additional Chess.com sound themes need user testing. Windows CI checks packaging/imports and simulated devices, not physical loopback capture.
