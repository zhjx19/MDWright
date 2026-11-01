# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""
MD 编辑器启动器（无控制台窗口）
Explorer 右键 / 双击传入 .md 路径时：
1. 端口空闲 → 拉起 md_server.py
2. 端口占用 → 校验服务版本：匹配则复用；不匹配（旧版本服务）则
   清掉旧服务进程后自行拉起最新版（自愈换代，用户无感）
3. 通知后端打开浏览器到对应 ?file= 页面

多开：**不做窗口互斥**。每个打开的 .md 得到自己的内嵌窗口/浏览器标签，
共享同一个本地服务，各自独立关闭（后端只在所有窗口都关闭后自动退出，
由 md_server 的按会话看门狗判定）。版本换代仅当服务版本不匹配时执行，
不影响正常多开。
"""
import sys
import os
import json
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import webbrowser

PORT = 18766
HERE = os.path.dirname(os.path.abspath(__file__))
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def _read_server_version(default=11):
    """从 md_server.py 里读版本号，不 import 它。

    启动器只需要一个整数，为此导入 150KB 的 md_server（连同 md_runs / llm_client /
    rag_client / web_search）要多花约 0.1s 与 20MB 内存，纯属白付。版本常量由
    md_server 单一维护，这里只做只读解析；解析不到就退回默认值（与旧行为一致）。
    """
    try:
        with open(os.path.join(HERE, "md_server.py"), "r",
                  encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("MD_SERVER_VERSION"):
                    return int(line.split("=", 1)[1].split("#")[0].strip())
    except Exception:
        pass
    return default


VERSION = _read_server_version()


def port_open():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # 0.3s 太长：本机未监听端口是 drop 而非 RST，每次冷启动都要把超时等满
    # （实测 310ms）。监听中的端口在 loopback 上握手是亚毫秒级，100ms 足够。
    s.settimeout(0.1)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


def server_version(timeout=0.3):
    """端口上服务的版本号；无 /api/version（旧版）或连接失败返回 None。
    默认 0.3s：这是「决定要不要换代」的判据，宁可慢也不能把响应稍慢的
    正常服务误判成旧版。wait_version 传更短的超时——那一支已经确定服务
    是我们刚拉起的，探测失败只是「还没起来」，重试即可。"""
    try:
        r = urllib.request.urlopen(
            "http://127.0.0.1:%d/api/version" % PORT, timeout=timeout)
        return json.loads(r.read().decode("utf-8")).get("version", 0)
    except Exception:
        return None


def start_server():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    subprocess.Popen(
        [sys.executable, os.path.join(HERE, "_md_run.py")],
        startupinfo=si,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _list_pythonw_cmdlines():
    """列出 (pid, commandline)；wmic 不可用时退回 PowerShell CIM。"""
    # 用绝对路径，避免目标机 PATH 缺 WindowsPowerShell 子目录时 powershell 解析不到
    pwsh = os.path.join(
        os.environ.get("SystemRoot", os.environ.get("WINDIR", "C:\\Windows")),
        "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    cmds = [
        ["wmic", "process", "where", "name='pythonw.exe'", "get",
         "ProcessId,CommandLine", "/format:csv"],
        [pwsh, "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"name='pythonw.exe'\" | "
         "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }"],
    ]
    for c in cmds:
        try:
            r = subprocess.run(c, capture_output=True, text=True,
                               errors="replace", creationflags=NO_WINDOW)
            out = r.stdout or ""
            if out.strip():
                return out
        except Exception:
            continue
    return ""



def kill_stale_services():
    """清掉本目录的旧 md_server（按完整路径精确匹配，不误伤其它 pythonw 脚本）
    兼容两种启动方式：直跑 md_server.py（旧）与 _md_run.py shim（新）"""
    me = os.getpid()
    marks = [os.path.join(HERE, n).replace("\\", "/").lower()
             for n in ("md_server.py", "_md_run.py")]
    killed = []
    for ln in _list_pythonw_cmdlines().splitlines():
        low = ln.replace("\\", "/").lower()
        if not any(m in low for m in marks):
            continue
        parts = [p for p in ln.replace("|", ",").split(",") if p.strip()]
        if not parts:
            continue
        pid = parts[-1].strip()
        if pid.isdigit() and int(pid) != me:
            try:
                subprocess.run(["taskkill", "/F", "/PID", pid],
                               creationflags=NO_WINDOW,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
                killed.append(pid)
            except Exception:
                pass
    return killed


def kill_port_holder():
    """兜底：杀掉占用本服务端口的进程（服务可能不是以 pythonw 启动的）。"""
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                           errors="replace", creationflags=NO_WINDOW)
        me = os.getpid()
        for ln in (r.stdout or "").splitlines():
            if ":%d " % PORT not in ln or "LISTENING" not in ln.upper():
                continue
            pid = ln.split()[-1].strip()
            if pid.isdigit() and int(pid) != me:
                subprocess.run(["taskkill", "/F", "/PID", pid],
                               creationflags=NO_WINDOW,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    except Exception:
        pass


def wait_version(timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        # 0.1s：这一支只用于「刚拉起/刚换代」后等就绪，探测失败=还没起来，
        # 立刻重试即可；本机未监听端口会把短超时等满，0.3s 会让就绪感知白晚 0.2s。
        if server_version(timeout=0.1) == VERSION:
            return True
        time.sleep(0.05)
    return False


def open_in_browser(path):
    q = ("?file=" + urllib.parse.quote(path)) if path else ""
    try:
        urllib.request.urlopen(
            "http://127.0.0.1:%d/open%s" % (PORT, q), timeout=8).read()
    except urllib.error.URLError:
        # 仅在“连不上服务”时兜底；HTTP 状态错误/超时不重复打开
        sep = "&" if q else "?"
        webbrowser.open("http://127.0.0.1:%d/%sv=%d" % (PORT, q and (q + sep) or (sep), VERSION))
    except Exception:
        pass


_splash_proc = None


def load_settings():
    """读取 runtime/settings.json（缺失/损坏时用默认值）"""
    defaults = {"embed_window": True, "disable_gpu": False}
    try:
        p = os.path.join(HERE, "runtime", "settings.json")
        d = json.loads(open(p, encoding="utf-8").read())
        if isinstance(d, dict):
            defaults.update({k: d[k] for k in defaults if k in d})
    except Exception:
        pass
    return defaults


def embedded_available():
    """内嵌模式可用性：有 md_app.pyw，且（自带内核 或 系统 WebView2）存在。"""
    if not os.path.exists(os.path.join(HERE, "md_app.pyw")):
        return False
    if os.path.exists(os.path.join(HERE, "runtime", "WebView2", "msedgewebview2.exe")):
        return True
    # 系统 WebView2 Runtime
    for p in (r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application",
              r"C:\Program Files\Microsoft\EdgeWebView\Application"):
        try:
            if os.path.isdir(p) and any(d[0].isdigit() for d in os.listdir(p)):
                return True
        except Exception:
            pass
    return False


def launch_embedded(path=None, service_started_by_us=False):
    """尝试用内嵌窗口打开；成功返回 True。"""
    if not embedded_available():
        return False
    exe = os.path.join(HERE, "python", "pythonw.exe")
    if not os.path.exists(exe):
        exe = sys.executable
    args = [exe, os.path.join(HERE, "md_app.pyw")]
    if path:
        args.append(path)
    env = dict(os.environ)
    if service_started_by_us:
        # 告诉 md_app「服务已经由启动器拉起，你只管等」——否则两边同时 spawn，
        # Windows 的 SO_REUSEADDR 会让两个服务绑同一个端口。
        env["MDW_LAUNCH_SPAWNED"] = "1"
    try:
        subprocess.Popen(args, cwd=HERE, creationflags=0x08000000, env=env)
        return True
    except Exception:
        return False


def start_splash(hold_seconds=25):
    """启动画面（独立子进程）。真实启动完成后由 close_splash() 淡出，
    hold_seconds 只是兜底上限。"""
    here = os.path.dirname(os.path.abspath(__file__))
    sp = os.path.join(here, "_splash.py")
    if not os.path.exists(sp):
        return
    exe = os.path.join(here, "python", "python.exe")
    if not os.path.exists(exe):
        exe = sys.executable
    global _splash_proc
    try:
        _splash_proc = subprocess.Popen([exe, sp, "", str(hold_seconds),
                                         str(PORT), str(VERSION)],
                                        cwd=here, creationflags=0x08000000)
    except Exception:
        _splash_proc = None


def close_splash():
    """给启动画面窗口发 WM_CLOSE，让它淡出退出。
    兜底终止放后台线程：淡出动画不阻塞主流程（开浏览器不等它）。"""
    try:
        import ctypes
        u = ctypes.windll.user32
        u.FindWindowW.restype = ctypes.c_void_p
        u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        u.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                   ctypes.c_size_t, ctypes.c_ssize_t]
        h = u.FindWindowW("MDWrightSplash2", None)
        if h:
            u.PostMessageW(ctypes.c_void_p(h), 0x0010, 0, 0)
    except Exception:
        pass
    # 后台兜底：淡出未完成则直接终止进程（不占主线程）
    global _splash_proc
    sp, _splash_proc = _splash_proc, None
    if sp is not None:
        def _reap():
            try:
                sp.wait(timeout=2.0)
            except Exception:
                try:
                    sp.terminate()
                except Exception:
                    pass
        try:
            threading.Thread(target=_reap, daemon=True).start()
        except Exception:
            pass


def open_ui(path, service_started_by_us=False):
    """开窗口；内嵌不可用时退回浏览器。"""
    st = load_settings()
    if st.get("embed_window") and launch_embedded(path, service_started_by_us):
        return True
    open_in_browser(path)
    return False


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    # 不互斥窗口：多开的每个窗口独立打开对应文件；页面 no-store，
    # 新窗口必然加载当前代码。服务仅版本不匹配时换代。
    if port_open():
        if server_version() == VERSION:
            open_ui(path)   # 版本匹配，直接复用（服务已在跑，窗口立刻起）
            return
        # 旧版服务占着端口：自愈换代。这一支保持串行——先杀掉旧服务、等新服务就绪，
        # 再开窗口，避免窗口连到正在被替换的服务上。
        start_splash()
        kill_stale_services()
        kill_port_holder()
        time.sleep(0.6)
        start_server()
        if not wait_version():
            close_splash()
            open_in_browser(path)  # 兜底：至少把页面打开
            return
        open_ui(path, service_started_by_us=True)
        return

    # 全新启动：服务与窗口并行。原先是「等服务就绪 → 再起 WebView2」串行，
    # 两段各约 0.7s；并行后窗口创建（pythonw + pywebview 导入 + WebView2 初始化）
    # 与服务启动同时进行，关键路径少一段。
    start_splash()
    start_server()
    st = load_settings()
    embedded = False
    if st.get("embed_window"):
        embedded = launch_embedded(path, service_started_by_us=True)
    if not wait_version():
        close_splash()
        open_in_browser(path)  # 兜底：服务没起来也至少把页面打开
        return
    if not embedded:
        open_in_browser(path)
    # 内嵌成功时 splash 不在这里关：由它自己轮询「页面会话上线」后淡出，
    # 服务就绪 ≠ 窗口可见，中间那段 WebView2 冷启动空档正是它该覆盖的。


if __name__ == "__main__":
    main()
