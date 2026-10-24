# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""浏览器级测试脚手架（R1 新增，替代本机未安装的 playwright）：
起本地服务 + headless 浏览器，经 CDP 在页面里求值 JS，取回 JSON 结果。

- 零安装：Node 24 内置 WebSocket 直连 Chrome/Edge 调试端口（实现见 _cdp.js）
- 端口 18777（与既有 18766 隔离，可并行）
- CDP 调试端口运行时探测空闲口（socket 绑 0），避免上次测试残留 chrome 进程
  造成端口冲突或误连旧实例
"""
# --- 测试入口 shim：本文件在 tests/ 下。便携运行时（python311._pth）不会把 script dir
# 加进 sys.path，所以 tests/ 与仓库根两个都显式挂上，跨用例 import 与根模块 import 才成立 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

# Windows 控制台默认 GBK，DOM 里可能含 GBK 外字符（如脚注回链 ↩）。
# 统一把 stdout 改成 UTF-8 + replace，避免测试因「打印」而失败。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
PORT = 18777

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser():
    """定位本机 Chromium 内核浏览器；找不到返回 None。"""
    for b in BROWSERS:
        if os.path.exists(b):
            return b
    return None


def port_in_use(port):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def free_port():
    """取一个当前空闲的本地端口（绑定 0 后立刻释放，交给 chrome 用）。"""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def start_server(port=PORT):
    """起一个进程内 md_server；端口已被占用则复用现有服务。"""
    if port_in_use(port):
        return None
    sys.argv = ["md_server.py"]
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import md_server
    httpd = md_server.ReuseTCPServer(("127.0.0.1", port), md_server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    return httpd


class Browser(object):
    """headless 浏览器 + CDP 求值通道。"""

    def __init__(self):
        exe = find_browser()
        if not exe:
            raise RuntimeError("no chromium browser found")
        self.port = free_port()
        self.prof = tempfile.mkdtemp(prefix="mdcdp-")
        self.proc = subprocess.Popen(
            [exe, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--remote-debugging-port=%d" % self.port,
             "--user-data-dir=%s" % self.prof, "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # 等调试端口真的能应答（chrome 冷启动 1~2s）
        for _ in range(150):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/json/version" % self.port,
                                       timeout=1).read()
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("devtools port %d never came up" % self.port)

    def eval(self, expr, url="http://127.0.0.1:%d/?file=" % PORT):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as f:
            f.write(expr)
            path = f.name
        try:
            r = subprocess.run(["node", os.path.join(_ROOT, "tests", "_cdp.js"),
                                str(self.port), url, path],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        finally:
            if os.path.exists(path):
                os.remove(path)
        if r.returncode != 0:
            raise RuntimeError("cdp failed: " + (r.stderr or r.stdout or "")[:500])
        lines = [ln for ln in (r.stdout or "").strip().splitlines() if ln.strip()]
        if not lines:
            raise RuntimeError("cdp produced no output")
        return json.loads(lines[-1])

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def run_expr(expr, url="http://127.0.0.1:%d/?file=" % PORT, port=PORT):
    """一次性：起服务 + 浏览器 → 求值 → 关停。

    URL 默认带 ?file=（空路径）：前端据此跳过「加载默认文档」，
    否则测试会打开使用指南并因改内容触发批注剪枝 → 把作者的
    annotations.json 清空写回磁盘（真实踩过一次）。
    """
    httpd = start_server(port)
    b = Browser()
    try:
        return b.eval(expr, url)
    finally:
        b.close()
        if httpd:
            httpd.shutdown()
            httpd.server_close()   # 必须 close，否则监听端口残留，下次起服务失败


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        got = run_expr("document.title")
        print("SELFTEST title=%r" % (got,))
        sys.exit(0 if got else 1)
    print(__doc__)
