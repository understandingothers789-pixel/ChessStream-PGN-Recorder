"""Build the offline recognition bank from pinned, credited upstream artwork."""
from pathlib import Path
import concurrent.futures
import hashlib
import io
import json
import urllib.request
import numpy as np
from PIL import Image
import cairosvg

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "chessstream/assets"
SETS = ["cburnett", "merida", "chessnut", "fantasy", "spatial"]
# Resolve this once and record the precise revision with all downloaded checksums.
URL = "https://raw.githubusercontent.com/lichess-org/lila/{revision}/public/piece/{style}/{name}.svg"

def main():
    info = json.load(urllib.request.urlopen("https://api.github.com/repos/lichess-org/lila/commits/master", timeout=30))
    revision = info["sha"]
    tasks = [(s,c+p) for s in SETS for c in "wb" for p in "PNBRQK"]
    def fetch(task):
        style, name = task
        path = ASSETS / "pieces" / style / (name+".svg")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = urllib.request.urlopen(URL.format(revision=revision,style=style,name=name), timeout=30).read()
        path.write_bytes(data)
        return style, name, data
    records, images, labels = [], [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for style, name, data in pool.map(fetch, tasks):
            records.append({"set":style,"file":name+".svg","sha256":hashlib.sha256(data).hexdigest()})
            for scale in [1.0, .90, .80]:
                size = round(32*scale)
                png = cairosvg.svg2png(bytestring=data, output_width=size, output_height=size)
                im = Image.open(io.BytesIO(png)).convert("RGBA")
                canvas = Image.new("RGBA", (32,32))
                canvas.paste(im, ((32-size)//2,(32-size)//2))
                images.append(np.asarray(canvas))
                char = name[1] if name[0] == "w" else name[1].lower()
                labels.append(".PNBRQKpnbrqk".index(char))
    np.savez_compressed(ASSETS/"templates.npz", rgba=np.asarray(images), labels=np.asarray(labels))
    (ASSETS/"provenance.json").write_text(json.dumps({"repository":"https://github.com/lichess-org/lila", "revision":revision, "files":records}, indent=2))
    print(f"Built {len(images)} templates from {len(records)} SVGs at {revision}")

if __name__ == "__main__":
    main()
