# -*- coding: utf-8 -*-
"""抓图与点击：只用 ctypes + Pillow，不依赖 pywin32 / pyautogui / OpenCV。

抓图优先 PrintWindow(PW_CLIENTONLY)：被别的窗口挡住也能抓到，且不用把
游戏切到前台（复扫雷自己截整窗用的就是这个 API）。
"""
import ctypes
from ctypes import wintypes

import numpy as np
from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# Win64 handles are pointer-sized; ctypes' default c_int truncates them.
for dll, name, restype, argtypes in (
    (user32,'FindWindowW',wintypes.HWND,[wintypes.LPCWSTR,wintypes.LPCWSTR]),
    (user32,'GetDC',wintypes.HDC,[wintypes.HWND]),
    (user32,'ReleaseDC',ctypes.c_int,[wintypes.HWND,wintypes.HDC]),
    (user32,'GetClientRect',wintypes.BOOL,[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]),
    (user32,'ClientToScreen',wintypes.BOOL,[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]),
    (user32,'PrintWindow',wintypes.BOOL,[wintypes.HWND,wintypes.HDC,wintypes.UINT]),
    (user32,'IsWindow',wintypes.BOOL,[wintypes.HWND]),
    (user32,'IsIconic',wintypes.BOOL,[wintypes.HWND]),
    (gdi32,'CreateCompatibleDC',wintypes.HDC,[wintypes.HDC]),
    (gdi32,'CreateCompatibleBitmap',wintypes.HBITMAP,[wintypes.HDC,ctypes.c_int,ctypes.c_int]),
    (gdi32,'SelectObject',wintypes.HANDLE,[wintypes.HDC,wintypes.HANDLE]),
    (gdi32,'DeleteObject',wintypes.BOOL,[wintypes.HANDLE]),
    (gdi32,'DeleteDC',wintypes.BOOL,[wintypes.HDC]),
    (gdi32,'GetDIBits',ctypes.c_int,[wintypes.HDC,wintypes.HBITMAP,wintypes.UINT,wintypes.UINT,ctypes.c_void_p,ctypes.c_void_p,wintypes.UINT]),
):
    fn = getattr(dll,name)
    fn.restype, fn.argtypes = restype,argtypes

CLASS_MAIN = "ComplexSweeperMain"
PW_CLIENTONLY = 0x00000001
SRCCOPY = 0x00CC0020

try:  # 让坐标是真实物理像素（否则 150% 缩放屏上坐标全错）
    ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def find_window(title=None, class_name=CLASS_MAIN):
    hwnd = user32.FindWindowW(class_name if class_name else None,
                              title if title else None)
    return hwnd or None


def list_windows():
    """枚举顶层窗口 (hwnd, class, title)。"""
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        out.append((hwnd, cls.value, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return out


def client_rect(hwnd):
    r = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        raise OSError("GetClientRect 失败")
    return r.right - r.left, r.bottom - r.top


def client_origin(hwnd):
    """客户区左上角的屏幕坐标。"""
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


def is_iconic(hwnd):
    return bool(user32.IsIconic(hwnd))


def grab_client(hwnd):
    """抓客户区，返回 PIL.Image（RGB）。"""
    w, h = client_rect(hwnd)
    if w <= 0 or h <= 0:
        raise OSError("客户区尺寸为 0（窗口最小化了？）")
    hdc = user32.GetDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    ok = user32.PrintWindow(hwnd, mem, PW_CLIENTONLY)
    if not ok:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)
        raise OSError('PrintWindow 失败，拒绝使用可能被遮挡的屏幕图像')

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h  # 负数 = 自上而下
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.SelectObject(mem, old)
    lines = gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    if lines != h:
        raise OSError('GetDIBits 未读取完整图像')
    arr = np.frombuffer(buf.raw, dtype=np.uint8).reshape(h, w, 4)[:, :, 2::-1]
    return Image.fromarray(arr.copy())


# ------------------------------------------------------------------ 输入注入
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE = 0x0001, 0x8000
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
INPUT_MOUSE = 0


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(flags, dx=0, dy=0):
    inp = INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dx, dy, 0, flags, 0, None))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _norm(x, y):
    """屏幕像素 -> SendInput 的 0..65535 绝对坐标。"""
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    return int(x * 65535 / (sw - 1)), int(y * 65535 / (sh - 1))


def click(hwnd, cx, cy, button="left"):
    """在客户区坐标 (cx, cy) 处点一下（先算出屏幕坐标）。"""
    ox, oy = client_origin(hwnd)
    nx, ny = _norm(ox + cx, oy + cy)
    flags = {"left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
             "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
             "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP)}[button]
    _send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, nx, ny)
    _send(flags[0])
    _send(flags[1])


def focus(hwnd):
    user32.SetForegroundWindow(hwnd)


def click_message(hwnd, cx, cy, button='left'):
    """Send paired client messages to the pinned game HWND, without cursor motion."""
    if not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        raise OSError('目标窗口不可用')
    fn = user32.SendMessageTimeoutW
    fn.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM,
                   wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
    fn.restype = ctypes.c_size_t
    down,up,key = {'left':(0x201,0x202,1),'right':(0x204,0x205,2)}[button]
    result = ctypes.c_size_t()
    pos = (cy << 16) | (cx & 0xffff)
    try:
        if not fn(hwnd,down,key,pos,2,1000,ctypes.byref(result)):
            raise OSError('游戏未响应鼠标按下')
    finally:
        if not fn(hwnd,up,0,pos,2,1000,ctypes.byref(result)):
            raise OSError('游戏未响应鼠标释放')
