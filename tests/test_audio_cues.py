"""Playback cues support visual evidence; they never manufacture chess history."""
import json
import time
from pathlib import Path

import chess
import numpy as np
import pytest

from chessstream.audio import BLOCK, RATE, WINDOW, AudioListener, CueDetector
from chessstream.domain import Observation, Settings, utcnow
from chessstream.games import GameManager
from chessstream.reconstruction import Branch
from chessstream.storage import Store


def cue():
    t=np.arange(WINDOW)/RATE
    return (.3*np.sin(2*np.pi*(900*t+1700*t*t))*np.exp(-18*t)).astype(np.float32)


def feed(detector,samples,start):
    for index in range(0,len(samples),BLOCK):
        detector.feed(samples[index:index+BLOCK],start+(index+BLOCK)/RATE)


def test_learn_match_volume_change_noise_refractory_and_feature_only_persistence(tmp_path):
    path=tmp_path/'audio-cues.json';detector=CueDetector(path)
    detector.learn('move',0)
    feed(detector,np.zeros(RATE//2,np.float32),0)
    feed(detector,cue(),.5)
    assert 'move' in detector.templates and path.exists()
    loaded=CueDetector(path)
    assert loaded.templates.keys()==detector.templates.keys()
    rng=np.random.default_rng(19)
    # Quieter playback with low-level unrelated background sound.
    feed(loaded,np.zeros(RATE//2,np.float32),1)
    feed(loaded,cue()*.4+rng.normal(0,.0005,WINDOW),1.5)
    assert loaded.count==1 and loaded.events[-1]['kind']=='move'
    feed(loaded,np.zeros(WINDOW,np.float32),1.74)
    assert loaded.count==1
    assert set(json.loads(path.read_text()))=={'move'}
    assert all(len(v)==672 for v in json.loads(path.read_text()).values())
    assert list(tmp_path.iterdir())==[path]  # No audio file is saved.


def test_unlearned_speech_like_sound_silence_and_invalid_samples_do_not_emit():
    d=CueDetector();feed(d,cue(),1);assert d.count==0
    d.reset_stream()
    d.templates['move']=__import__('chessstream.audio',fromlist=['fingerprint']).fingerprint(cue())
    t=np.arange(RATE)/RATE
    speech=.03*(np.sin(2*np.pi*145*t)+np.sin(2*np.pi*290*t))*(.5+.5*np.sin(2*np.pi*4*t))
    feed(d,speech,2);feed(d,np.zeros(RATE),3)
    assert not d.events
    d.feed(np.array([np.nan]),4);assert not len(d.samples)


def test_learning_times_out_and_buffers_are_bounded():
    d=CueDetector();d.learn('capture',0)
    feed(d,np.zeros(RATE*11,np.float32),0)
    assert d.learning is None and not d.templates and len(d.samples)<=RATE
    assert 'try again' in d.status


@pytest.mark.parametrize('data',[{'move':[float('nan')]},[],{'other':[1]}, {'move':'bad'}])
def test_invalid_calibration_is_ignored(tmp_path,data):
    p=tmp_path/'audio-cues.json';p.write_text(json.dumps(data))
    assert not CueDetector(p).templates


@pytest.mark.parametrize('case',['good','disabled','stale','other_game','other_board','incomplete','detour','premove','rewind'])
def test_audio_only_accelerates_unique_visual_move(tmp_path,case):
    store=Store(tmp_path);m=GameManager(store,Settings(audio_cues=case!='disabled'))
    m._create(chess.Board(),utcnow());now=[10.];m._clock=lambda:now[0]
    target=chess.Board();target.push_san('e4');obs=Observation.from_board(target)
    m.rec.branches=[Branch(chess.STARTING_FEN,('e2e4',))]
    m._settle_position(obs)
    now[0]=10.1
    m._audio_evidence=(m.current_id,obs.placement(),10.)
    if case=='stale':m._audio_evidence=(m.current_id,obs.placement(),8.)
    if case=='other_game':m._audio_evidence=('previous',obs.placement(),10.)
    if case=='other_board':m._audio_evidence=(m.current_id,chess.Board().board_fen(),10.)
    if case=='incomplete':m.rec.incomplete=True
    if case=='detour':m.rec.gap_requires_confirmation=True
    if case=='premove':m.premove_state={'active':True}
    if case=='rewind':m.rewind_state={'active':True}
    m._settle_position(obs)
    assert m.rec.verified==(['e2e4'] if case=='good' else [])
    if case=='good':
        assert m._audio_evidence is None
        assert 'playback sound' in m.inferred_moves['1']['comment']
    store.close()


def test_audio_does_not_resolve_equal_legal_move_orders(tmp_path):
    store=Store(tmp_path);m=GameManager(store,Settings(audio_cues=True));m._create(chess.Board(),utcnow())
    paths=[]
    for line in ('Nf3 Nf6 Nc3 Nc6','Nc3 Nc6 Nf3 Nf6'):
        board=chess.Board()
        for move in line.split():board.push_san(move)
        paths.append(Branch(chess.STARTING_FEN,tuple(x.uci() for x in board.move_stack)))
    m.rec.branches=paths;now=[10.];m._clock=lambda:now[0];obs=Observation.from_board(board)
    m._settle_position(obs);now[0]=10.6;m._audio_evidence=(m.current_id,obs.placement(),10.5)
    m._settle_position(obs)
    assert not m.rec.verified and len(m.rec.branches)==2
    store.close()


def test_non_windows_fails_without_opening_microphone(monkeypatch,tmp_path):
    monkeypatch.setattr('chessstream.audio.sys.platform','linux')
    listener=AudioListener(tmp_path/'audio-cues.json');listener.start();listener.thread.join(2)
    _,info=listener.poll();listener.stop()
    assert not info['available'] and 'require Windows' in info['status']


def test_loopback_backend_is_output_only_and_releases_resources(monkeypatch,tmp_path):
    import sys
    from types import SimpleNamespace
    calls=[]
    class Stream:
        def stop_stream(self):calls.append('stop')
        def close(self):calls.append('close')
    class Backend:
        def get_default_wasapi_loopback(self):
            return {'isLoopbackDevice':True,'defaultSampleRate':48000,'maxInputChannels':2,'index':9,'name':'Test speakers'}
        def open(self,**kwargs):
            calls.append(kwargs)
            return Stream()
        def terminate(self):calls.append('terminate')
    monkeypatch.setattr('chessstream.audio.sys.platform','win32')
    monkeypatch.setitem(sys.modules,'pyaudiowpatch',SimpleNamespace(PyAudio=Backend,paFloat32=1,paContinue=0))
    listener=AudioListener(tmp_path/'audio-cues.json');listener.start()
    deadline=time.monotonic()+2
    while not calls and time.monotonic()<deadline:time.sleep(.005)
    listener.stop()
    assert calls[0]['input_device_index']==9
    assert calls[0]['input'] and calls[0]['frames_per_buffer']==960
    assert calls[-3:]==['stop','close','terminate'] and not listener.thread.is_alive()


def test_microphone_device_cannot_be_used_as_fallback(monkeypatch,tmp_path):
    import sys
    from types import SimpleNamespace
    calls=[]
    class Backend:
        def get_default_wasapi_loopback(self):return {'isLoopbackDevice':False}
        def open(self,**kwargs):raise AssertionError('Must never open microphone')
        def terminate(self):calls.append('terminate')
    monkeypatch.setattr('chessstream.audio.sys.platform','win32')
    monkeypatch.setitem(sys.modules,'pyaudiowpatch',SimpleNamespace(PyAudio=Backend))
    listener=AudioListener(tmp_path/'audio-cues.json');listener.start();listener.thread.join(2)
    _,info=listener.poll();listener.stop()
    assert not info['available'] and calls==['terminate']


@pytest.mark.parametrize('offset',[0,112,208])
def test_very_short_click_survives_callback_alignment_and_quieter_playback(offset):
    # An impulse followed by a short ring models a move click. Its peak can
    # fall just outside the latest 240 ms window but inside an aligned window.
    t=np.arange(RATE//3)/RATE
    sound=np.zeros(len(t),np.float32)
    start=960
    tail=t[:400]
    sound[start:start+400]=.5*np.cos(2*np.pi*1800*tail)*np.exp(-tail*260)
    d=CueDetector();d.learn('move',0);feed(d,np.zeros(RATE//2),0)
    feed(d,np.pad(sound,(0,RATE)),.5)
    assert d.templates
    d.reset_stream()
    signal=np.pad(sound*.4,(RATE//2+offset,RATE//2))
    feed(d,signal,2)
    assert d.count==1


def test_presets_are_ready_without_learning_and_ignore_old_user_calibration(tmp_path):
    path=tmp_path/'audio-cues.json';path.write_text('old invalid calibration')
    listener=AudioListener(path)
    assert len(listener.detector.templates)==7
    assert 'Listening' in listener.detector.status
    assert listener.detector.learning is None
    assert any('Lichess' in name for name in listener.detector.templates)
    assert any('Chess.com' in name for name in listener.detector.templates)
    assert path.read_text()=='old invalid calibration'


def test_bundled_signatures_are_normalized_and_include_provenance():
    data=json.loads((Path(__file__).parents[1]/'chessstream/assets/audio-presets.json').read_text())
    assert len(data['templates'])==7
    for entry in data['templates']:
        assert len(entry['vector'])==672
        assert np.isfinite(entry['vector']).all()
        assert np.linalg.norm(entry['vector'])==pytest.approx(1,abs=1e-4)
        assert entry['source'].startswith('https://') and len(entry['sha256'])==64


def test_sound_before_animation_is_retained_once_and_expires():
    from chessstream.audio import AudioBoardEvidence
    evidence=AudioBoardEvidence()
    evidence.observe('game','before',[],10.)
    assert evidence.observe('game','before',[{'at':10.1}],10.2)[0] is None
    assert evidence.observe('game','after',[],10.5)[0]==10.1
    assert evidence.observe('game','next',[],10.7)[0] is None
    evidence.observe('game','next',[{'at':11.}],11.1)
    assert evidence.observe('game','later',[],12.2)[0] is None


@pytest.mark.parametrize('case',['review','uncertain','new_game','reset'])
def test_navigation_and_discontinuities_cannot_reuse_sound(case):
    from chessstream.audio import AudioBoardEvidence
    evidence=AudioBoardEvidence()
    evidence.observe('game','before',[],10.)
    evidence.observe('game','before',[{'at':10.1}],10.2)
    if case=='review':
        at,hint=evidence.observe('game','old',[],10.3,review=True)
        assert at is None and 'replay' in hint
    elif case=='uncertain':evidence.observe('game','bad',[],10.3,usable=False)
    elif case=='reset':evidence.reset()
    game='new' if case=='new_game' else 'game'
    assert evidence.observe(game,'after',[],10.5)[0] is None


def test_quiet_board_and_multiple_cues_are_hints_only():
    from chessstream.audio import AudioBoardEvidence
    evidence=AudioBoardEvidence();evidence.observe('game','same',[],10.)
    at,hint=evidence.observe('game','same',[],13.)
    assert at is None and 'thinking or paused' in hint
    evidence.observe('game','same',[{'at':13.1},{'at':13.5}],13.6)
    at,hint=evidence.observe('game','changed',[],13.7)
    assert at==13.5 and 'skipped' in hint
    assert not evidence.pending
    assert evidence.observe('game','next',[{'at':13.5}],13.8)[0] is None
