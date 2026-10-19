"""Windows application identity and a per-user shortcut with ChessStream artwork."""
import ctypes
import hashlib
import json
import logging
from pathlib import Path
import subprocess
import sys
from .domain import atomic_text

APP_ID='ChessStream.PGNRecorder'


def set_application_identity():
    if sys.platform=='win32':
        try:ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError,OSError):logging.exception('Could not set Windows application identity')


def create_desktop_shortcut(root,force=False):
    """Create/update only our named shortcut; never changes Python associations."""
    if sys.platform!='win32':return None
    root=Path(root).resolve();package=Path(__file__).resolve().parent.parent
    source=package/'chessstream/assets/icon.ico'
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    executable=Path(sys.executable).resolve()
    if executable.with_name('pythonw.exe').exists():executable=executable.with_name('pythonw.exe')
    fingerprint={'target':str(executable),'working_directory':str(package),'icon_sha256':digest,'data_dir':str(root)}
    stamp=root/'desktop-shortcut.json'
    if not force and stamp.exists():
        try:
            saved=json.loads(stamp.read_text(encoding='utf-8'))
            if saved.get('fingerprint')==fingerprint and Path(saved['shortcut']).is_file():return Path(saved['shortcut'])
        except (OSError,ValueError,KeyError,TypeError):pass
    # A content-specific icon path also avoids stale Windows icon-cache entries.
    icon=root/'icons'/f'chessstream-{digest[:16]}.ico'
    icon.parent.mkdir(parents=True,exist_ok=True)
    if not icon.exists():icon.write_bytes(source.read_bytes())
    payload={**fingerprint,'icon':str(icon),
             'arguments':subprocess.list2cmdline(['-m','chessstream','--data-dir',str(root)])}
    script="""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$data = [Console]::In.ReadToEnd() | ConvertFrom-Json
$desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory, [Environment+SpecialFolderOption]::Create)
$path = Join-Path $desktop 'ChessStream PGN Recorder.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($path)
$shortcut.TargetPath = $data.target
$shortcut.Arguments = $data.arguments
$shortcut.WorkingDirectory = $data.working_directory
$shortcut.IconLocation = $data.icon + ',0'
$shortcut.Description = 'ChessStream - record visible chess games as PGN'
$shortcut.Save()
[Console]::Out.Write($path)
"""
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
        input=json.dumps(payload,ensure_ascii=True),text=True,encoding='utf-8',capture_output=True,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=10,check=True)
    shortcut=Path(result.stdout.strip())
    if not shortcut.is_file():raise OSError('Windows did not create the ChessStream desktop shortcut')
    atomic_text(stamp,json.dumps({'fingerprint':fingerprint,'shortcut':str(shortcut)},indent=2))
    logging.info('ChessStream desktop shortcut refreshed: %s',shortcut)
    return shortcut
