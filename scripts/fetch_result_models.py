"""Reproduce the bundled Apache-2.0 PP-OCRv4 ONNX model assets from a pinned wheel."""
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    dest=ROOT/'chessstream/assets/models'
    manifest=json.loads((dest/'result-text.json').read_text())
    with urllib.request.urlopen('https://pypi.org/pypi/rapidocr-onnxruntime/1.4.4/json') as response:metadata=json.load(response)
    url=next(item['url'] for item in metadata['urls'] if item['filename'].endswith('.whl'))
    with urllib.request.urlopen(url) as response:content=response.read()
    if hashlib.sha256(content).hexdigest()!=manifest['wheel_sha256']:raise ValueError('OCR wheel checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for kind,entry in manifest['models'].items():
            model=archive.read(f'rapidocr_onnxruntime/models/ch_PP-OCRv4_{kind}_infer.onnx')
            if hashlib.sha256(model).hexdigest()!=entry['sha256']:raise ValueError('Model checksum mismatch')
            (dest/entry['file']).write_bytes(model)
    print('Verified offline result and context OCR assets')

if __name__=='__main__':main()
