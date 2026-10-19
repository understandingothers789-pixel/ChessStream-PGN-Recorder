"""Convert the retained original artwork into Windows and Qt icon assets."""
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]


def main():
    image=Image.open(ROOT/'artwork/chessstream-icon-source.png').convert('RGBA')
    image=image.crop(image.getchannel('A').point(lambda alpha:255 if alpha>=16 else 0).getbbox())
    # Equal small padding on all sides, regardless of the source canvas bounds.
    side=max(image.size)+16
    canvas=Image.new('RGBA',(side,side))
    canvas.alpha_composite(image,((side-image.width)//2,(side-image.height)//2))
    icon=canvas.resize((512,512),Image.Resampling.LANCZOS)
    icon.save(ROOT/'chessstream/assets/icon.png')
    icon.save(ROOT/'chessstream/assets/icon.ico',format='ICO',
              sizes=[(s,s) for s in (16,20,24,32,40,48,64,96,128,256)])


if __name__=='__main__':main()
