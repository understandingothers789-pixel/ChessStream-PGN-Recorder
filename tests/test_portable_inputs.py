"""A stale build cache must never overwrite updated native dependencies."""
import pytest

from scripts.build_windows import validated_wheels


def cache(tmp_path,names,requirement='PySide6-Essentials==6.12.0'):
    requirements=tmp_path/'requirements.txt';requirements.write_text(requirement+'\n')
    wheels=tmp_path/'wheels';wheels.mkdir()
    for name in names:(wheels/name).touch()
    return wheels,requirements


def test_portable_cache_accepts_compatible_windows_and_pure_wheels(tmp_path):
    wheels,requirements=cache(tmp_path,['pyside6_essentials-6.12.0-cp310-abi3-win_amd64.whl',
        'chess-1.11.2-py3-none-any.whl'])
    assert len(validated_wheels(wheels,requirements))==2


@pytest.mark.parametrize('names,message',[
    (['pyside6_essentials-6.12.0-cp310-abi3-win_amd64.whl',
      'pyside6_essentials-6.8.3-cp39-abi3-win_amd64.whl'],'Duplicate'),
    (['pyside6_essentials-6.8.3-cp39-abi3-win_amd64.whl'],'does not satisfy'),
    (['numpy-2.2.6-cp311-cp311-win_amd64.whl'],'Incompatible'),
    (['pyside6_essentials-6.12.0-cp310-abi3-manylinux_2_34_x86_64.whl'],'Incompatible'),
    ([], 'does not satisfy')])
def test_portable_cache_rejects_old_duplicate_missing_or_wrong_platform_wheels(tmp_path,names,message):
    wheels,requirements=cache(tmp_path,names)
    with pytest.raises(ValueError,match=message):validated_wheels(wheels,requirements)
