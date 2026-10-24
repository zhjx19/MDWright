# -*- coding: utf-8 -*-
"""批注 .smd 往返：另存为 .smd → 写批注 → 验证入包 → 重新读取。"""
# --- 测试入口 shim：本文件在 tests/ 下。便携运行时（python311._pth）不会把 script dir
# 加进 sys.path，所以 tests/ 与仓库根两个都显式挂上，跨用例 import 与根模块 import 才成立 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import io
import json
import os
import sys
import shutil
import threading
import time
import zipfile
import urllib.request
import urllib.parse

BASE = "http://127.0.0.1:18766"

# 自己起一份后端（原本假定本机已有实例在 18766 上跑，没开就只能是“连接被拒”）
sys.argv = ["md_server.py"]
import md_server                                              # noqa: E402
httpd = md_server.ReuseTCPServer(("127.0.0.1", 18766), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

D = os.path.join(os.environ.get("TEMP", "/tmp"), "mda_smd_test")
shutil.rmtree(D, ignore_errors=True)
os.makedirs(D)

fails = []


def check(name, cond, detail=""):
    print("%-28s %s %s" % (name, "PASS" if cond else "FAIL", "" if cond else detail))
    if not cond:
        fails.append(name)


def call(path, method="GET", body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


try:
    content = "# smd 批注测试\n\n一段包含可标注文本的正文内容，用于验证批注写入 smd 包。\n"
    j = call("/api/save-as", "POST", {"dir": D, "name": "smd批注.smd", "content": content})
    check("save-as .smd ok", j.get("ok") is True, str(j)[:200])
    p = j["path"]

    ann = [{"id": "s1", "text": "可标注文本", "note": "smd 内批注", "created": 1, "updated": 2}]
    j = call("/api/annotations", "POST", {"path": p, "annotations": ann})
    check("annotations POST smd", j.get("ok") is True, str(j)[:200])

    with zipfile.ZipFile(p, "r") as z:
        names = z.namelist()
        check("annotations.json in package", "assets/annotations.json" in names, str(names))
        if "assets/annotations.json" in names:
            in_pkg = json.loads(z.read("assets/annotations.json").decode("utf-8"))
            check("package content correct", in_pkg == ann, str(in_pkg)[:200])

    j = call("/api/annotations?path=" + urllib.parse.quote(p, safe=""))
    check("annotations GET smd", j.get("ok") and j.get("annotations") == ann, str(j)[:200])

    # 再保存一次正文（触发 save_from_dir 增量）→ 批注仍在包内
    j = call("/api/file", "POST", {"path": p, "content": content + "\n新增一行。\n"})
    check("doc save on smd", j.get("ok") is True, str(j)[:200])
    with zipfile.ZipFile(p, "r") as z:
        names = z.namelist()
        check("annotations survive resave", "assets/annotations.json" in names, str(names))

    # 全量整理（compact）路径也保留
    sys.path.insert(0, _ROOT)   # 同 shim，保留此行以免与旧习惯冲突
    import _smd
    base = _smd.base_dir_for(p)
    _smd.compact(p, base)
    with zipfile.ZipFile(p, "r") as z:
        names = z.namelist()
        check("annotations survive compact", "assets/annotations.json" in names, str(names))
finally:
    shutil.rmtree(D, ignore_errors=True)

print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
sys.exit(1 if fails else 0)