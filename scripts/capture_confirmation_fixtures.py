"""Real browser regression: reported Italian position and a held legal bishop hover."""
from pathlib import Path
from datetime import datetime,timezone
import json
import chess
from playwright.sync_api import sync_playwright
from capture_chesscom_ocean_fixtures import image_uri,ROOT

DEST=ROOT/'tests/fixtures/confirmation'


def main():
    DEST.mkdir(parents=True,exist_ok=True);cases=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        for name,opening,continuation in [
                ('italian','e4 e5 Nf3 Nc6 Bc4 Bc5 d4 Bxd4 c3 Bb6','Ng5 Nh6 Qf3'),
                ('bishop-drag','e4 e5 Nf3 Nc6 Nc3','')]:
            page=browser.new_page(viewport={'width':1400,'height':1000})
            page.goto('https://www.chess.com/analysis',wait_until='domcontentloaded',timeout=60000)
            page.wait_for_selector('wc-chess-board');page.wait_for_timeout(1000)
            try:page.get_by_role('button',name='Ok',exact=True).click(timeout=2000)
            except Exception:pass
            css='wc-chess-board {background-image:url("'+image_uri('boards/walnut/200.png')+'") !important; background-size:100% 100% !important;}'
            for c in 'wb':
                for s in 'pnbrqk':css+=f'wc-chess-board .piece.{c}{s} {{background-image:url("'+image_uri(f'pieces/ocean/150/{c}{s}.png')+'") !important;}'
            page.add_style_tag(content=css);page.locator('#board-controls-flip').evaluate('(e)=>e.click()');page.wait_for_timeout(300)
            element=page.locator('wc-chess-board');board=chess.Board();frames=[]
            def xy(square):
                r=element.bounding_box()
                return r['x']+(7-chess.square_file(square)+.5)*r['width']/8,r['y']+(chess.square_rank(square)+.5)*r['height']/8
            def move(san):
                m=board.parse_san(san)
                for sq in [m.from_square,m.to_square]:page.mouse.click(*xy(sq));page.wait_for_timeout(70)
                board.push(m);page.wait_for_timeout(350)
            def shot(label,kind='position'):
                path=f'{name}-{label}.png';element.screenshot(path=str(DEST/path))
                frames.append({'file':path,'kind':kind,'fen':board.fen(),'orientation':'black'})
            for san in opening.split():move(san)
            initial=board.fen();page.mouse.move(1200,20);shot('root')
            if name=='italian':
                for san in continuation.split():move(san);page.mouse.move(1200,20);shot(san)
                page.keyboard.down('Alt')
                for start,end in [(chess.G5,chess.F7),(chess.C4,chess.F7)]:
                    page.mouse.move(*xy(start));page.mouse.down(button='right');page.mouse.move(*xy(end),steps=8);page.mouse.up(button='right')
                page.keyboard.up('Alt');page.mouse.move(1200,20);shot('arrows','annotation')
                page.mouse.click(*xy(chess.D7));page.mouse.click(*xy(chess.D7))
                move('d6');page.mouse.move(1200,20);shot('reply')
            else:
                page.mouse.move(*xy(chess.F8));page.mouse.down();page.mouse.move(*xy(chess.C5),steps=15);page.wait_for_timeout(500);shot('hover-c5','hover')
                page.wait_for_timeout(1500);shot('hover-c5-held','hover')
                page.mouse.move(*xy(chess.B4),steps=12);page.wait_for_timeout(300);shot('hover-b4','hover')
                page.mouse.up();board.push_san('Bb4');page.mouse.move(1200,20);page.wait_for_timeout(400);shot('released-b4')
                move('a3');page.mouse.move(1200,20);shot('reply')
            cases.append({'id':name,'initial_fen':initial,'frames':frames});page.close()
        browser.close()
    manifest={'method':'Actual Chromium Chess.com UI: native mouse moves, native held drag (no drop at c5), release at b4, and native blue analysis arrows. Test artwork selection only; no site access in runtime.',
              'captured_at':datetime.now(timezone.utc).isoformat(),'cases':cases}
    (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Captured confirmation regression fixtures')


if __name__=='__main__':main()
