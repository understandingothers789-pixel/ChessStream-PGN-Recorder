"""Real Chess.com UI regression captures for the reported shaded piece style.

CSS selects the actual Ocean artwork and Walnut board. Native clicks, flips,
right-drag arrows and a held-piece drag exercise the site itself. Downloaded
piece sprites remain in the ignored development cache, never in app assets.
"""
from pathlib import Path
from datetime import datetime, timezone
import base64
import json
import urllib.request
import chess
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'tests/fixtures/themes'


def image_uri(relative):
    path=ROOT/'.cache/chesscom-fixtures'/relative
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(urllib.request.urlopen('https://images.chesscomfiles.com/chess-themes/'+relative,timeout=30).read())
    return 'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()


def main():
    DEST.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1400,'height':1000})
        page.goto('https://www.chess.com/analysis',wait_until='domcontentloaded',timeout=60000)
        page.wait_for_selector('wc-chess-board');page.wait_for_timeout(1000)
        try:page.get_by_role('button',name='Ok',exact=True).click(timeout=2500)
        except Exception:pass
        css='wc-chess-board {background-image:url("'+image_uri('boards/walnut/200.png')+'") !important; background-size:100% 100% !important;}'
        for color in 'wb':
            for symbol in 'pnbrqk':
                css+=f'wc-chess-board .piece.{color}{symbol} {{background-image:url("'+image_uri(f'pieces/ocean/150/{color}{symbol}.png')+'") !important;}'
        page.add_style_tag(content=css)
        page.keyboard.press('Escape');page.locator('#board-controls-flip').evaluate('(e)=>e.click()');page.wait_for_timeout(500)
        element=page.locator('wc-chess-board');ground=chess.Board();frames=[];extra=[]

        def xy(square):
            bounds=element.bounding_box()
            return (bounds['x']+(7-chess.square_file(square)+.5)*bounds['width']/8,
                    bounds['y']+(chess.square_rank(square)+.5)*bounds['height']/8)

        for ply,san in enumerate(['']+'e4 e5 Nf3 Nc6 Bc4 Bc5 d4'.split()):
            if san:
                move=ground.parse_san(san)
                for square in [move.from_square,move.to_square]:
                    page.mouse.click(*xy(square));page.wait_for_timeout(90)
                ground.push(move)
            page.mouse.move(1200,20);page.wait_for_timeout(500)
            filename=f'chesscom-ocean-{ply:02d}.png';element.screenshot(path=str(DEST/filename))
            frames.append({'file':filename,'fen':ground.fen(),'orientation':'black','ply':ply,'san':san})
            if ply==0:page.screenshot(path=str(DEST/'chesscom-ocean-page.png'))
            if ply==5:
                texture=image_uri('boards/burled_wood/200.png')
                element.evaluate('(e,bg)=>e.style.setProperty("background-image", `url("${bg}")`, "important")',texture)
                page.wait_for_timeout(200)
                filename='chesscom-ocean-burled.png';element.screenshot(path=str(DEST/filename));extra.append({'file':filename,'after_ply':ply,'scenario':'orange burled wood texture'})
                page.keyboard.down('Control')
                for origin,target in [(chess.G8,chess.F6),(chess.F8,chess.C5)]:
                    page.mouse.move(*xy(origin));page.mouse.down(button='right');page.mouse.move(*xy(target),steps=8);page.mouse.up(button='right')
                page.keyboard.up('Control');page.mouse.move(1200,20);page.wait_for_timeout(200)
                filename='chesscom-ocean-arrows.png';element.screenshot(path=str(DEST/filename));extra.append({'file':filename,'after_ply':ply,'scenario':'native analysis arrows'})
                # Clear arrows, then hold a displaced knight inside its source square.
                page.mouse.click(*xy(chess.G8));page.mouse.click(*xy(chess.G8))
                x,y=xy(chess.G8);page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+17,y+8,steps=6);page.wait_for_timeout(200)
                filename='chesscom-ocean-drag.png';element.screenshot(path=str(DEST/filename));extra.append({'file':filename,'after_ply':ply,'scenario':'native held-piece drag, not a completed move'})
                page.mouse.up();page.mouse.move(1200,20);page.wait_for_timeout(400)
                element.evaluate('''e=>{const p=document.createElementNS('http://www.w3.org/2000/svg','svg');p.id='test-stream-cursor';p.setAttribute('viewBox','0 0 24 30');p.style.cssText='position:absolute;left:19%;top:90%;width:18px;height:24px;z-index:999;pointer-events:none';p.innerHTML='<path d="M2 1 L2 24 L8 19 L13 29 L17 27 L12 17 L21 17 Z" fill="white" stroke="black"/>';e.appendChild(p)}''')
                filename='chesscom-ocean-cursor.png';element.screenshot(path=str(DEST/filename));extra.append({'file':filename,'after_ply':ply,'scenario':'stream-like cursor rendered over knight'})
                element.locator('#test-stream-cursor').evaluate('(e)=>e.remove()')
                element.evaluate('(e)=>e.style.removeProperty("background-image")')
        browser.close()
    manifest={'method':'Chromium screenshots of actual Chess.com analysis UI; actual Ocean/Walnut artwork selected by testing-only CSS. Native UI moves, flip, analysis arrows and held-piece drag. Runtime never uses site APIs or this test line.',
              'captured_at':datetime.now(timezone.utc).isoformat(),'games':[{'id':'chesscom-ocean','texture':'walnut','moves':'e4 e5 Nf3 Nc6 Bc4 Bc5 d4','frames':frames,'extra_frames':extra}]}
    (DEST/'chesscom-ocean-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Captured Chess.com Ocean/Walnut regression fixtures')


if __name__=='__main__':main()
