# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""独立「保存文件」对话框进程（纯 ctypes 调 comdlg32.GetSaveFileNameW）。

与 _pickfile.py 同一套 Win32 路线（便携 Python 无 tkinter），差别：
- GetSaveFileNameW：可输入文件名、按扩展名过滤、自动补扩展名
- OFN_OVERWRITEPROMPT：覆盖已有文件时由系统弹「是否替换」
- 取消时写入空串（调用方据此什么都不做）

用法: python _savefile.py <输出文件> <标题> <默认文件名> <初始目录> <过滤串>
过滤串形如 "Word 文档 (*.docx)\0*.docx\0所有文件 (*.*)\0*.*\0\0"
"""
import ctypes
import io
import sys
from ctypes import wintypes


class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", ctypes.c_void_p),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", wintypes.LPCWSTR),
    ]


# OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST | OFN_EXPLORER | OFN_NOCHANGEDIR
# | OFN_HIDEREADONLY | OFN_LONGNAMES
FLAGS = 0x00000002 | 0x00000800 | 0x00080000 | 0x00000008 | 0x00000004 | 0x00200000


def save_file(title, default_name, init_dir, filter_str, def_ext):
    comdlg32 = ctypes.windll.comdlg32
    user32 = ctypes.windll.user32
    try:
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)   # STA
    except Exception:
        pass
    try:
        buf = ctypes.create_unicode_buffer(32768)
        if default_name:
            buf.value = default_name
        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        # 以当前前台窗口为主人，对话框才会随编辑器置前
        try:
            ofn.hwndOwner = user32.GetForegroundWindow()
        except Exception:
            ofn.hwndOwner = None
        ofn.lpstrFilter = filter_str
        ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
        ofn.nMaxFile = 32768
        ofn.lpstrTitle = title
        ofn.lpstrInitialDir = init_dir or None
        ofn.Flags = FLAGS
        ofn.lpstrDefExt = def_ext or None
        comdlg32.GetSaveFileNameW.restype = wintypes.BOOL
        comdlg32.GetSaveFileNameW.argtypes = [ctypes.POINTER(OPENFILENAMEW)]
        if not comdlg32.GetSaveFileNameW(ctypes.byref(ofn)):
            return ""
        return buf.value
    finally:
        try:
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            pass


try:
    out_path = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else "保存"
    default_name = sys.argv[3] if len(sys.argv) > 3 else ""
    init_dir = sys.argv[4] if len(sys.argv) > 4 else ""
    filter_str = sys.argv[5] if len(sys.argv) > 5 else "所有文件 (*.*)\0*.*\0\0"
    def_ext = sys.argv[6] if len(sys.argv) > 6 else ""
    result = save_file(title, default_name, init_dir, filter_str, def_ext)
except Exception:
    result = ""
try:
    io.open(sys.argv[1], "w", encoding="utf-8").write(result or "")
except Exception:
    pass
