"""Capture actual public analysis boards in Chromium, with known legal test games.

Only fixture creation uses the sites' UI. The application never reads their DOM,
network, usernames or chess APIs. These are tests, not built-in recording moves.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse
import json
import chess
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'tests/fixtures/real'
GAMES={
 'lichess-fools': 'f3 e5 g4 Qh4#',
 'lichess-scholar': 'e4 e5 Bc4 Nc6 Qh5 Nf6 Qxf7#',
 'lichess-opera': 'e4 e5 Nf3 d6 d4 Bg4 dxe5 Bxf3 Qxf3 dxe5 Bc4 Nf6 Qb3 Qe7 Nc3 c6 Bg5 b5 Nxb5 cxb5 Bxb5+ Nbd7 O-O-O Rd8 Rxd7 Rxd7 Rd1 Qe6 Bxd7+ Nxd7 Qb8+ Nxb8 Rd8#',
 'chesscom-ruy': 'e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O',
}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--chromium',default='/usr/bin/chromium');args=parser.parse_args()
    DEST.mkdir(parents=True,exist_ok=True)
    manifest={'captured_at':datetime.now(timezone.utc).isoformat(),'method':'Playwright screenshots of actual public analysis UI, not a custom renderer','games':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
        for name,sequence in GAMES.items():
            page=browser.new_page(viewport={'width':1400,'height':1000})
            is_lichess=name.startswith('lichess')
            url='https://lichess.org/analysis' if is_lichess else 'https://www.chess.com/analysis'
            page.goto(url,wait_until='domcontentloaded',timeout=60000)
            selector='cg-board' if is_lichess else 'wc-chess-board'
            page.wait_for_selector(selector,timeout=30000);page.wait_for_timeout(2200)
            if not is_lichess:
                try:page.get_by_role('button',name='Ok',exact=True).click(timeout=4000)
                except Exception:pass
                page.wait_for_timeout(700)
            board_element=page.locator(selector).first
            b=chess.Board();frames=[];orientation='white'
            for ply,san in enumerate(['']+sequence.split()):
                if san:
                    move=b.parse_san(san)
                    if is_lichess:
                        page.evaluate('(uci)=>window.lichess.analysis.playUci(uci)',move.uci())
                    else:
                        bbox=board_element.bounding_box()
                        for square in [move.from_square,move.to_square]:
                            x=bbox['x']+(chess.square_file(square)+.5)*bbox['width']/8
                            y=bbox['y']+(7-chess.square_rank(square)+.5)*bbox['height']/8
                            page.mouse.click(x,y);page.wait_for_timeout(70)
                    b.push(move)
                # Exercise real UI flips midgame, without changing the chess position.
                if name=='lichess-opera' and ply in [6,17]:
                    page.keyboard.press('f');orientation='black' if orientation=='white' else 'white'
                page.mouse.move(1250,30);page.wait_for_timeout(450)
                path=f'{name}-{ply:03d}.png'
                board_element.screenshot(path=str(DEST/path))
                frames.append({'file':path,'fen':b.fen(),'ply':ply,'san':san,'orientation':orientation})
                if ply==0:
                    page.screenshot(path=str(DEST/(name+'-page.png')))
                    if is_lichess and name=='lichess-fools':
                        board_element.screenshot(path=str(DEST/'lichess-start.png'))
                        page.screenshot(path=str(DEST/'lichess-start-page.png'))
                print(name,ply,san,flush=True)
            manifest['games'].append({'id':name,'url':url,'moves':sequence,'frames':frames,'calibrate':not is_lichess})
            page.close()
            (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        browser.close()


if __name__=='__main__':main()
