"""Malformed replay inputs cannot leave a video or database handle open."""
from unittest.mock import Mock

import pytest

import chessstream.replay as replay


@pytest.mark.parametrize('interval',[0,-1,float('nan'),float('inf')])
def test_invalid_replay_interval_is_rejected_before_opening_video(tmp_path,monkeypatch,interval):
    capture=Mock();monkeypatch.setattr(replay.cv2,'VideoCapture',capture)
    with pytest.raises(ValueError,match='finite and positive'):
        replay.replay_video(tmp_path/'video.avi',tmp_path,interval=interval)
    capture.assert_not_called()


@pytest.mark.parametrize('opened,fps,region,message',[
    (False,30,None,'Cannot open video'),
    (True,0,None,'valid frame rate'),
    (True,float('nan'),None,'valid frame rate'),
    (True,float('inf'),None,'valid frame rate'),
    (True,30,'0,0,100','Video region'),
    (True,30,'-1,0,100,100','Video region'),
    (True,30,'0,0,10,100','Video region')])
def test_invalid_video_releases_capture_without_creating_store(tmp_path,monkeypatch,opened,fps,region,message):
    capture=Mock();capture.isOpened.return_value=opened;capture.get.return_value=fps
    store=Mock()
    monkeypatch.setattr(replay.cv2,'VideoCapture',lambda _:capture)
    monkeypatch.setattr(replay,'Store',store)
    with pytest.raises(ValueError,match=message):
        replay.replay_video(tmp_path/'video.avi',tmp_path,region=region)
    capture.release.assert_called_once();store.assert_not_called()


def test_replay_model_failure_releases_video_and_closes_database(tmp_path,monkeypatch):
    capture=Mock();capture.isOpened.return_value=True;capture.get.return_value=30
    store=Mock()
    monkeypatch.setattr(replay.cv2,'VideoCapture',lambda _:capture)
    monkeypatch.setattr(replay,'Store',lambda _:store)
    monkeypatch.setattr(replay,'GameManager',Mock())
    monkeypatch.setattr(replay,'create_recognizer',Mock(side_effect=RuntimeError('model unavailable')))
    with pytest.raises(RuntimeError,match='model unavailable'):
        replay.replay_video(tmp_path/'video.avi',tmp_path)
    capture.release.assert_called_once();store.close.assert_called_once()
