from pathlib import Path
import json
from playwright.sync_api import sync_playwright
out=Path('tests/fixtures/results');out.mkdir(exist_ok=True)
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 page=b.new_page(viewport={'width':1200,'height':1000})
 page.goto('https://www.chess.com/play/computer',wait_until='domcontentloaded',timeout=60000)
 page.get_by_role('button',name='Start',exact=True).click(timeout=15000)
 try:
  page.get_by_role('button',name='Options',exact=True).click(timeout=4000)
  page.get_by_role('button',name='10 min',exact=True).click(timeout=4000)
 except Exception as e:print('Clock option:',type(e).__name__)
 page.get_by_role('button',name='Play',exact=True).click(timeout=10000)
 page.get_by_role('button',name='Resign',exact=True).wait_for(timeout=45000)
 import sys
 sys.path.insert(0,str(Path.cwd()/'scripts'))
 from capture_chesscom_ocean_fixtures import image_uri
 css='wc-chess-board {background-image:url("'+image_uri('boards/walnut/200.png')+'") !important; background-size:100% 100% !important;}'
 for c in 'wb':
  for piece in 'pnbrqk':css+=f'wc-chess-board .piece.{c}{piece} {{background-image:url("'+image_uri(f'pieces/ocean/150/{c}{piece}.png')+'") !important;}'
 page.add_style_tag(content=css)
 page.wait_for_timeout(1000)
 page.screenshot(path=str(out/'native-bot-start.png'))
 board=page.locator('wc-chess-board').first
 rect=board.bounding_box();print('board',rect)
 for file,rank in [(4,1),(4,3)]:page.mouse.click(rect['x']+(file+.5)*rect['width']/8,rect['y']+(7-rank+.5)*rect['height']/8);page.wait_for_timeout(100)
 page.wait_for_timeout(2200)
 page.screenshot(path=str(out/'native-bot-clock.png'))
 for file,rank in [(6,0),(5,2),(5,0),(2,3)]:
  page.mouse.click(rect['x']+(file+.5)*rect['width']/8,rect['y']+(7-rank+.5)*rect['height']/8)
  page.wait_for_timeout(1800 if (file,rank) in [(5,2),(2,3)] else 100)
 page.get_by_role('button',name='Resign',exact=True).click()
 page.wait_for_timeout(500)
 print(page.locator('body').inner_text()[-1500:])
 buttons=page.get_by_role('button',name='Yes',exact=True)
 if buttons.count():buttons.click()
 else:
  again=page.get_by_role('button',name='Resign',exact=True)
  if again.count():again.last.click()
 page.wait_for_timeout(1500)
 page.screenshot(path=str(out/'native-bot-resigned.png'))
 (out/'native-manifest.json').write_text(json.dumps({'source':'Actual Chromium Chess.com play/computer guest UI, clock option selected, native e4 and resignation clicks; Ocean/Walnut artwork chosen with CSS only; no text/result injection','board_rect':rect,'orientation':'white','text':page.locator('body').inner_text()[-2000:]},indent=2))
 print(page.locator('body').inner_text()[-2000:])
 b.close()
