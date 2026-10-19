import json
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
import chessstream.desktop as desktop


def test_icon_contains_small_and_hidpi_sizes_with_transparent_corners():
    path=Path(desktop.__file__).parent/'assets/icon.ico'
    with Image.open(path) as icon:
        assert {(16,16),(24,24),(32,32),(48,48),(128,128),(256,256)}<=icon.ico.sizes()
        assert icon.ico.getimage((256,256)).getpixel((0,0))[3]==0


def test_shortcut_uses_app_artwork_hidden_launcher_and_safe_path_parameters(tmp_path,monkeypatch):
    monkeypatch.setattr(desktop.sys,'platform','win32')
    executable=tmp_path/'runtime'/'python.exe';executable.parent.mkdir();executable.touch()
    executable.with_name('pythonw.exe').touch()
    monkeypatch.setattr(desktop.sys,'executable',str(executable))
    link=tmp_path/'Desktop'/'ChessStream PGN Recorder.lnk';link.parent.mkdir()
    calls=[]
    def run(command,**kwargs):
        calls.append((command,kwargs));link.touch()
        return SimpleNamespace(stdout=str(link))
    monkeypatch.setattr(desktop.subprocess,'run',run)
    root=tmp_path/"User's chess files"
    assert desktop.create_desktop_shortcut(root)==link
    payload=json.loads(calls[0][1]['input'])
    assert payload['target'].endswith('pythonw.exe')
    assert payload['data_dir']==str(root) and '-m chessstream' in payload['arguments']
    assert Path(payload['icon']).is_file() and payload['icon'].endswith('.ico')
    assert str(root) not in calls[0][0][-1] # Paths are data over stdin, not shell code.
    assert calls[0][1]['check'] and calls[0][1]['timeout']==10
    desktop.create_desktop_shortcut(root);assert len(calls)==1
    desktop.create_desktop_shortcut(root,force=True);assert len(calls)==2
