"""Optional, local Windows output-loopback cues. Never supplies chess moves.

Only short-lived PCM is kept in RAM; bundled identification features cover
publicly available default move sounds. No user calibration is required. The microphone is never selected as a fallback.
"""
from collections import deque
import json
from pathlib import Path
import logging
import queue
import sys
import threading
import time

import numpy as np

from .domain import atomic_text

RATE = 16000
BLOCK = 320  # 20 ms
WINDOW = 3840  # 240 ms, enough for common click/thud move sounds


def fingerprint(samples):
    samples = np.asarray(samples, dtype=np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(samples, 512)[::160]
    power = np.abs(np.fft.rfft(frames * np.hanning(512), axis=1))[:, 2:226]
    bands = power.reshape(len(frames), 32, 7).mean(axis=2)
    # Remove the low spectral floor before compression so quiet background
    # noise cannot dominate empty frequency bins. Normalize overall volume.
    values = np.maximum(bands - bands.max()*.015, 0)
    values -= values.mean(axis=1, keepdims=True)
    values = values.astype(np.float32).ravel()
    norm = np.linalg.norm(values)
    return values / max(float(norm), 1e-8)


class CueDetector:
    """Bounded streaming template matcher, independent of the audio device."""
    def __init__(self, path=None, *, presets=False):
        self.path = path
        self.templates = {}
        self.samples = np.zeros(0, np.float32)
        self.events = deque(maxlen=32)
        self.count = 0
        self.last_match = -float('inf')
        self.learning = None
        self.learn_at = None
        self.status = 'Learn a move sound to begin'
        self.level = 0.
        self.dropped = 0
        if presets:
            data=json.loads((Path(__file__).parent/'assets/audio-presets.json').read_text())
            expected=len(fingerprint(np.zeros(WINDOW,np.float32)))
            for entry in data['templates']:
                vector=np.asarray(entry['vector'],np.float32)
                if (vector.shape!=(expected,) or not np.isfinite(vector).all()
                        or not .99<np.linalg.norm(vector)<1.01):
                    raise ValueError('Invalid bundled audio preset')
                self.templates[entry['name']]=vector
            if not self.templates:raise ValueError('Bundled audio presets missing')
            self.status='Listening for Chess.com and Lichess default sounds'
        elif path and path.exists():
            try:
                if path.stat().st_size > 100000:raise ValueError('oversized audio calibration')
                values = json.loads(path.read_text())
                expected = len(fingerprint(np.zeros(WINDOW, np.float32)))
                for name, vector in values.items():
                    if name not in ('move', 'capture'):raise ValueError('unknown sound type')
                    vector = np.asarray(vector, np.float32)
                    if vector.shape != (expected,) or not np.isfinite(vector).all():raise ValueError('invalid audio calibration')
                    if not .99 < np.linalg.norm(vector) < 1.01:raise ValueError('invalid audio normalization')
                    self.templates[name] = vector
                if self.templates:self.status = 'Listening for learned move sounds'
            except (OSError, ValueError, TypeError, AttributeError):
                logging.warning('Ignoring invalid audio calibration', exc_info=True)
                self.templates.clear()

    def learn(self, name, now):
        if name not in ('move', 'capture'):raise ValueError('Unknown sound type')
        self.reset_stream()
        self.learning = (name, now + .3, now + 10)
        self.learn_at = None
        self.status = 'Waiting for next distinct sound (10 seconds); keep commentary quiet'

    def reset_stream(self):
        self.samples = np.zeros(0, np.float32)
        self.events.clear()
        self.learn_at = None

    def feed(self, samples, now):
        samples = np.asarray(samples, dtype=np.float32)
        if not np.isfinite(samples).all():
            self.reset_stream();return
        self.samples = np.concatenate((self.samples, samples))[-RATE:]
        self.level = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.
        if self.learning:
            name, armed, deadline = self.learning
            if now > deadline:
                self.learning = None;self.learn_at = None
                self.status = 'No distinct sound learned; try again near a move'
                return
            # User arms immediately before a move; next loud onset is the sample.
            if self.learn_at is None and now >= armed and len(self.samples) >= BLOCK * 4:
                previous = self.samples[-BLOCK * 4:-BLOCK]
                baseline = float(np.sqrt(np.mean(previous * previous)))
                if self.level > max(.006, baseline * 2.5):self.learn_at = now
            if self.learn_at is not None and now - self.learn_at >= (WINDOW - BLOCK) / RATE - 1e-6:
                vector = fingerprint(self.samples[-WINDOW:])
                if np.linalg.norm(vector) > .99:
                    self.templates[name] = vector
                    if self.path:atomic_text(self.path, json.dumps({k:v.tolist() for k,v in self.templates.items()}))
                    self.status = f'Learned {name} sound; listening'
                else:self.status = 'Sound was too flat; please learn again'
                self.learning = None;self.reset_stream()
            return
        if not self.templates or len(self.samples) < WINDOW or now - self.last_match < .3:return
        window = self.samples[-WINDOW-BLOCK:]
        if float(np.sqrt(np.mean(window * window))) < .002:return
        # Search the 20 ms callback boundary in 1 ms steps. Sound onset and
        # device callback boundaries need not align between learning and play.
        vectors=[fingerprint(self.samples[len(self.samples)-WINDOW-offset:len(self.samples)-offset])
                 for offset in range(0,BLOCK,16) if len(self.samples)>=WINDOW+offset]
        name, score = max(((name, max(float(vector @ template) for vector in vectors))
                          for name,template in self.templates.items()), key=lambda pair:pair[1])
        if score >= .94:
            self.last_match = now;self.count += 1
            # Event time is the beginning of the matched sound, not processing time.
            self.events.append({'at':now - WINDOW / RATE, 'kind':name, 'score':round(score, 3)})
            self.status = f'{name.title()} cue detected ({score:.0%})'


class AudioListener:
    """Separate device thread; slow chess searches cannot block audio capture."""
    def __init__(self, path):
        self.detector = CueDetector(presets=True)
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread = None
        self.device = ''
        self.error = ''

    def start(self):
        self.thread = threading.Thread(target=self._run, name='ChessStream-audio', daemon=True)
        self.thread.start()

    def poll(self, discard=False):
        with self.lock:
            events = list(self.detector.events);self.detector.events.clear()
            info = {'status':self.error or self.detector.status, 'device':self.device,
                    'count':self.detector.count, 'level':round(self.detector.level, 4),
                    'dropped_blocks':self.detector.dropped, 'available':not bool(self.error)}
        return ([] if discard else events), info

    def stop(self):
        self.stopping.set()
        if self.thread:self.thread.join(timeout=2)

    def _run(self):
        stream = None;audio = None
        try:
            if sys.platform != 'win32':raise RuntimeError('Playback audio cues require Windows WASAPI')
            import pyaudiowpatch as pa
            audio = pa.PyAudio()
            device = audio.get_default_wasapi_loopback()
            if not device.get('isLoopbackDevice'):raise RuntimeError('No output loopback device; microphone capture is disabled')
            rate = int(device['defaultSampleRate']);channels = min(2, int(device['maxInputChannels']))
            if channels < 1:raise RuntimeError('Output device has no loopback channels')
            chunks = queue.Queue(maxsize=64)
            def callback(data, frame_count, timing, flags):
                item = (data, time.monotonic(), flags)
                try:chunks.put_nowait(item)
                except queue.Full:
                    # Drop oldest, retain current audio and explicitly mark discontinuity.
                    try:chunks.get_nowait()
                    except queue.Empty:pass
                    try:chunks.put_nowait((data, item[1], True))
                    except queue.Full:pass
                return (None, pa.paContinue)
            with self.lock:self.device = device['name']
            stream = audio.open(format=pa.paFloat32, channels=channels, rate=rate,
                input=True, input_device_index=device['index'], frames_per_buffer=rate // 50,
                stream_callback=callback)
            last_at = None
            while not self.stopping.is_set():
                try:data, now, flags = chunks.get(timeout=.1)
                except queue.Empty:continue
                values = np.frombuffer(data, np.float32).reshape(-1, channels).mean(axis=1)
                values = np.interp(np.arange(BLOCK) * rate / RATE, np.arange(len(values)), values).astype(np.float32)
                with self.lock:
                    if flags or (last_at is not None and now - last_at > .15):
                        self.detector.dropped += 1;self.detector.reset_stream()
                    last_at = now
                    self.detector.feed(values, now)
        except Exception as exc:
            logging.warning('Audio cues unavailable: %s', exc, exc_info=True)
            with self.lock:self.error = 'Audio unavailable: ' + str(exc)
        finally:
            if stream:
                try:stream.stop_stream();stream.close()
                except Exception:logging.exception('Closing audio stream failed')
            if audio:audio.terminate()
