"""Offline source-launcher check; no imports of native libraries or downloads."""
from importlib import metadata
from pathlib import Path
import sys
import tomllib


def mismatches(root, lookup=metadata.version, platform=sys.platform):
    with (root/'pyproject.toml').open('rb') as stream:project=tomllib.load(stream)['project']
    wanted={project['name']:project['version']}
    for specification in project['dependencies']:
        requirement,_,marker=specification.partition(';')
        if marker:
            if marker.strip().replace('"',"'")!="sys_platform == 'win32'":
                raise ValueError('Unsupported dependency marker in source launcher: '+marker)
            if platform!='win32':continue
        name,separator,version=requirement.strip().partition('==')
        if not separator:raise ValueError('Source launcher expects exact dependency pins')
        wanted[name.strip()]=version.strip()
    failures=[]
    for name,expected in wanted.items():
        try:installed=lookup(name)
        except metadata.PackageNotFoundError:installed='missing'
        if installed!=expected:failures.append(f'{name}: installed {installed}; expected {expected}')
    return failures


if __name__=='__main__':
    failures=mismatches(Path(__file__).resolve().parents[1])
    if failures:print('Refreshing source runtime:\n'+'\n'.join(failures))
    raise SystemExit(bool(failures))
