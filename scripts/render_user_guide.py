"""Build the bundled offline user guide using only the standard library."""
import html
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def inline(text):
    text=html.escape(text)
    text=re.sub(r'`([^`]+)`',r'<code>\1</code>',text)
    return re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',text)


def main():
    blocks=[]
    for block in (ROOT/'docs/USER_GUIDE.md').read_text(encoding='utf-8').strip().split('\n\n'):
        if block.startswith('# '):blocks.append('<h1>'+inline(block[2:])+'</h1>')
        elif block.startswith('## '):blocks.append('<h2>'+inline(block[3:])+'</h2>')
        elif re.match(r'(?:- |\d+\. )',block):
            tag='ul' if block.startswith('- ') else 'ol'
            lines=[re.sub(r'^(?:- |\d+\. )','',line) for line in block.splitlines()]
            blocks.append(f'<{tag}>'+''.join('<li>'+inline(line)+'</li>' for line in lines)+f'</{tag}>')
        else:blocks.append('<p>'+inline(block).replace('\n','<br>')+'</p>')
    page='<!doctype html><html lang="en"><meta charset="utf-8"><title>ChessStream User Guide</title><style>body{font:16px/1.65 Segoe UI,Arial,sans-serif;background:#101620;color:#dce5f1;max-width:920px;margin:50px auto;padding:20px}h1,h2{color:#86e5cc}h2{margin-top:40px}strong{color:#fff}</style><body>'+''.join(blocks)+'</body></html>\n'
    (ROOT/'chessstream/assets/USER_GUIDE.html').write_text(page,encoding='utf-8')


if __name__=='__main__':main()
