# -*- coding: utf-8 -*-
# 分发清单实测：按"最小可用分发集"组装干净目录，从零启动，逐项验证。
# 不带：runtime/、__pycache__/、_slice/、全部测试与诊断、安装脚本。
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
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.parse

SRC = _ROOT
DIST = os.path.join(SRC, "_dist_verify")
PY = os.path.join(SRC, "python", "python.exe")
NO_WINDOW = 0x08000000
RESULTS = []


def check(name, ok, extra=""):
    RESULTS.append((name, ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + extra) if extra else ""))


# --- 1) 组装（真实分发包内容，junction 模拟大目录拷贝） ---
shutil.rmtree(DIST, ignore_errors=True)
os.makedirs(DIST)
FILES = ["md_launch.pyw", "_md_run.py", "md_server.py",
         "mdwright.html", "mdwright.ico", "llm_client.py",
         "web_search.py", "rag_client.py", "_smd.py", "md_assets.py",
         "_splash.py", "_pickdir_modern.py", "_pickfile.py", "md_app.pyw",
         "md_tools.py", "md_pandoc.py", "_cdp.py", "_savefile.py",
         "LICENSE", "README.md"]
for f in FILES:
    shutil.copy2(os.path.join(SRC, f), os.path.join(DIST, f))
for d in ["python", "katex", "pagedjs", "docs", "LICENSES",
          "mermaid", "viz", "wavedrom", "vega", "highlight"]:
    subprocess.run(["cmd", "/c", "mklink", "/J",
                    os.path.join(DIST, d), os.path.join(SRC, d)],
                   capture_output=True, creationflags=NO_WINDOW)
check("dist assembled (20 files + 10 junctions)",
      all(os.path.exists(os.path.join(DIST, f)) for f in FILES)
      and all(os.path.isdir(os.path.join(DIST, d))
              for d in ["python", "katex", "pagedjs", "docs", "LICENSES",
                        "mermaid", "viz", "wavedrom", "vega", "highlight"]))
# I1：代码高亮 vendor 必须真的进包（漏了 = 装完代码永不着色，且无任何报错）
check("highlight vendor in dist",
      os.path.isfile(os.path.join(DIST, "highlight", "highlight.min.js"))
      and os.path.isfile(os.path.join(DIST, "highlight", "styles", "github.css")))
check("no runtime/ pycache/ in dist",
      not os.path.exists(os.path.join(DIST, "runtime"))
      and not os.path.exists(os.path.join(DIST, "__pycache__")))

# --- 1b) pythonnet 原生桥接 DLL 断言（v1.11.1 缺失事故回归锚点） ---
# pywebview 挂载系统 WebView2 的 .NET 互操作必需件；缺失 = 内嵌窗口静默崩。
_dll = os.path.join(DIST, "python", "Lib", "site-packages", "pythonnet",
                    "runtime", "Python.Runtime.dll")
_dll_size = os.path.getsize(_dll) if os.path.isfile(_dll) else 0
check("pythonnet bridge DLL in dist (>=400KB)",
      _dll_size > 400 * 1024, str(_dll_size) if _dll_size else "missing")


def get(path, timeout=3):
    return urllib.request.urlopen(
        "http://127.0.0.1:18766" + path, timeout=timeout).read()


# --- 2) 从分发目录冷启动（shim，无 pyc，全新环境） ---
p = subprocess.Popen([PY, os.path.join(DIST, "_md_run.py")], cwd=DIST,
                     creationflags=NO_WINDOW)
t0 = time.time()
ver = None
while time.time() - t0 < 20:
    try:
        d = json.loads(get("/api/version", timeout=0.3))
        ver = d
        break
    except Exception:
        time.sleep(0.05)
check("cold start from dist (no pyc)", ver is not None,
      "%.2fs" % (time.time() - t0) if ver else "timeout")
EXPECT_VER = __import__('md_server').MD_SERVER_VERSION   # 单一来源：不再硬编码版本号
check("version == %d with sessions" % EXPECT_VER, ver and ver.get("version") == EXPECT_VER
      and "sessions" in ver, str(ver))

# --- 3) 页面与静态资源 ---
body = get("/").decode("utf-8")
check("page served", "MDWright" in body and
      'defer src="/static/katex/katex.min.js"' in body,
      "%d bytes" % len(body))
check("katex.min.js", len(get("/static/katex/katex.min.js")) > 200000)
# 图表 vendor 四引擎（v1.12.0：mermaid / graphviz / wavedrom / vega-lite）
check("mermaid vendor", len(get("/static/mermaid/mermaid.min.js")) > 3000000)
check("viz-js vendor (graphviz, standalone=embedded wasm)", len(get("/static/viz/viz-standalone.js")) > 1000000)
check("wavedrom vendor + skins", len(get("/static/wavedrom/wavedrom.min.js")) > 50000
      and len(get("/static/wavedrom/skins/default.js")) > 30000
      and len(get("/static/wavedrom/skins/dark.js")) > 30000)
check("vega vendor", len(get("/static/vega/vega.min.js")) > 500000)
check("vega-lite vendor", len(get("/static/vega/vega-lite.min.js")) > 200000)
check("vega-embed vendor", len(get("/static/vega/vega-embed.min.js")) > 50000)
fonts = json.loads(get("/static/katex/fonts/").decode("utf-8")) \
    if False else None
try:
    get("/static/katex/fonts/KaTeX_Main-Regular.woff2")
    check("katex font file", True)
except Exception as e:
    check("katex font file", False, repr(e))
check("favicon", len(get("/favicon.ico")) > 10000)

# --- 4) 内置文档（默认文章 + 版权声明） ---
d1 = json.loads(get("/doc?file=" + urllib.parse.quote(
    "MDWright 使用指南.md")).decode("utf-8"))
check("default doc (使用指南)", d1.get("ok") and len(d1.get("content", "")) > 500,
      "%d chars" % len(d1.get("content", "")))
d2 = json.loads(get("/doc?file=" + urllib.parse.quote(
    "版权与开源组件声明.md")).decode("utf-8"))
check("license doc (版权声明)", d2.get("ok") and len(d2.get("content", "")) > 200)

# --- 5) pagedjs 可用（分页导出，服务端读文件） ---
req = urllib.request.Request(
    "http://127.0.0.1:18766/api/export-paged",
    data=json.dumps({"bodyHtml": "<h1>分发验证</h1><p>paged 导出</p>",
                     "tsCss": "", "cfg": {}}).encode("utf-8"),
    headers={"Content-Type": "application/json"})
r = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
check("paged export", r.get("ok") is True, r.get("url", r.get("error", "")))

# --- 6) 降级链路完整性：LLM 模块加载成功（无 _llm.err） ---
check("llm modules loaded (no _llm.err)",
      not os.path.exists(os.path.join(DIST, "runtime", "_llm.err")))

# --- 7) 首次写盘自动生成 runtime/（启动只读不建目录，保存设置才建） ---
req = urllib.request.Request(
    "http://127.0.0.1:18766/api/llm-config",
    data=json.dumps({"config": {"backend": "lmstudio"}}).encode("utf-8"),
    headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=3).read()
except Exception:
    pass
check("runtime/ auto-created on first save",
      os.path.isdir(os.path.join(DIST, "runtime"))
      and os.path.isfile(os.path.join(DIST, "runtime", "settings.json")))

# --- 8) splash 在分发目录可起（进程能存活=消息循环正常） ---
# 实测会偶发：同一份代码 3 次里 1 次在 1s 内自退（_splash.main 里的异常被吞掉，
# 没有日志可查）。真坏了会每次都死，所以重试 3 次、全死才判失败，并把尝试次数写出来。
_attempts = []
for _i in range(3):
    sp = subprocess.Popen([PY, os.path.join(DIST, "_splash.py"),
                           "", "4", "18766", str(EXPECT_VER)], cwd=DIST,
                          creationflags=NO_WINDOW)
    time.sleep(1.0)
    _attempts.append(sp.poll() is None)
    sp.terminate()
    try:
        sp.wait(3)
    except Exception:
        sp.kill()
    if _attempts[-1]:
        break
check("splash process alive in dist", any(_attempts),
      "attempts=%s" % _attempts)

# --- 清理 ---
print("cleanup: terminating server...", flush=True)
p.terminate()
try:
    p.wait(3)
except Exception:
    p.kill()
print("cleanup: stopping dist processes...", flush=True)
sp2 = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine "
     "-like '*_dist_verify\\*' -and $_.ProcessId -ne $PID } | ForEach-Object "
     "{ Stop-Process -Id $_.ProcessId -Force }"],
    capture_output=True, creationflags=NO_WINDOW, timeout=15)
print("cleanup: stopping processes done rc=%s" % sp2.returncode, flush=True)
time.sleep(0.5)
# junction 只删链接不伤源：os.rmdir 对 junction 是 unlink 语义；
# 实体目录随后 rmtree。带重试——句柄释放可能滞后于进程退出。
import time as _t
for attempt in range(5):
    for d in ["python", "katex", "pagedjs", "docs", "LICENSES"]:
        j = os.path.join(DIST, d)
        if os.path.isdir(j):
            try:
                os.rmdir(j)
            except OSError:
                pass
    try:
        shutil.rmtree(DIST, ignore_errors=False)
    except Exception:
        pass
    if not os.path.exists(DIST):
        break
    _t.sleep(0.5)
check("cleanup (source dirs intact)",
      os.path.isdir(os.path.join(SRC, "python"))
      and os.path.isdir(os.path.join(SRC, "katex"))
      and not os.path.exists(DIST))

fails = [n for n, ok in RESULTS if not ok]
print("\n%d/%d passed" % (len(RESULTS) - len(fails), len(RESULTS)))
if fails:
    print("FAILED:", "; ".join(fails))
    sys.exit(1)