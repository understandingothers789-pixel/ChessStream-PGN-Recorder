"""Build a complete offline Windows x64 portable ZIP, on Linux or Windows.

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
import tomllib
import urllib.request
import zipfile
from packaging.requirements import Requirement
from packaging.tags import compatible_tags,cpython_tags
from packaging.utils import parse_wheel_filename

ROOT=Path(__file__).resolve().parents[1]
VERSION='3.13.16'


def validated_wheels(directory,requirements):
    """Reject stale duplicate or incompatible cached wheels before extraction."""
    supported=set(cpython_tags((3,13),platforms=['win_amd64']))
    supported.update(compatible_tags((3,13),interpreter='cp313',platforms=['win_amd64']))
    selected={};paths=sorted(directory.glob('*.whl'))
    for path in paths:
        name,version,_,tags=parse_wheel_filename(path.name)
        if not tags & supported:raise ValueError(f'Incompatible Windows runtime wheel: {path.name}')
        if name in selected:raise ValueError(f'Duplicate cached wheel for {name}; rebuild without --skip-download')
        selected[name]=version
    for line in requirements.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        requirement=Requirement(line)
        name=requirement.name.lower().replace('_','-')
        if name not in selected or selected[name] not in requirement.specifier:
            raise ValueError(f'Cached wheel does not satisfy {requirement}; rebuild without --skip-download')
    return paths


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--makensis', help='Also build the optional NSIS installer with this makensis executable')
    parser.add_argument('--skip-download',action='store_true')
    args=parser.parse_args()
    cache=ROOT/'.cache';wheels=cache/'win-wheels';wheels.mkdir(parents=True,exist_ok=True)
    pure=cache/'wheels';pure.mkdir(exist_ok=True)
    if not args.skip_download:
        # Retaining older wheels lets alphabetic extraction overwrite a new
        # library with an old version (notably Qt 6.8 sorting after 6.12).
        shutil.rmtree(wheels);wheels.mkdir(parents=True)
        subprocess.run([sys.executable,'-m','pip','wheel','--no-deps','chess==1.11.2','-w',str(pure)],check=True)
        subprocess.run([sys.executable,'-m','pip','download','-r',str(ROOT/'requirements.txt'),
            '--platform','win_amd64','--python-version','313','--implementation','cp','--abi','cp313',
            '--only-binary=:all:','--find-links',str(pure),'--dest',str(wheels),'PyAudioWPatch==0.2.12.9'],check=True)
    archive=cache/f'python-{VERSION}-embed-amd64.zip'
    inputs=validated_wheels(wheels,ROOT/'requirements.txt')
    if not archive.exists():
        urllib.request.urlretrieve(f'https://www.python.org/ftp/python/{VERSION}/{archive.name}',archive)
    package=ROOT/'build/windows-portable'
    if package.exists():shutil.rmtree(package)
    runtime=package/'runtime';runtime.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:z.extractall(runtime)
    site=runtime/'Lib/site-packages';site.mkdir(parents=True)
    hashes={archive.name:hashlib.sha256(archive.read_bytes()).hexdigest()}
    for wheel in inputs:
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
    (package/'Launch ChessStream.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nstart "ChessStream PGN Recorder" "%~dp0runtime\\pythonw.exe" -m chessstream %*\r\n',encoding='utf-8',newline='')
    (package/'Diagnose ChessStream.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\n"%~dp0runtime\\python.exe" -m chessstream %*\r\npause\r\n',encoding='utf-8',newline='')
    model=package/'chessstream/assets/models/chess-tiles-v2.onnx'
    model_info=json.loads(model.with_suffix('.json').read_text())
    if hashlib.sha256(model.read_bytes()).hexdigest()!=model_info['sha256']:
        raise RuntimeError('Bundled screenshot model checksum mismatch')
    text_models=json.loads((model.parent/'result-text.json').read_text())
    for entry in text_models['models'].values():
        if hashlib.sha256((model.parent/entry['file']).read_bytes()).hexdigest()!=entry['sha256']:
            raise RuntimeError('Bundled text-recognition model checksum mismatch')
    if not any((site/'onnxruntime').rglob('*.pyd')):
        raise RuntimeError('Windows ONNX Runtime is missing; rebuild without --skip-download to refresh the wheel cache')
    with (ROOT/'pyproject.toml').open('rb') as metadata:app_version=tomllib.load(metadata)['project']['version']
    try:
        revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.CalledProcessError):revision='unknown'
    (package/'BUILD-MANIFEST.json').write_text(json.dumps({'application_version':app_version,'source_revision':revision,
        'python':VERSION,'architecture':'Windows x86-64','inputs_sha256':hashes,
        'model':model_info,'text_models':text_models},indent=2))
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    portable_zip=dist/'ChessStream.zip'
    portable_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(portable_zip,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for path in sorted(package.rglob('*')):
            if path.is_file():
                z.write(path,Path('ChessStream')/path.relative_to(package))
    print('Built portable package:',portable_zip)
    if args.makensis:
        env=os.environ.copy()
        if os.name!='nt' and 'nsis/usr/bin' in args.makensis:
            env['NSISDIR']=str(Path(args.makensis).resolve().parents[1]/'share/nsis')
        subprocess.run([args.makensis,str(ROOT/'packaging/installer.nsi')],cwd=ROOT,env=env,check=True)
        print('Built optional installer:',dist/'ChessStream-PGN-Recorder-Setup.exe')
    print('This artifact contains Windows binaries. Validate on Windows 11 before release.')


if __name__=='__main__':main()
