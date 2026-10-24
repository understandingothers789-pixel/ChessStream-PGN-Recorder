from importlib import metadata
from pathlib import Path
import tomllib
from scripts.check_runtime import mismatches

ROOT=Path(__file__).parents[1]


def versions():
    with (ROOT/'pyproject.toml').open('rb') as stream:project=tomllib.load(stream)['project']
    pins={project['name']:project['version']}
    for requirement in project['dependencies']:
        name,version=requirement.split(';')[0].strip().split('==')
        pins[name]=version
    return pins


def test_current_windows_runtime_needs_no_download():
    assert mismatches(ROOT,versions().__getitem__,'win32')==[]


def test_reused_old_runtime_is_detected():
    pins=versions();pins.update({'opencv-python-headless':'4.11.0.86','PySide6-Essentials':'6.8.3'})
    errors=mismatches(ROOT,pins.__getitem__,'win32')
    assert len(errors)==2 and any('4.11.0.86' in error for error in errors)


def test_missing_windows_audio_is_detected_but_not_required_on_linux():
    pins=versions()
    def lookup(name):
        if name=='PyAudioWPatch':raise metadata.PackageNotFoundError(name)
        return pins[name]
    assert len(mismatches(ROOT,lookup,'win32'))==1
    assert mismatches(ROOT,lookup,'linux')==[]
