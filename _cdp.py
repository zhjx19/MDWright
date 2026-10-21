# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""最小 CDP 客户端（纯标准库）：让 headless 浏览器「等分页完成再打印」。

为什么不能用 CLI 两趟法：`--dump-dom` + `--print-to-pdf` 是两次独立加载，
分页（Paged.js 异步 chunker）与 dump 时刻之间的竞态无法从外部消除。实测同一
URL、同一 profile 连续 6 次 dump，页数依次是 2/0/1/0/3/1——按这个口径判断
「页数稳定」既会误判完成，也会误判未完成，最终产出半截 PDF。

CDP 的价值是：**同一个会话里**可以轮询页面状态（`data-paged-done`，由页码
填充脚本在页数连续稳定后写入），确认后再调 `Page.printToPDF`，中间没有任何
二次加载。

只实现打印需要的最小子集：WebSocket 握手 + 文本帧收发 + 按 id 匹配响应。
"""
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class CDPError(Exception):
    pass


def _read_http_headers(sock):
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise CDPError("websocket handshake: connection closed")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head.decode("latin-1"), rest


class WebSocket(object):
    def __init__(self, host, port, path):
        self.sock = socket.create_connection((host, port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n" % (path, host, port, key))
        self.sock.sendall(req.encode("latin-1"))
        head, self.buf = _read_http_headers(self.sock)
        if " 101 " not in head.split("\r\n")[0]:
            raise CDPError("websocket handshake failed: %s" % head.split("\r\n")[0])

    # ---- 帧 ----
    def send(self, text):
        data = text.encode("utf-8")
        header = bytearray([0x81])                      # FIN + text
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv_exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise CDPError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        """返回一条完整文本消息；遇到 close 返回 None；ping 自动回 pong。"""
        payload = b""
        while True:
            b1, b2 = self._recv_exact(2)
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            data = self._recv_exact(n)
            if masked:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:
                return None
            if opcode == 0x9:                            # ping → pong
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if opcode == 0xA:                            # pong
                continue
            payload += data
            if fin:
                return payload.decode("utf-8", errors="replace")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class CDP(object):
    def __init__(self, ws_url):
        # ws://127.0.0.1:PORT/devtools/page/XXXX
        rest = ws_url.split("://", 1)[1]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.ws = WebSocket(host, int(port), "/" + path)
        self._id = 0

    def cmd(self, method, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = self.ws.recv()
            if msg is None:
                raise CDPError("websocket closed during %s" % method)
            obj = json.loads(msg)
            if obj.get("id") == mid:
                if "error" in obj:
                    raise CDPError("%s: %s" % (method, obj["error"]))
                return obj.get("result", {})

    def close(self):
        self.ws.close()


def _devtools_port(user_data_dir, timeout=20.0):
    """Chrome 以 --remote-debugging-port=0 启动后把实际端口写进 DevToolsActivePort。"""
    p = os.path.join(user_data_dir, "DevToolsActivePort")
    end = time.time() + timeout
    while time.time() < end:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    first = f.readline().strip()
                if first.isdigit():
                    return int(first)
            except Exception:
                pass
        time.sleep(0.1)
    raise CDPError("DevToolsActivePort 未出现（浏览器可能启动失败）")


def _json_list(port, timeout=10.0):
    import urllib.request
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port,
                                        timeout=2) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            time.sleep(0.1)
    raise CDPError("/json/list 不可达")


def print_pdf(url, out_pdf, browser, wait_timeout=90.0, poll=0.2):
    """打开 url，等 `data-paged-done="1"`，再 printToPDF 落盘。

    返回 PDF 页数；失败抛 CDPError（调用方据此给用户明确提示，且不落半截文件）。
    """
    prof = tempfile.mkdtemp(prefix="mdeditor-cdp-")
    proc = subprocess.Popen([browser, "--headless=new", "--disable-gpu", "--no-sandbox",
                             "--remote-debugging-port=0",
                             "--user-data-dir=" + prof, "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=_NO_WINDOW)
    cdp = None
    try:
        port = _devtools_port(prof)
        targets = _json_list(port)
        page = next((t for t in targets if t.get("type") == "page"), None)
        if not page:
            raise CDPError("没有可用的 page target")
        cdp = CDP(page["webSocketDebuggerUrl"])
        cdp.cmd("Page.enable")
        cdp.cmd("Runtime.enable")
        cdp.cmd("Page.navigate", url=url)
        end = time.time() + wait_timeout
        while time.time() < end:
            r = cdp.cmd("Runtime.evaluate",
                        expression="document.documentElement.getAttribute('data-paged-done')"
                                   "==='1'",
                        returnByValue=True)
            if r.get("result", {}).get("value") is True:
                break
            time.sleep(poll)
        else:
            raise CDPError("分页超时（%ds）：Paged.js 未在限定时间内完成" % int(wait_timeout))

        n = cdp.cmd("Runtime.evaluate",
                    expression="document.querySelectorAll('.pagedjs_page').length",
                    returnByValue=True).get("result", {}).get("value") or 0
        if not n:
            raise CDPError("分页结果为 0 页")

        res = cdp.cmd("Page.printToPDF", printBackground=True, preferCSSPageSize=True,
                      marginTop=0, marginBottom=0, marginLeft=0, marginRight=0,
                      displayHeaderFooter=False)
        data = base64.b64decode(res.get("data") or "")
        if not data.startswith(b"%PDF-"):
            raise CDPError("printToPDF 返回的不是 PDF")
        with open(out_pdf, "wb") as f:
            f.write(data)
        return n
    finally:
        if cdp:
            cdp.close()
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        import shutil
        shutil.rmtree(prof, ignore_errors=True)
