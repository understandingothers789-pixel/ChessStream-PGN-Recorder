"""Build a complete offline Windows x64 runtime and NSIS installer, on Linux or Windows.

Uses official CPython embeddable distribution and Windows wheels. No cross-compiled
Python extensions or host-platform DLLs are copied. A Windows smoke test is still
required before a release is advertised as Windows-validated.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='3.13.16'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--makensis',default='makensis');parser.add_argument('--skip-download',action='store_true');args=parser.parse_args()
    cache=ROOT/'.cache';wheels=cache/'win-wheels';wheels.mkdir(parents=True,exist_ok=True)
    pure=cache/'wheels';pure.mkdir(exist_ok=True)
    if not args.skip_download:
        subprocess.run([sys.executable,'-m','pip','wheel','--no-deps','chess==1.11.2','-w',str(pure)],check=True)
        subprocess.run([sys.executable,'-m','pip','download','-r',str(ROOT/'requirements.txt'),
            '--platform','win_amd64','--python-version','313','--implementation','cp','--abi','cp313',
            '--only-binary=:all:','--find-links',str(pure),'--dest',str(wheels)],check=True)
    archive=cache/f'python-{VERSION}-embed-amd64.zip'
    if not archive.exists():
        urllib.request.urlretrieve(f'https://www.python.org/ftp/python/{VERSION}/{archive.name}',archive)
    package=ROOT/'build/windows-portable'
    if package.exists():shutil.rmtree(package)
    runtime=package/'runtime';runtime.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:z.extractall(runtime)
    site=runtime/'Lib/site-packages';site.mkdir(parents=True)
    hashes={archive.name:hashlib.sha256(archive.read_bytes()).hexdigest()}
    for wheel in sorted(wheels.glob('*.whl')):
        if 'linux' in wheel.name:raise ValueError('Non-Windows wheel in build input')
        with zipfile.ZipFile(wheel) as z:
            z.extractall(site)
            for entry in z.namelist():
                # Wheel .data relocation (all required wheels normally use root layout).
                if '.data/purelib/' in entry or '.data/platlib/' in entry:
                    for marker in ['.data/purelib/','.data/platlib/']:
                        if marker in entry and not entry.endswith('/'):
                            target=site/entry.split(marker,1)[1];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(entry))
        hashes[wheel.name]=hashlib.sha256(wheel.read_bytes()).hexdigest()
    # Qt's DLLs and plugins are discovered by its normal Windows wheel bootstrap.
    # OpenCV imports before Qt, so expose app-local C++ runtime DLLs immediately.
    for pattern in ['msvcp140*.dll','concrt140.dll','vcruntime140*.dll']:
        for dll in (site/'PySide6').glob(pattern):
            if not (runtime/dll.name).exists():shutil.copy2(dll,runtime/dll.name)
    (runtime/'python313._pth').write_text('python313.zip\n.\nLib/site-packages\n..\nimport site\n',encoding='utf-8')
    shutil.copytree(ROOT/'chessstream',package/'chessstream',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ['README.md','LICENSE','THIRD_PARTY_NOTICES.md']:
        shutil.copy2(ROOT/name,package/name)
    shutil.copytree(ROOT/'docs',package/'docs')
    (package/'Launch ChessStream.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nstart "ChessStream PGN Recorder" "%~dp0runtime\\pythonw.exe" -m chessstream\r\n',encoding='utf-8')
    (package/'Diagnose ChessStream.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\n"%~dp0runtime\\python.exe" -m chessstream\r\npause\r\n',encoding='utf-8')
    (package/'BUILD-MANIFEST.json').write_text(json.dumps({'python':VERSION,'architecture':'Windows x86-64','inputs_sha256':hashes},indent=2))
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    env=os.environ.copy()
    if os.name!='nt' and 'nsis/usr/bin' in args.makensis:
        env['NSISDIR']=str(Path(args.makensis).resolve().parents[1]/'share/nsis')
    subprocess.run([args.makensis,str(ROOT/'packaging/installer.nsi')],cwd=ROOT,env=env,check=True)
    print('Built:',dist/'ChessStream-PGN-Recorder-Setup.exe')
    print('This artifact contains Windows binaries. Validate on Windows 11 before release.')


if __name__=='__main__':main()
