# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""启动画面（纯 ctypes/Win32，无 tkinter）
- 工具图标（md-editor.ico）+ MDEditor + 动态"正在启动..."
- 淡入显示；收到关闭信号后淡出退出；超时兜底
用法: python _splash.py <信号文件> [超时秒]
      信号文件出现内容 "close" → 淡出退出
"""
import io
import os
import sys
import time
import json
import threading
import urllib.request
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# ---- 显式声明（否则字符串/句柄参数会被按 int 传递而截断）----
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreatePen.restype = wintypes.HANDLE
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.CreateFontW.restype = wintypes.HANDLE
gdi32.CreateFontW.argtypes = [ctypes.c_int] * 13 + [wintypes.LPCWSTR]
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
gdi32.Ellipse.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
user32.DrawTextW.restype = ctypes.c_int
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
user32.FillRect.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.HBRUSH]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, ctypes.c_uint,
                              ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE,
                              ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                              wintypes.HANDLE, ctypes.c_uint]
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF,
                                              ctypes.c_ubyte, ctypes.c_uint]
user32.SetTimer.restype = ctypes.c_size_t
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, ctypes.c_uint, ctypes.c_void_p]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UpdateWindow.argtypes = [wintypes.HWND]
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
user32.ValidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.ValidateRect.restype = wintypes.BOOL
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint,
                             wintypes.WPARAM, wintypes.LPARAM)

W, H = 400, 170
C_BG = 0x00211914          # COLORREF(BGR) 深蓝灰
C_BG2 = 0x002A2119
C_TXT = 0x00EDE7E3         # 近白
C_SUB = 0x00A89E96
C_DOT = 0x00D65B3D         # 强调蓝

WM_DESTROY, WM_PAINT, WM_ERASEBKGND, WM_TIMER = 0x0002, 0x000F, 0x0014, 0x0113
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_LAYERED = 0x8, 0x80, 0x80000
DT_CENTER, DT_VCENTER, DT_SINGLELINE = 0x1, 0x4, 0x20
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
DI_NORMAL = 0x3

_state = {"t0": time.time(), "alpha": 0, "phase": "in", "out_start": 0.0,
          "life": 15.0, "sig": "", "ready": False, "port": 0, "ver": 0,
          "last_tick": -1}
_icon = None


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


def _poll_ready():
    """轮询后端：等任一页面会话上线（= 窗口真正加载完成）→ 触发淡出。

    会话由前端页面加载完成后的首个心跳（/api/ping）登记：
    机器快窗口出得快，画面一闪而过；机器慢窗口出得慢，画面一直撑着。
    服务就绪本身不是信号——服务就绪到窗口可见之间还有 WebView2/浏览器
    冷启动的空档，这段时间正是启动画面该覆盖的。
    兜底：窗口始终没起来（极端故障）时由 life 超时退场。"""
    port = _state["port"]
    if not port:
        return
    t0 = time.time()
    while time.time() - t0 < 40:
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/api/version" % port, timeout=0.3) as r:
                d = json.loads(r.read().decode("utf-8"))
            if int(d.get("sessions", 0)) >= 1:
                if _state["phase"] != "out":
                    _state["phase"] = "out"
                    _state["out_start"] = time.time()
                return
        except Exception:
            pass
        time.sleep(0.15)


def _draw(hwnd):
    hdc = user32.GetDC(hwnd)
    if not hdc:
        return
    try:
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        br = gdi32.CreateSolidBrush(C_BG)
        user32.FillRect(hdc, ctypes.byref(rect), br)
        gdi32.DeleteObject(br)
        # icon (fallback: accent dot)
        if _icon:
            user32.DrawIconEx(hdc, 30, 46, _icon, 64, 64, 0, None, DI_NORMAL)
        else:
            dbr = gdi32.CreateSolidBrush(C_DOT)
            dpen = gdi32.CreatePen(0, 1, C_DOT)
            ob = gdi32.SelectObject(hdc, dbr)
            op = gdi32.SelectObject(hdc, dpen)
            gdi32.Ellipse(hdc, 30, 46, 94, 110)
            gdi32.SelectObject(hdc, ob)
            gdi32.SelectObject(hdc, op)
            gdi32.DeleteObject(dbr)
            gdi32.DeleteObject(dpen)
        # dots animation
        n = int((time.time() - _state["t0"]) * 2.5) % 4
        sub = "正在启动" + "." * n
        gdi32.SetBkMode(hdc, 1)
        f1 = gdi32.CreateFontW(32, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0, "Segoe UI")
        f2 = gdi32.CreateFontW(18, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0, "Microsoft YaHei")
        gdi32.SetTextColor(hdc, C_TXT)
        of = gdi32.SelectObject(hdc, f1)
        r1 = wintypes.RECT(112, 46, W - 24, 92)
        user32.DrawTextW(hdc, "MDEditor", -1, ctypes.byref(r1),
                         DT_CENTER | DT_VCENTER | DT_SINGLELINE)
        gdi32.SetTextColor(hdc, C_SUB)
        gdi32.SelectObject(hdc, f2)
        r2 = wintypes.RECT(112, 94, W - 24, 130)
        user32.DrawTextW(hdc, str(sub), -1, ctypes.byref(r2),
                         DT_CENTER | DT_VCENTER | DT_SINGLELINE)
        gdi32.SelectObject(hdc, of)
        gdi32.DeleteObject(f1)
        gdi32.DeleteObject(f2)
    finally:
        user32.ReleaseDC(hwnd, hdc)


def _proc(hwnd, msg, wparam, lparam):
    if msg == WM_PAINT:
        _draw(hwnd)
        # 关键：GetDC/ReleaseDC 不 validate 更新区域，不显式 ValidateRect
        # 会导致 WM_PAINT 风暴——WM_PAINT 优先级高于 WM_TIMER，风暴会把
        # timer 永久饿死（fade-in/out、超时退场全部失效，窗口卡死）
        user32.ValidateRect(hwnd, None)
        return 0
    if msg == WM_ERASEBKGND:
        return 1
    if msg == 0x0010:  # WM_CLOSE -> fade out then destroy
        if _state["phase"] != "out":
            _state["phase"] = "out"
            _state["out_start"] = time.time()
        return 0
    if msg == WM_TIMER:
        now = time.time()
        repaint = False
        alpha_changed = False
        # fade in: ~5 ticks (fast, 40ms timer -> ~200ms)
        if _state["phase"] == "in":
            nxt = min(246, _state["alpha"] + 62)
            if nxt != _state["alpha"]:
                _state["alpha"] = nxt
                alpha_changed = True
            if _state["alpha"] >= 246:
                _state["phase"] = "hold"
        # close signal file (fallback route)
        if _state["phase"] in ("in", "hold"):
            end = (now - _state["t0"]) > _state["life"]
            try:
                if _state["sig"] and os.path.exists(_state["sig"]):
                    if "close" in open(_state["sig"], encoding="utf-8").read():
                        end = True
            except Exception:
                pass
            if end:
                _state["phase"] = "out"
                _state["out_start"] = now
        # fade out ~200ms
        if _state["phase"] == "out":
            nxt = max(0, _state["alpha"] - 58)
            if nxt != _state["alpha"]:
                _state["alpha"] = nxt
                alpha_changed = True
            if _state["alpha"] <= 0 or (now - _state["out_start"]) > 0.8:
                user32.DestroyWindow(hwnd)
                return 0
        if alpha_changed:
            try:
                user32.SetLayeredWindowAttributes(hwnd, 0, _state["alpha"], 0x2)
            except Exception:
                pass
        # dot animation: repaint only when the dot step changes (~2.5 steps/s)
        tick = int((now - _state["t0"]) * 2.5)
        if tick != _state["last_tick"]:
            _state["last_tick"] = tick
            repaint = True
        if repaint:
            # bErase=False: we repaint fully ourselves, avoid erase flicker
            user32.InvalidateRect(hwnd, None, False)
        return 0
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def main():
    global _icon
    sig = sys.argv[1] if len(sys.argv) > 1 else ""
    life = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    ver = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    _state["sig"] = sig
    _state["life"] = life
    _state["port"] = port
    _state["ver"] = ver
    _state["t0"] = time.time()
    if port:
        threading.Thread(target=_poll_ready, daemon=True).start()

    here = os.path.dirname(os.path.abspath(__file__))
    ico = os.path.join(here, "md-editor.ico")
    hinst = kernel32.GetModuleHandleW(None)
    if os.path.exists(ico):
        try:
            _icon = user32.LoadImageW(hinst, ico, IMAGE_ICON, 64, 64, LR_LOADFROMFILE)
        except Exception:
            _icon = None

    wc = WNDCLASSW()
    wc.lpfnWndProc = WNDPROC(_proc)
    wc.hInstance = hinst
    wc.hCursor = user32.LoadCursorW(None, 32512)
    wc.lpszClassName = "MDEditorSplash2"
    user32.RegisterClassW(ctypes.byref(wc))
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    hwnd = user32.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED,
        "MDEditorSplash2", "MDEditor", WS_POPUP,
        (sw - W) // 2, (sh - H) // 2, W, H, None, None, hinst, None)
    try:
        rgn = gdi32.CreateRoundRectRgn(0, 0, W + 1, H + 1, 30, 30)
        user32.SetWindowRgn(hwnd, rgn, True)
    except Exception:
        pass
    user32.ShowWindow(hwnd, 5)
    user32.UpdateWindow(hwnd)
    try:
        user32.SetLayeredWindowAttributes(hwnd, 0, _state["alpha"], 0x2)
    except Exception:
        pass
    user32.SetTimer(hwnd, 1, 40, None)
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
