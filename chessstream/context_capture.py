"""Small temporary context captures around a board, in physical screen pixels."""
import numpy as np
from .domain import Region


def context_region(source,board_rect,desktop,padding_percent=18):
    x,y,w,h=board_rect
    left,top=source.left+x,source.top+y
    if left<desktop["left"] or top<desktop["top"] or left+w>desktop["left"]+desktop["width"] or top+h>desktop["top"]+desktop["height"]:
        raise ValueError("Board is partly outside the visible desktop")
    # Player nameplates typically sit above and below the board; give these
    # rows more pixels than the horizontal gutters without expanding to the
    # entire stream or breaking the user-adjustable base padding setting.
    pad_x=round(w*padding_percent/100);pad_y=round(h*padding_percent/100*1.35)
    x0=max(desktop['left'],left-pad_x);y0=max(desktop['top'],top-pad_y)
    x1=min(desktop['left']+desktop['width'],left+w+pad_x)
    y1=min(desktop['top']+desktop['height'],top+h+pad_y)
    if x1<=x0 or y1<=y0:raise ValueError('Board is outside the visible desktop')
    region=Region(x0,y0,x1-x0,y1-y0)
    return region,(left-x0,top-y0,w,h)


def capture_context(cap,source,image,board_rect,enabled=True,padding_percent=18):
    """Reuse selected pixels when possible; otherwise grab only the nearby margin.

    Returns image, board coordinates within it, and whether a newer frame was
    captured. Callers use the newer board pixels too, keeping move/clock evidence
    in the same frame. Nothing in this function writes images to disk.
    """
    if not enabled or board_rect is None:return image,board_rect,False
    region,relative=context_region(source,board_rect,cap.monitors[0],padding_percent)
    contained=(source.left<=region.left and source.top<=region.top and
               region.left+region.width<=source.left+source.width and
               region.top+region.height<=source.top+source.height)
    if contained:
        x,y=region.left-source.left,region.top-source.top
        return image[y:y+region.height,x:x+region.width].copy(),relative,False
    pixels=np.asarray(cap.grab({key:getattr(region,key) for key in ['left','top','width','height']}))[:,:,:3].copy()
    return pixels,relative,True
