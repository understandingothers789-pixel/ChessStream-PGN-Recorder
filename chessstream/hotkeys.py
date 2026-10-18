"""Windows RegisterHotKey integration, with focused Qt shortcuts as fallback."""
import ctypes
import sys
from ctypes import wintypes
from PySide6.QtCore import QAbstractNativeEventFilter


class GlobalHotkeys(QAbstractNativeEventFilter):
    def __init__(self,app):
        super().__init__();self.app=app;self.callbacks={}
        if sys.platform=='win32':app.installNativeEventFilter(self)

    def register(self,sequence,callback):
        if sys.platform!='win32':return False
        tokens=sequence.upper().split('+');mod=0x4000;key=None
        for token in tokens:
            token=token.strip()
            if token in ['CTRL','CONTROL']:mod|=2
            elif token=='ALT':mod|=1
            elif token=='SHIFT':mod|=4
            elif token in ['META','WIN']:mod|=8
            elif len(token)==1 and token.isalnum():key=ord(token)
            elif token.startswith('F') and token[1:].isdigit() and 1<=int(token[1:])<=24:key=0x70+int(token[1:])-1
            else:return False
        if key is None:return False
        identity=0x5100+len(self.callbacks)
        if not ctypes.windll.user32.RegisterHotKey(None,identity,mod,key):return False
        self.callbacks[identity]=callback
        return True

    def clear(self):
        if sys.platform=='win32':
            for identity in self.callbacks:ctypes.windll.user32.UnregisterHotKey(None,identity)
        self.callbacks.clear()

    def nativeEventFilter(self,event_type,message):
        if sys.platform=='win32':
            msg=wintypes.MSG.from_address(int(message))
            if msg.message==0x0312 and msg.wParam in self.callbacks:
                self.callbacks[msg.wParam]();return True,0
        return False,0
