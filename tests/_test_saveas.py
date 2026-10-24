# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""另存为的落盘边界：

- 不允许写进安装目录（升级会覆盖用户文档；首次另存为时对话框以进程工作目录为起点，
  不拦住就会把稿子存进 `D:\\Program Files\\MDWright`）；
- 文件名必须是**裸文件名**（带路径/盘符的名字会被 os.path.join 当成绝对路径，
  表现为"文件名多了个 D:"）；
- 正常目录照常写。
"""
# --- 测试入口 shim ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.argv = ["md_server.py"]
import md_server  # noqa: E402

PORT = 18793
httpd = md_server.ReuseTCPServer(("127.0.0.1", PORT), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)
fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


def post(obj):
    req = urllib.request.Request("http://127.0.0.1:%d/api/save-as" % PORT,
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8")), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


def main():
    tmp = tempfile.mkdtemp(prefix="mdsaveas-")
    try:
        # 目录规范化：盘符根不能变成"该盘当前目录"
        check("D: 规范化为 D:\\",
              md_server._norm_save_dir("D:") == "D:" + os.sep,
              repr(md_server._norm_save_dir("D:")))
        check("D:\\ 保持为 D:\\",
              md_server._norm_save_dir("D:\\") == "D:" + os.sep,
              repr(md_server._norm_save_dir("D:\\")))
        check("普通目录去尾斜杠",
              md_server._norm_save_dir(tmp + os.sep) == os.path.normpath(tmp),
              repr(md_server._norm_save_dir(tmp + os.sep)))
        check("盘符根不算安装目录",
              md_server._is_install_dir(md_server._norm_save_dir("D:")) is False
              or os.path.realpath("D:" + os.sep) == os.path.realpath(md_server.HERE),
              repr(md_server._norm_save_dir("D:")))
        check("安装目录被识别为安装目录",
              md_server._is_install_dir(md_server.HERE) is True, "")

        # 正常目录：照常写
        j, code = post({"dir": tmp, "name": "ok.md", "content": "# hi\n"})
        check("正常目录可以保存", code == 200 and j.get("ok") is True, str(j)[:160])
        check("文件真的落盘", os.path.isfile(os.path.join(tmp, "ok.md")), "")

        # 安装目录：拒绝，且不产生文件
        j2, code2 = post({"dir": md_server.HERE, "name": "evil.md", "content": "x"})
        check("拒绝写进安装目录", code2 == 400 and "安装目录" in (j2.get("error") or ""),
              "%s %s" % (code2, str(j2)[:160]))
        check("安装目录里没有产生文件",
              not os.path.isfile(os.path.join(md_server.HERE, "evil.md")), "")

        # 带盘符/路径的文件名：拒绝（不许把路径当名字）
        for bad in ("D:\\x.md", "sub/x.md", "C:y.md"):
            jb, cb = post({"dir": tmp, "name": bad, "content": "x"})
            check("拒绝带路径的文件名 %r" % bad,
                  cb == 400 and "文件名" in (jb.get("error") or ""),
                  "%s %s" % (cb, str(jb)[:120]))
        check("这些名字没有偷偷落到别处",
              not any(os.path.isfile(os.path.join(tmp, n))
                      for n in ("x.md", "sub", "y.md")), "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        httpd.shutdown()
        httpd.server_close()

    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
