# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""现代"选择文件夹"对话框（纯 ctypes 调 COM 的 IFileOpenDialog + FOS_PICKFOLDERS）。

与系统"打开/保存"对话框是同一个现代 UI（Vista/Win10/Win11 风格），
而不是老式的 SHBrowseForFolder 树状框。
本机没有 pywin32 / tkinter，因此手写 COM vtable 调用。

用法: python _pickdir_modern.py <输出文件> [初始目录]
取消时写入空串；任何失败都写空串（调用方可回退旧实现）。
"""
import sys
import io
import ctypes
from ctypes import wintypes


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


def _guid(s):
    import uuid
    u = uuid.UUID(s)
    g = GUID()
    g.Data1 = u.time_low
    g.Data2 = u.time_mid
    g.Data3 = u.time_hi_version
    g.Data4 = (ctypes.c_ubyte * 8)(*u.bytes[8:])
    return g


CLSID_FileOpenDialog = _guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")
IID_IFileOpenDialog = _guid("d57c7288-d4ad-4768-be02-9d969532d960")
IID_IShellItem = _guid("43826d1e-e718-42ee-bc55-a1e261c37bfe")

CLSCTX_INPROC_SERVER = 0x1
COINIT_APARTMENTTHREADED = 0x2

FOS_PICKFOLDERS = 0x00000020
FOS_FORCEFILESYSTEM = 0x00000040
FOS_PATHMUSTEXIST = 0x00000800

SIGDN_FILESYSPATH = 0x80058000

# IFileDialog vtable 索引（0=QueryInterface,1=AddRef,2=Release 之后）
IDX_SHOW = 3
IDX_SET_OPTIONS = 9
IDX_GET_OPTIONS = 10
IDX_SET_FOLDER = 12
IDX_SET_TITLE = 17
IDX_GET_RESULT = 20


def _vtbl(punk, index, restype, *argtypes):
    vt = ctypes.cast(punk, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(vt[index])


def _release(punk):
    try:
        _vtbl(punk, 2, ctypes.c_ulong)(punk)
    except Exception:
        pass


def pick_dir(init_dir=""):
    """返回 (路径, 状态)。
    状态: 'ok' 选中 / 'cancel' 用户取消 / 'fail' 实现不可用（调用方应回退旧实现）"""
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32
    try:
        ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    except Exception:
        pass
    pfd = ctypes.c_void_p()
    psi = ctypes.c_void_p()
    psf = ctypes.c_void_p()
    try:
        ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(GUID),
                                           ctypes.POINTER(ctypes.c_void_p)]
        hr = ole32.CoCreateInstance(ctypes.byref(CLSID_FileOpenDialog), None,
                                    CLSCTX_INPROC_SERVER,
                                    ctypes.byref(IID_IFileOpenDialog),
                                    ctypes.byref(pfd))
        if hr != 0 or not pfd:
            return "", "fail"

        opts = ctypes.c_uint(0)
        if _vtbl(pfd, IDX_GET_OPTIONS, ctypes.HRESULT,
                 ctypes.POINTER(ctypes.c_uint))(pfd, ctypes.byref(opts)) != 0:
            return "", "fail"
        newopts = opts.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
        if _vtbl(pfd, IDX_SET_OPTIONS, ctypes.HRESULT, ctypes.c_uint)(pfd, newopts) != 0:
            return "", "fail"

        try:
            _vtbl(pfd, IDX_SET_TITLE, ctypes.HRESULT, wintypes.LPCWSTR)(
                pfd, "选择保存目录")
        except Exception:
            pass

        if init_dir:
            try:
                if shell32.SHCreateItemFromParsingName(
                        ctypes.c_wchar_p(init_dir), None,
                        ctypes.byref(IID_IShellItem), ctypes.byref(psi)) == 0 and psi:
                    _vtbl(pfd, IDX_SET_FOLDER, ctypes.HRESULT, ctypes.c_void_p)(
                        pfd, psi)
            except Exception:
                pass

        owner = 0
        try:
            owner = user32.GetForegroundWindow() or 0
        except Exception:
            pass
        # Show() 返回非 0 表示用户取消 —— 属于正常路径，不是"实现不可用"
        if _vtbl(pfd, IDX_SHOW, ctypes.HRESULT, ctypes.c_void_p)(
                pfd, ctypes.c_void_p(owner)) != 0:
            return "", "cancel"

        if _vtbl(pfd, IDX_GET_RESULT, ctypes.HRESULT,
                 ctypes.POINTER(ctypes.c_void_p))(pfd, ctypes.byref(psf)) != 0:
            return "", "fail"
        if not psf:
            return "", "fail"
        path_ptr = ctypes.c_wchar_p()
        if _vtbl(psf, 5, ctypes.HRESULT, ctypes.c_uint,
                 ctypes.POINTER(ctypes.c_wchar_p))(psf, SIGDN_FILESYSPATH,
                                                  ctypes.byref(path_ptr)) != 0:
            return "", "fail"
        out = path_ptr.value or ""
        try:
            ole32.CoTaskMemFree(ctypes.cast(path_ptr, ctypes.c_void_p))
        except Exception:
            pass
        return out, "ok"
    except Exception:
        return "", "fail"
    finally:
        if psf:
            _release(psf)
        if psi:
            _release(psi)
        if pfd:
            _release(pfd)
        try:
            ole32.CoUninitialize()
        except Exception:
            pass


try:
    init = sys.argv[2] if len(sys.argv) > 2 else ""
    path, status = pick_dir(init)
except Exception:
    path, status = "", "fail"
try:
    if status == "ok":
        io.open(sys.argv[1], "w", encoding="utf-8").write(path or "")
    elif status == "cancel":
        io.open(sys.argv[1], "w", encoding="utf-8").write("@CANCEL@")
    else:
        # 留空 -> 调用方据此回退旧实现
        pass
except Exception:
    pass
