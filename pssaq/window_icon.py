"""Qt icons and explicit Windows taskbar identity, without extra dependencies."""
import ctypes
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import uuid
from PySide6 import QtCore, QtGui
from .resources import asset_path

APP_ID = 'PSHamware.PSSAQ.Desktop'


def application_icon():
    # Populate sizes explicitly from PNG as well as embedding the ICO in EXE.
    pixmap=QtGui.QPixmap(str(asset_path('pssaq.png')))
    icon=QtGui.QIcon()
    for size in (16,24,32,48,64,128,256):
        icon.addPixmap(pixmap.scaled(size,size,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation))
    return icon


def set_process_identity():
    if sys.platform!='win32':return
    shell=ctypes.WinDLL('shell32',use_last_error=True)
    shell.SetCurrentProcessExplicitAppUserModelID.argtypes=[ctypes.c_wchar_p]
    shell.SetCurrentProcessExplicitAppUserModelID.restype=ctypes.c_int32
    shell.SetCurrentProcessExplicitAppUserModelID(APP_ID)


class GUID(ctypes.Structure):
    _fields_=[('data1',ctypes.c_uint32),('data2',ctypes.c_uint16),
              ('data3',ctypes.c_uint16),('data4',ctypes.c_ubyte*8)]

    @classmethod
    def parse(cls,value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class PROPERTYKEY(ctypes.Structure):
    _fields_=[('fmtid',GUID),('pid',ctypes.c_uint32)]


class CountedPointer(ctypes.Structure):
    _fields_=[('count',ctypes.c_uint32),('pointer',ctypes.c_void_p)]


class VariantValue(ctypes.Union):
    _fields_=[('pointer',ctypes.c_void_p),('number',ctypes.c_int64),('array',CountedPointer)]


class PROPVARIANT(ctypes.Structure):
    _fields_=[('vt',ctypes.c_uint16),('reserved',ctypes.c_uint16*3),('value',VariantValue)]


def _window_properties(hwnd,values=None):
    """Set/read the four Shell string properties; VT_EMPTY clears on close.

    IPropertyStore::SetValue copies the caller-owned PROPVARIANT string.
    Fixed-width fields and pointer-sized handles support 32/64-bit Python.
    """
    shell=ctypes.WinDLL('shell32');ole=ctypes.WinDLL('ole32')
    ole.CoInitializeEx.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
    ole.CoInitializeEx.restype=ctypes.c_int32
    initialized=ole.CoInitializeEx(None,2)
    store=ctypes.c_void_p()
    try:
        iid=GUID.parse('886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99')
        get=shell.SHGetPropertyStoreForWindow
        get.argtypes=[ctypes.c_void_p,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)]
        get.restype=ctypes.c_int32
        result=get(hwnd,ctypes.byref(iid),ctypes.byref(store))
        if result<0:raise OSError(f'SHGetPropertyStoreForWindow: {result:#x}')
        table=ctypes.cast(store,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        fn=ctypes.WINFUNCTYPE(ctypes.c_int32,ctypes.c_void_p,
                             ctypes.POINTER(PROPERTYKEY),ctypes.POINTER(PROPVARIANT))
        set_value=fn(table[6]);get_value=fn(table[5])
        fmtid=GUID.parse('9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3')
        output={}
        clear=ole.PropVariantClear;clear.argtypes=[ctypes.POINTER(PROPVARIANT)];clear.restype=ctypes.c_int32
        for pid in (2,3,4,5):
            key=PROPERTYKEY(fmtid,pid);variant=PROPVARIANT()
            if values is not None:
                text=values.get(pid)
                buffer=None
                if text is not None:
                    buffer=ctypes.create_unicode_buffer(text)
                    variant.vt=31  # VT_LPWSTR; buffer remains alive during SetValue.
                    variant.value.pointer=ctypes.cast(buffer,ctypes.c_void_p).value
                result=set_value(store,ctypes.byref(key),ctypes.byref(variant))
                if result<0:raise OSError(f'IPropertyStore::SetValue: {result:#x}')
            else:
                try:
                    result=get_value(store,ctypes.byref(key),ctypes.byref(variant))
                    if result<0:raise OSError(f'IPropertyStore::GetValue: {result:#x}')
                    output[pid]=ctypes.wstring_at(variant.value.pointer) if variant.vt==31 and variant.value.pointer else None
                finally:clear(ctypes.byref(variant))
        return output
    finally:
        if store.value:
            table=ctypes.cast(store,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_uint32,ctypes.c_void_p)(table[2])(store)
        if initialized in (0,1):ole.CoUninitialize()


def persist_taskbar_icon(root):
    content=asset_path('pssaq.ico').read_bytes()
    digest=hashlib.sha256(content).hexdigest()[:12]
    path=Path(root)/'config'/f'pssaq_taskbar_{digest}.ico'
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists() or path.read_bytes()!=content:
        pending=path.with_suffix('.tmp')
        pending.write_bytes(content);pending.replace(path)
    # A different resource filename refreshes the Shell's image cache when
    # artwork changes. Keep only this app's managed icon files.
    for old in path.parent.glob('pssaq_taskbar*.ico'):
        if old!=path and (old.name=='pssaq_taskbar.ico' or re.fullmatch(r'pssaq_taskbar_[0-9a-f]{12}\.ico',old.name)):
            try:old.unlink()
            except OSError:pass
    return path.resolve()


class TaskbarIdentity:
    def __init__(self,window):
        self.window=window;self.handles=[];self.error=''
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.user.LoadImageW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint32,
                                       ctypes.c_int,ctypes.c_int,ctypes.c_uint32]
        self.user.LoadImageW.restype=ctypes.c_void_p
        self.user.SendMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_size_t,ctypes.c_ssize_t]
        self.user.SendMessageW.restype=ctypes.c_ssize_t
        self.user.DestroyIcon.argtypes=[ctypes.c_void_p];self.user.DestroyIcon.restype=ctypes.c_int
        icon=persist_taskbar_icon(window.root)
        command=[sys.executable]
        if not getattr(sys,'frozen',False):command.append(str(Path(__file__).resolve().parent.parent/'main.py'))
        self.properties={2:subprocess.list2cmdline(command),3:str(icon)+',0',4:'PSSAQ',5:APP_ID}

    def apply(self):
        try:
            hwnd=int(self.window.winId())
            loaded=[]
            for kind,size in ((0,16),(1,32)):
                handle=self.user.LoadImageW(None,str(asset_path('pssaq.ico')),1,size,size,0x10)
                if handle:loaded.append(handle)
            if len(loaded)!=2:
                for handle in loaded:self.user.DestroyIcon(handle)
                raise OSError('LoadImageW could not load both window icons')
            for kind,handle in enumerate(loaded):self.user.SendMessageW(hwnd,0x80,kind,handle)
            for handle in self.handles:self.user.DestroyIcon(handle)
            self.handles=loaded
            _window_properties(hwnd,self.properties)
            self.error=''
        except (OSError,ValueError) as exc:
            self.error=str(exc)

    def verify(self):
        hwnd=int(self.window.winId())
        return (not self.error and all(self.user.SendMessageW(hwnd,0x7f,kind,0) for kind in (0,1))
                and _window_properties(hwnd)==self.properties)

    def close(self):
        hwnd=int(self.window.winId())
        try:_window_properties(hwnd,{})
        except OSError:pass
        for kind in (0,1):self.user.SendMessageW(hwnd,0x80,kind,0)
        for handle in self.handles:self.user.DestroyIcon(handle)
        self.handles=[]


def install_taskbar_identity(window):
    if sys.platform!='win32' or QtGui.QGuiApplication.platformName()!='windows':return None
    try:
        identity=TaskbarIdentity(window)
        window.taskbar_identity=identity
        identity.apply()
        return identity
    except OSError:
        return None
