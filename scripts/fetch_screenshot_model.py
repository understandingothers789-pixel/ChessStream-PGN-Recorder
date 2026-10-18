"""Fetch the pinned pretrained model; not called at application runtime."""
from pathlib import Path
import hashlib
import json
import urllib.request

root = Path(__file__).resolve().parents[1]
path = root / 'chessstream/assets/models/chess-tiles-v2.onnx'
metadata = json.loads(path.with_suffix('.json').read_text())
url = metadata['source'].replace('github.com/', 'raw.githubusercontent.com/')
url += '/' + metadata['revision'] + '/' + metadata['upstream_path']
data = urllib.request.urlopen(url, timeout=60).read()
if hashlib.sha256(data).hexdigest() != metadata['sha256']:
    raise RuntimeError('Model checksum does not match the pinned release')
path.write_bytes(data)
print('Fetched verified model:', path)
