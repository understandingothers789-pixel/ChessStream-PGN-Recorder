"""Capture themed public Lichess analysis UI, not a custom chessboard renderer.

Testing-only CSS selects upstream piece artwork and textures. The application
does not access a website, DOM, game identity, API, or known move sequence.
"""
from pathlib import Path
import base64
import json
import urllib.request
from datetime import datetime, timezone
import chess
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REVISION = "49fca53ebe4c1466b0ce723bbdf5ee4165d96c39"
UPSTREAM = f"https://raw.githubusercontent.com/lichess-org/lila/{REVISION}/public/"
THEMES = [("chess7", "wood4.jpg"), ("merida", "maple2.jpg"),
          ("maestro", "marble.jpg"), ("tatiana", "blue-marble.jpg")]
MOVES = "e4 e5 Nf3 Nc6 Bc4 Bc5 d4"


def asset(path, mime):
    cache = ROOT / ".cache/theme-fixtures" / path
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(urllib.request.urlopen(UPSTREAM + path, timeout=30).read())
    return "data:" + mime + ";base64," + base64.b64encode(cache.read_bytes()).decode()


def main():
    dest = ROOT / "tests/fixtures/themes"
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {"method": "Actual public Lichess analysis UI in Chromium; testing-only CSS selects pinned upstream piece/board themes",
                "captured_at": datetime.now(timezone.utc).isoformat(), "asset_revision": REVISION, "games": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        for index, (style, texture) in enumerate(THEMES):
            page = browser.new_page(viewport={"width": 1400 if index % 2 == 0 else 1150, "height": 950})
            page.goto("https://lichess.org/analysis", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("cg-board");page.wait_for_timeout(1200)
            rules = []
            for color, name in [("w", "white"), ("b", "black")]:
                for symbol, kind in zip("PNBRQK", ["pawn", "knight", "bishop", "rook", "queen", "king"]):
                    uri = asset(f"piece/{style}/{color}{symbol}.svg", "image/svg+xml")
                    rules.append(f'piece.{name}.{kind} {{ background-image: url("{uri}") !important; }}')
            bg = asset(f"images/board/{texture}", "image/jpeg")
            rules.append(f'cg-board::before {{ background-image: url("{bg}") !important; background-size: 100% 100% !important; }}')
            page.add_style_tag(content="\n".join(rules))
            board = chess.Board();orientation = "black";page.keyboard.press("f")
            frames = []
            for ply, san in enumerate([""] + MOVES.split()):
                if san:
                    move = board.parse_san(san)
                    page.evaluate("uci => window.lichess.analysis.playUci(uci)", move.uci());board.push(move)
                if ply in [3, 5]:
                    page.keyboard.press("f");orientation = "white" if orientation == "black" else "black"
                page.mouse.move(1300, 20);page.wait_for_timeout(400)
                filename = f"{style}-{ply:02d}.png"
                page.locator("cg-board").screenshot(path=str(dest / filename))
                frames.append({"file": filename, "fen": board.fen(), "orientation": orientation, "ply": ply, "san": san})
                if ply == 0:page.screenshot(path=str(dest / f"{style}-page.png"))
            manifest["games"].append({"id": style, "texture": texture, "moves": MOVES, "frames": frames})
            page.close();print(style, flush=True)
        browser.close()
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":main()
