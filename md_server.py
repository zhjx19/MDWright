# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""
MD 编辑器本地后端 + 系统托盘（纯标准库，零第三方依赖）
- 标准库 http.server 提供页面 / 读文件 / 写文件路由
- 仅在 127.0.0.1 监听，单实例（由 md_launch.pyw 负责端口占用检测）
- 托盘用 ctypes 直接调用 Shell_NotifyIcon，无 pystray；失败则降级无托盘常驻
- LLM 客户端（润色/注解）为纯标准库 urllib 实现，见 llm_client.py
本文件与 markdown-editor.html 一同分发，配合内置 python/ 即可在任意 Windows 运行。
"""
import http.server
import hashlib
import io
import base64
import time
import subprocess
import tempfile
import socketserver
import socket
import shutil
import threading
import os
import sys
import json
import re
import uuid
import atexit
import zipfile
import urllib.parse
import urllib.request
import webbrowser
import html as html_module

try:
    if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import llm_client as _llm
except Exception as _e:
    _llm = None
    try:
        os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime"), exist_ok=True)
        with io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "runtime", "_llm.err"), "w", encoding="utf-8") as _f:
            _f.write(repr(_e))
    except Exception:
        pass

try:
    if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import rag_client as _ragc
    import web_search as _ws_mod
except Exception as _e:
    _ragc = None
    _ws_mod = None
    try:
        os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime"), exist_ok=True)
        with io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "runtime", "_ragc.err"), "w", encoding="utf-8") as _f:
            _f.write(repr(_e))
    except Exception:
        pass

PORT = 18766
HERE = os.path.dirname(os.path.abspath(__file__))
EDITOR_HTML = os.path.join(HERE, "markdown-editor.html")
MD_SERVER_VERSION = 63  # 每次服务端路由/能力变更时 +1；md_launch 依此自愈换代
SETTINGS_PATH = os.path.join(HERE, "runtime", "settings.json")

# .smd 自包含文档格式（v1.2.0）；导入失败落错误日志，相关路由返回明确错误而非静默
try:
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import _smd
except Exception as _e:  # embedded Python 下兜底，与 md_assets 同模式
    _smd = None
    try:
        os.makedirs(os.path.join(HERE, "runtime"), exist_ok=True)
        with io.open(os.path.join(HERE, "runtime", "_smd.err"), "w", encoding="utf-8") as _f:
            _f.write(repr(_e))
    except Exception:
        pass


def _rewrite_assets_ref(text, old, new):
    """把文档内 "old/..." 资源引用改写为 "new/..."（.smd 打包/导出的路径契约换算）。

    old/new 均为不含尾斜杠的目录引用，如 "我的文档.assets"（磁盘契约）或
    "assets"（.smd 包内契约）。左边界断言 (?<![\\w\\-.]) 防止误伤更长名字的
    尾段（如 "xA.assets" 不会被 "A.assets" 命中，"Xassets/" 不会被 "assets" 命中）。
    返回 (新文本, 替换次数)。
    """
    if not text or not old or old == new:
        return text, 0
    pat = re.compile(r"(?<![\w\-.])" + re.escape(old) + r"/")
    out, n = pat.subn(new + "/", text)
    return out, n


# ---------------------------------------------------------------------------
# 批注与 LLM 配置持久化
#   .md  → 同目录 <文档名>.assets/annotations.json
#   .smd → 解包目录 assets/annotations.json（随包分发，_smd.PROTECTED 豁免清理）
# ---------------------------------------------------------------------------
ANNOT_NAME = "annotations.json"
LLM_DEFAULTS = {"backend": "lmstudio", "base_url": "", "model": "", "api_key": "",
                "timeout": 180, "max_tokens": 2048, "temperature": 0.7,
                "web_search": None}   # web_search 由 _norm_web_search_config 填充
WS_DEFAULTS = {"enabled": False, "backend": "duckduckgo", "api_key": "",
               "google_key": "", "google_cx": "", "bing_key": "",
               "custom_url": "", "max_results": 3}
_WS_BACKENDS = ("duckduckgo", "tavily", "google", "bing", "custom")


def _load_json(path, default):
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _annotations_path(doc_path):
    if _smd is not None and _smd.is_smd(doc_path):
        return os.path.join(_smd.base_dir_for(doc_path), _smd.ASSETS_DIR, ANNOT_NAME)
    stem = os.path.splitext(os.path.basename(doc_path))[0]
    return os.path.join(os.path.dirname(doc_path), stem + ".assets", ANNOT_NAME)


def _smd_tmp_backups(smd_path):
    """列出某文档未完成的保存备份（<文档名>.tmp<毫秒时间戳>），按时间升序。

    保存失败时 tmp 故意保留：会话结束解包工作目录会被 clear_tmp 清掉，
    它是本次内容跨会话的唯一幸存副本（打开文档时提供恢复入口）。
    """
    d = os.path.dirname(smd_path)
    base = os.path.basename(smd_path)
    if not d or not os.path.isdir(d):
        return []
    out = []
    for fn in os.listdir(d):
        m = re.match(re.escape(base) + r"\.tmp(\d+)$", fn)
        if m and os.path.isfile(os.path.join(d, fn)):
            out.append((int(m.group(1)), os.path.join(d, fn)))
    out.sort()
    return [fp for _, fp in out]


def _friendly_save_error(e, path):
    """保存失败 → 说人话。只读目标是高频根因（OneDrive/手工设置 R 属性）。"""
    if not isinstance(e, OSError):
        return str(e)
    ro = False
    try:
        if os.path.exists(path):
            ro = not (os.stat(path).st_mode & 0o222)
    except OSError:
        pass
    if ro:
        kept = ""
        try:
            tmps = _smd_tmp_backups(path)
            if tmps:
                kept = "\n本次内容已保留在 %s（重新打开本文档时可恢复）" % tmps[-1]
        except OSError:
            pass
        return ("目标文件为只读（可能被 OneDrive 或手工设置了只读属性），"
                "请解除只读后重新保存。%s" % kept)
    return str(e)


def _norm_llm_config(cfg):
    """LLM 配置归一：backend 白名单、数值限幅，防手写 settings.json 脏数据打崩客户端。"""
    cfg = cfg if isinstance(cfg, dict) else {}
    out = dict(LLM_DEFAULTS)
    backend = str(cfg.get("backend") or "").lower()
    if backend in ("lmstudio", "ollama", "openai", "deepseek"):
        out["backend"] = backend
    for k in ("base_url", "model", "api_key"):
        v = cfg.get(k)
        out[k] = v.strip() if isinstance(v, str) else ""
    for k, lo, hi in (("timeout", 5, 600), ("max_tokens", 64, 32768)):
        try:
            out[k] = max(lo, min(hi, int(cfg.get(k, out[k]))))
        except Exception:
            pass
    try:
        out["temperature"] = max(0.0, min(2.0, float(cfg.get("temperature", out["temperature"]))))
    except Exception:
        pass
    out["web_search"] = _norm_web_search_config(cfg.get("web_search"))
    return out


def _norm_web_search_config(cfg):
    """联网查询子配置归一：backend 白名单、布尔/数值限幅（模式同 rag-assistant）。"""
    cfg = cfg if isinstance(cfg, dict) else {}
    out = dict(WS_DEFAULTS)
    out["enabled"] = bool(cfg.get("enabled"))
    backend = str(cfg.get("backend") or "").lower()
    if backend in _WS_BACKENDS:
        out["backend"] = backend
    for k in ("api_key", "google_key", "google_cx", "bing_key", "custom_url"):
        v = cfg.get(k)
        out[k] = v.strip() if isinstance(v, str) else ""
    try:
        out["max_results"] = max(1, min(10, int(cfg.get("max_results", out["max_results"]))))
    except Exception:
        pass
    return out


def _llm_saved_config():
    settings = _load_json(SETTINGS_PATH, {})
    cfg = settings.get("llm") if isinstance(settings, dict) else None
    return _norm_llm_config(cfg if isinstance(cfg, dict) else {})


def _llm_config_from_request(obj):
    """按请求携带的 config（未保存的表单值）归一配置；未携带则用已存配置。"""
    cfg = obj.get("config") if isinstance(obj, dict) else None
    return _norm_llm_config(cfg) if isinstance(cfg, dict) else _llm_saved_config()


def _llm_from_request(obj):
    """按请求携带的 config（未保存的表单值）构造 LLMClient；未携带则用已存配置。"""
    if _llm is None:
        raise _LLM_ERR("llm_client.py 加载失败，详见 runtime/_llm.err")
    return _llm.LLMClient(_llm_config_from_request(obj))


_LLM_ERR = _llm.LLMError if _llm is not None else RuntimeError


# ---------------------------------------------------------------------------
# RAG（rag-assistant 检索增强）：只检索不生成 —— /api/kb/query 拿上下文，
# 拼进 LLM prompt 后仍走 llm_client 生成；原润色/解释路径零改动。
# 服务端为 rag-assistant 外部 API（:8767），与它的 Web UI（:8765/18765）隔离。
# ---------------------------------------------------------------------------
RAG_PORT = 8767
RAG_DEFAULTS = {"path": "", "kb": ""}   # 路径默认空：分发给谁都是无效值，由用户自填

_rag_lock = threading.Lock()
_rag_process = None        # 本服务拉起的 rag-assistant 子进程（手动启停）
_rag_starting = False      # 冷启动中（后台线程轮询就绪）
_rag_process_stderr = ""   # 子进程崩掉时的 Traceback 摘录（诊断用）

_RAG_SYS_POLISH = (
    "你是一个中文写作润色助手。用户给你一段文本，并附上从其知识库检索到的参考资料。"
    "请结合参考资料润色优化：保持原意、结构、篇幅和 Markdown 标记（#、*、`、链接等）完全不变，"
    "仅优化表达的通顺、准确与书面化，术语与事实尽量与参考资料一致。"
    "只输出润色后的文本，不要解释。\n\n【参考资料】\n%s")

_RAG_SYS_EXPLAIN = (
    "你是一个 Markdown 文档注释助手。用户给出一段文本，并附上从其知识库检索到的参考资料。"
    "请结合参考资料为它写一条简洁的备注/批注：解释它的含义或补充要点，2-4 句，第一人称可省略。"
    "直接输出备注内容，不要引号、不要'备注：'前缀。\n\n【参考资料】\n%s")

_WS_SYS_POLISH = (
    "你是一个中文写作润色助手。用户给你一段文本，并附上联网搜索到的网络资料。"
    "请结合网络资料润色优化：保持原意、结构、篇幅和 Markdown 标记（#、*、`、链接等）完全不变，"
    "仅优化表达的通顺、准确与书面化，事实性内容尽量与网络资料一致。"
    "只输出润色后的文本，不要解释。\n\n【网络资料】\n%s")

_WS_SYS_EXPLAIN = (
    "你是一个 Markdown 文档注释助手。用户给出一段文本，并附上联网搜索到的网络资料。"
    "请结合网络资料为它写一条简洁的备注/批注：解释它的含义或补充要点，2-4 句，第一人称可省略。"
    "直接输出备注内容，不要引号、不要'备注：'前缀。\n\n【网络资料】\n%s")


def _norm_rag_config(cfg):
    """RAG 配置归一：路径与知识库名；key 缺失/脏数据保留默认，防手写 settings.json 打崩。"""
    cfg = cfg if isinstance(cfg, dict) else {}
    out = dict(RAG_DEFAULTS)
    for k in ("path", "kb"):
        v = cfg.get(k)
        out[k] = v.strip() if isinstance(v, str) else out[k]
    return out


def _rag_saved_config():
    settings = _load_json(SETTINGS_PATH, {})
    cfg = settings.get("rag") if isinstance(settings, dict) else None
    return _norm_rag_config(cfg if isinstance(cfg, dict) else {})


def _rag_from_request(obj):
    """按请求携带的 rag 段构造配置；未携带则用已存配置。"""
    cfg = obj.get("rag") if isinstance(obj, dict) else None
    return _norm_rag_config(cfg) if isinstance(cfg, dict) else _rag_saved_config()


def _probe_rag():
    """探测 :8767 是否在线。先 socket 短超时探端口（毫秒级~0.5s，且 IPv4
    直连绕开 localhost→IPv6 解析），端口活着才走 HTTP 拿 health/KB 列表。
    本机对未监听端口可能是 drop 而非 RST，直接 HTTP 探测会等满超时。"""
    s = socket.socket()
    s.settimeout(0.5)
    try:
        if s.connect_ex(("127.0.0.1", RAG_PORT)) != 0:
            return {"online": False, "health": None, "kbs": []}
    finally:
        s.close()
    try:
        req = urllib.request.Request("http://127.0.0.1:%d/api/health" % RAG_PORT)
        with urllib.request.urlopen(req, timeout=3) as resp:
            health = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"online": False, "health": None, "kbs": []}
    kbs = []
    try:
        req2 = urllib.request.Request("http://127.0.0.1:%d/api/kb/list" % RAG_PORT)
        with urllib.request.urlopen(req2, timeout=3) as resp2:
            kb_data = json.loads(resp2.read().decode("utf-8"))
        kbs_raw = kb_data.get("kbs", kb_data.get("data", []))
        if isinstance(kbs_raw, dict):
            kbs = list(kbs_raw.keys())
        elif isinstance(kbs_raw, list):
            kbs = [k if isinstance(k, str) else k.get("name", "") for k in kbs_raw]
    except Exception:
        pass
    return {"online": True, "health": health, "kbs": kbs}


def _rag_python_cmd(rag_path):
    """挑能跑 rag-assistant 重依赖（torch/chromadb…）的解释器：
    venv → PATH 里的 python → py -3 → 当前解释器兜底。
    本服务可能由内嵌纯净 Python 运行，直接用 sys.executable 大概率缺依赖。"""
    venv_py = os.path.join(rag_path, ".venv", "Scripts", "python.exe")
    if os.path.isfile(venv_py):
        return [venv_py]
    for name in ("python", "python3"):
        w = shutil.which(name)
        if w and os.path.normcase(w) != os.path.normcase(sys.executable):
            return [w]
    w = shutil.which("py")
    if w:
        return [w, "-3"]
    return [sys.executable]


def _rag_start_async(rag_path):
    """异步冷启动 rag-assistant 外部 API。返回 (ok, msg)。"""
    global _rag_starting, _rag_process, _rag_process_stderr
    main_py = os.path.join(rag_path, "main.py")
    if not os.path.isfile(main_py):
        return False, "路径下未找到 main.py：%s" % main_py
    if _probe_rag()["online"]:
        return False, "RAG 服务已在运行（端口 %d），无需启动" % RAG_PORT
    with _rag_lock:
        if _rag_starting:
            return False, "正在启动中，请稍候"
        _rag_starting = True
    try:
        # stderr 落临时文件而非 pipe：子进程输出多时 pipe 缓冲区满会卡死双方
        stderr_tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".log", prefix="rag_", mode="w", encoding="utf-8")
        stderr_path = stderr_tmp.name
        # 子进程强制 UTF-8 输出，防中文/emoji 在 GBK 控制台报编码错
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        cmd = _rag_python_cmd(rag_path) + [main_py, "--port", "18765",
                                           "--api-port", str(RAG_PORT)]
        proc = subprocess.Popen(cmd, cwd=rag_path, env=env,
                                stdout=subprocess.DEVNULL, stderr=stderr_tmp)
        stderr_tmp.close()
        with _rag_lock:
            _rag_process = proc
            _rag_process_stderr = ""
    except Exception as e:
        with _rag_lock:
            _rag_starting = False
        return False, "启动失败：%s" % e

    def _poll():
        global _rag_starting, _rag_process_stderr
        try:
            for _ in range(45):          # 最多等 90 秒（embedding 冷加载）
                time.sleep(2)
                if _probe_rag()["online"]:
                    return
                if proc.poll() is not None:
                    # 子进程挂了：读临时文件找 Traceback
                    err = ""
                    try:
                        with open(stderr_path, "r", encoding="utf-8", errors="replace") as ef:
                            full = ef.read()
                        idx = full.rfind("Traceback (most recent call last)")
                        err = full[idx:][:2000] if idx >= 0 else full[-2000:]
                    except Exception:
                        err = "(无法读取启动输出)"
                    with _rag_lock:
                        _rag_process_stderr = err
                    return
        finally:
            with _rag_lock:
                _rag_starting = False
            try:
                os.unlink(stderr_path)
            except Exception:
                pass

    threading.Thread(target=_poll, daemon=True).start()
    return True, "RAG 启动中（冷加载 embedding 可能需数十秒），请稍候…"


def _rag_stop():
    """停 RAG：terminate 本服务拉起的子进程 → 清 :8767 全部 PID → 等端口释放。
    rag-assistant 带看护自动重启，kill 后端口可能复活，只能尽力而为；
    返回 True=端口仍活着（复活），False=已真停。"""
    global _rag_process, _rag_process_stderr
    with _rag_lock:
        if _rag_process is not None:
            try:
                _rag_process.terminate()
                _rag_process.wait(timeout=3)
            except Exception:
                try:
                    _rag_process.kill()
                except Exception:
                    pass
            _rag_process = None
            _rag_process_stderr = ""
    try:
        r = subprocess.run("netstat -ano", capture_output=True, text=True,
                           shell=True, timeout=5)
        for line in r.stdout.splitlines():
            if str(RAG_PORT) in line and ("LISTENING" in line or "ESTABLISHED" in line):
                parts = line.strip().split()
                if parts and parts[-1].isdigit():
                    subprocess.run(["taskkill", "/F", "/T", "/PID", parts[-1]],
                                   capture_output=True, timeout=5)
    except Exception:
        pass
    for _ in range(10):
        try:
            s = socket.socket()
            s.settimeout(0.5)
            s.connect(("127.0.0.1", RAG_PORT))
            s.close()
            time.sleep(0.5)
        except Exception:
            return False        # 连不上 = 端口已释放
    return _probe_rag()["online"]


class ReuseTCPServer(socketserver.ThreadingTCPServer):
    # 线程化：LLM 润色/解释最长可达 timeout 秒（默认 180），单线程会卡死
    # 心跳/保存等全部路由；HTTP/1.0 每请求一线程，用完即回收
    daemon_threads = True
    allow_reuse_address = True


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/index.html"):
            try:
                with open(EDITOR_HTML, "r", encoding="utf-8") as f:
                    html = f.read()
            except Exception as e:  # pragma: no cover
                self._send(500, "read editor failed: %s" % e)
                return
            build = hashlib.md5(html.encode("utf-8")).hexdigest()[:10]
            html = html.replace("<body>", '<body data-build="%s">' % build, 1)
            self._send(200, html, "text/html; charset=utf-8",
                       {"Cache-Control": "no-store"})
            return
        if u.path == "/api/version":
            # sessions：当前活跃页面会话数（页面加载完成即发首个 ping 登记）。
            # 启动画面据此判断"窗口真正加载出来了"再淡出（v1.11.1）。
            self._send(200, json.dumps(
                {"ok": True, "version": MD_SERVER_VERSION,
                 "sessions": len(_LIVE_SESSIONS)},
                ensure_ascii=False))
            return
        if u.path == "/api/tools":
            # 外部工具探测（pandoc / 浏览器 / R / quarto）：前端据 found 决定按钮置灰，
            # 缺失时给安装指引而不是让导出中途炸掉。
            try:
                settings = _load_json(SETTINGS_PATH, {})
                cfg = settings.get("tools") if isinstance(settings, dict) else {}
                if not isinstance(cfg, dict):
                    cfg = {}
                self._send(200, json.dumps({"ok": True,
                                            "tools": _tools_probe_cached(cfg),
                                            "configured": cfg},
                                           ensure_ascii=False),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/ping":
            # 页面心跳：登记本会话存活（token 区分多窗口/多标签），并撤销待退出。
            # 注意：闲置（切标签页/最小化）绝不触发退出。
            _keepalive_ping(_live_tok(u.query))
            self._send(200, '{"ok":true}', "application/json; charset=utf-8")
            return
        if u.path == "/api/bye":
            # 页面卸载通知（pagehide -> sendBeacon）。刷新也会走到这里，
            # 因此只"登记"，由看门狗在宽限期后再决定是否退出。
            # 多窗口共享本服务：仅当【最后一个】会话 bye 后才进入待退出。
            _keepalive_bye(_live_tok(u.query))
            self._send(200, '{"ok":true}', "application/json; charset=utf-8")
            return
        if u.path == "/api/browse-dir":
            try:
                d = _pick_dir_subprocess()
                self._send(200, json.dumps({"ok": True, "dir": d or ""},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/open-file":
            # 浏览器模式专用：用原生"打开"框拿真实完整路径
            try:
                q = urllib.parse.parse_qs(u.query)
                initdir = q.get("dir", [""])[0]
                p = _pick_file_subprocess(initdir)
                if p:
                    _LAST_DOC_DIR[0] = os.path.dirname(p)
                self._send(200, json.dumps({"ok": True, "path": p},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/common-dirs":
            try:
                out = _common_dirs()
                self._send(200, json.dumps({"ok": True, "dirs": out},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/version":
            # sessions：当前活跃页面会话数（页面加载完成即发首个 ping 登记）。
            # 启动画面据此判断"窗口真正加载出来了"再淡出（v1.11.1）。
            self._send(200, json.dumps(
                {"ok": True, "version": MD_SERVER_VERSION,
                 "sessions": len(_LIVE_SESSIONS)},
                ensure_ascii=False))
            return
        if u.path == "/favicon.ico":
            ico = os.path.join(HERE, "md-editor.ico")
            try:
                with open(ico, "rb") as f:
                    self._send(200, f.read(), "image/x-icon",
                               {"Cache-Control": "max-age=86400"})
            except Exception:
                self._send(404, "not found")
            return
        if u.path == "/api/fonts":
            try:
                import winreg
                fonts = set()
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        k = winreg.OpenKey(hive, "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Fonts")
                    except OSError:
                        continue
                    i = 0
                    while True:
                        try:
                            name, _, _ = winreg.EnumValue(k, i)
                            i += 1
                        except OSError:
                            break
                        name = re.sub(r"\s*\((TrueType|OpenType|PostScript)\)$", "", name, flags=re.IGNORECASE)
                        for part in name.split("&"):
                            part = part.strip()
                            if part:
                                fonts.add(part)
                    try:
                        winreg.CloseKey(k)
                    except OSError:
                        pass
                self._send(200, json.dumps({"ok": True,
                    "fonts": sorted(fonts, key=lambda s: s.lower())}, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path.startswith("/static/"):
            rel = urllib.parse.unquote(u.path[len("/static/"):])
            root = os.path.normpath(HERE)
            full = os.path.normpath(os.path.join(HERE, rel))
            if not (full == root or full.startswith(root + os.sep)):
                self._send(403, "forbidden")
                return
            ctypes_map = {
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf",
                ".html": "text/html; charset=utf-8", ".png": "image/png",
                ".svg": "image/svg+xml", ".ico": "image/x-icon",
            }
            ctype = ctypes_map.get(os.path.splitext(full)[1].lower(),
                                   "application/octet-stream")
            try:
                with open(full, "rb") as f:
                    data = f.read()
            except Exception:
                self._send(404, "not found")
                return
            self._send(200, data, ctype)
            return
        if u.path == "/api/file":
            q = urllib.parse.parse_qs(u.query)
            p = q.get("path", [""])[0]
            if not p:
                self._send(400, json.dumps({"ok": False, "error": "missing path"}, ensure_ascii=False))
                return
            if _smd is not None and _smd.is_smd(p):
                # .smd 自包含文档：解包（幂等）后返回 doc.md 内容 + 工作目录，
                # 前端以 base 为图片基址（assets/ 引用经 /img 代理指向解包目录）
                try:
                    base = _smd.base_dir_for(p)
                    with open(os.path.join(base, _smd.DOC_NAME), "r", encoding="utf-8") as f:
                        content = f.read()
                    _LAST_DOC_DIR[0] = base
                    self._send(200, json.dumps({"ok": True, "smd": True, "base": base,
                                                "content": content}, ensure_ascii=False),
                               "application/json; charset=utf-8")
                except Exception as e:
                    self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                return
            try:
                _LAST_DOC_DIR[0] = os.path.dirname(p)
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    data = f.read()
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                return
            self._send(200, data, "text/plain; charset=utf-8")
            return
        if u.path == "/img":
            q = urllib.parse.parse_qs(u.query)
            p = q.get("path", [""])[0]
            if p and not os.path.isabs(p):
                cand = os.path.join(HERE, p)
                if os.path.exists(cand):
                    p = cand
            exts = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                    ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
                    ".bmp": "image/bmp"}
            ext = os.path.splitext(p)[1].lower()
            try:
                st = os.stat(p)
                with open(p, "rb") as f:
                    data = f.read()
            except Exception:
                self._send(404, "image not found")
                return
            # 协商缓存：ETag=mtime-size，浏览器每次请求都回源校验，
            # 文件没变回 304（不重传），变了立刻拿到新图 —— F5 即见效
            etag = '"%d-%d"' % (int(st.st_mtime), st.st_size)
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("ETag", etag)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", exts.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", etag)
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path == "/docs-list":
            docs_dir = os.path.join(HERE, "docs")
            items = []
            try:
                for f in sorted(os.listdir(docs_dir)):
                    if f.lower().endswith(".md"):
                        items.append({"name": os.path.splitext(f)[0],
                                      "file": f})
            except Exception:
                pass
            self._send(200, json.dumps({"ok": True, "docs": items},
                                       ensure_ascii=False))
            return
        if u.path == "/api/log":
            q = urllib.parse.parse_qs(u.query)
            msg = q.get("msg", [""])[0][:500]
            try:
                rt = os.path.join(HERE, "runtime")
                os.makedirs(rt, exist_ok=True)
                with io.open(os.path.join(rt, "ui.log"), "a",
                             encoding="utf-8") as f:
                    f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
            except Exception:
                pass
            self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
            return
        if u.path == "/api/open-external":
            q = urllib.parse.parse_qs(u.query)
            url = q.get("url", [""])[0]
            # 仅允许本机服务的 URL，防止被用作任意程序启动器
            if url.startswith("/"):
                url = "http://127.0.0.1:%d%s" % (PORT, url)
            if url.startswith("http://127.0.0.1:%d/" % PORT)                     or url.startswith("http://localhost:%d/" % PORT):
                threading.Thread(target=lambda: webbrowser.open(url),
                                 daemon=True).start()
                self._send(200, json.dumps({"ok": True},
                                           ensure_ascii=False))
            else:
                self._send(400, json.dumps({"ok": False,
                    "error": "仅允许打开本机服务地址"}, ensure_ascii=False))
            return
        if u.path == "/api/save-dialog":
            # 原生「保存为」框：Word / PDF 导出先让用户选路径（可改目录与文件名，
            # 覆盖已存在文件时由系统确认）。取消返回 path=""
            try:
                q = urllib.parse.parse_qs(u.query)
                ext = (q.get("ext", [""])[0] or "").lower()
                name = q.get("name", [""])[0]
                initdir = q.get("dir", [""])[0]
                title = q.get("title", [""])[0] or ("保存为 .%s" % ext)
                p = _save_dialog_subprocess(title, name, initdir, ext)
                self._send(200, json.dumps({"ok": True, "path": p or ""},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/reveal":
            # 在资源管理器里定位导出产物（只接受已存在路径，不做任意命令执行）
            q = urllib.parse.parse_qs(u.query)
            target = q.get("path", [""])[0]
            if not target or not os.path.exists(target):
                self._send(400, json.dumps({"ok": False, "error": "路径不存在"},
                                           ensure_ascii=False))
                return
            try:
                # /select, 与路径必须拼成一个参数字符串，否则资源管理器把路径当独立参数
                subprocess.Popen('explorer /select,"%s"' % os.path.normpath(target),
                                 creationflags=0x08000000)
                self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/doc":
            q = urllib.parse.parse_qs(u.query)
            fname = q.get("file", [""])[0]
            docs_dir = os.path.normpath(os.path.join(HERE, "docs"))
            full = os.path.normpath(os.path.join(docs_dir, fname))
            if (fname and full.startswith(docs_dir + os.sep)
                    and os.path.isfile(full)):
                try:
                    with io.open(full, "r", encoding="utf-8") as f:
                        body = f.read()
                    _LAST_DOC_DIR[0] = os.path.dirname(full)
                    self._send(200, json.dumps(
                        {"ok": True, "path": full, "content": body},
                        ensure_ascii=False))
                except Exception as e:
                    self._send(500, json.dumps({"ok": False, "error": str(e)},
                                               ensure_ascii=False))
            else:
                self._send(404, json.dumps({"ok": False,
                    "error": "文档不存在"}, ensure_ascii=False))
            return
        if u.path == "/api/annotations":
            q = urllib.parse.parse_qs(u.query)
            p = q.get("path", [""])[0]
            if not p:
                self._send(400, json.dumps({"ok": False, "error": "missing path"}, ensure_ascii=False))
                return
            try:
                data = _load_json(_annotations_path(p), [])
                if not isinstance(data, list):
                    data = []
                self._send(200, json.dumps({"ok": True, "annotations": data}, ensure_ascii=False),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
        if u.path == "/api/save-backups":
            # 打开文档时查询：是否有保存失败保留的备份（<文档>.tmp<时间戳>）
            q = urllib.parse.parse_qs(u.query)
            p = q.get("path", [""])[0]
            if not p:
                self._send(400, json.dumps({"ok": False, "error": "missing path"}, ensure_ascii=False))
                return
            out = []
            try:
                for fp in _smd_tmp_backups(os.path.abspath(p)):
                    try:
                        st = os.stat(fp)
                    except OSError:
                        continue
                    valid = False
                    try:
                        with zipfile.ZipFile(fp) as _z:
                            _z.namelist()
                        valid = True
                    except Exception:
                        pass
                    out.append({"path": fp, "name": os.path.basename(fp),
                                "mtime": int(st.st_mtime), "size": st.st_size,
                                "valid": valid})
                self._send(200, json.dumps({"ok": True, "backups": out},
                                           ensure_ascii=False),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
        if u.path == "/api/llm-config":
            self._send(200, json.dumps({"ok": True, "config": _llm_saved_config(),
                                        "rag": _rag_saved_config()},
                                       ensure_ascii=False),
                       "application/json; charset=utf-8")
            return
        if u.path == "/api/rag-status":
            result = _probe_rag()
            with _rag_lock:
                proc_alive = _rag_process is not None and _rag_process.poll() is None
                starting = _rag_starting
                stderr = _rag_process_stderr[:500] if _rag_process_stderr else ""
            cfg = _rag_saved_config()
            self._send(200, json.dumps({"ok": True, "online": result["online"],
                                        "kbs": result["kbs"], "local_process": proc_alive,
                                        "starting": starting, "stderr": stderr,
                                        "path": cfg["path"], "kb": cfg["kb"]},
                                       ensure_ascii=False),
                       "application/json; charset=utf-8")
            return
        if u.path == "/open":
            q = urllib.parse.parse_qs(u.query)
            f = q.get("file", [""])[0]
            v = MD_SERVER_VERSION
            if f:
                target = "/?file=" + urllib.parse.quote(f) + "&v=%d" % v
            else:
                target = "/?v=%d" % v
            # 先回响应、再异步开浏览器：避免启动器等待超时后重复打开
            self._send(200, "ok")
            _url = "http://127.0.0.1:%d%s" % (PORT, target)
            threading.Timer(0.05, lambda: webbrowser.open(_url)).start()
            return
        # 根级静态兜底：工具目录内的图片/常见静态文件（防穿越，白名单扩展名）
        root = os.path.normpath(HERE)
        rel = urllib.parse.unquote(u.path.lstrip("/"))
        full = os.path.normpath(os.path.join(HERE, rel))
        static_exts = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                       ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
                       ".ico": "image/x-icon", ".css": "text/css", ".js": "application/javascript"}
        if (full.startswith(root + os.sep) and rel
                and os.path.splitext(full)[1].lower() in static_exts
                and os.path.isfile(full)):
            try:
                with open(full, "rb") as f:
                    data = f.read()
                self._send(200, data, static_exts[os.path.splitext(full)[1].lower()])
                return
            except Exception:
                pass
        self._send(404, "not found")

    def do_PUT(self):
        """PUT 语义：整体替换配置。目前只有 /api/tools 用得上；
        BaseHTTPRequestHandler 默认不实现 PUT（会 501），这里转发给 do_POST 按路径分发。"""
        self.do_POST()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/api/ping", "/api/bye"):
            # sendBeacon 走 POST（pagehide 心跳/卸载通知），路由与 GET 同一实现
            self.do_GET()
            return
        if u.path == "/api/file":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                obj = json.loads(raw.decode("utf-8"))
                p = obj.get("path", "")
                content = obj.get("content", "")
                if not p:
                    self._send(400, json.dumps({"ok": False, "error": "missing path"}, ensure_ascii=False))
                    return
                if _smd is not None and _smd.is_smd(p):
                    # .smd：正文写入解包目录 doc.md，增量追加进包（append 模式，
                    # 仅变化 entry；阈值触发时自动全量整理）。写前物化：手写的
                    # data URI / blob / 本机绝对路径中真实存在的图收进包内
                    # assets/，引用统一为 assets/ 契约；save_from_dir 按目录
                    # diff 自动追加新图。响应回传新正文供前端同步编辑区
                    base = _smd.base_dir_for(p)
                    if materialize_into:
                        content, _mi = materialize_into(
                            content, os.path.join(base, "assets"), "assets")
                    # newline=""：禁用换行翻译，磁盘=包内=响应字节一致
                    # （文本模式会把 LF 翻成 CRLF，save_from_dir 按原始字节进包）
                    with open(os.path.join(base, _smd.DOC_NAME), "w", encoding="utf-8",
                              newline="") as f:
                        f.write(content)
                    _n, _compacted = _smd.save_from_dir(p, base)
                    _LAST_DOC_DIR[0] = base
                    self._send(200, json.dumps({"ok": True, "smd": True, "base": base,
                                                "content": content,
                                                "images": []}, ensure_ascii=False))
                    return
                added = []
                if materialize_images:
                    content, added = materialize_images(p, content)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
                _LAST_DOC_DIR[0] = os.path.dirname(p)
                self._send(200, json.dumps({"ok": True, "content": content,
                                            "images": added}, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": _friendly_save_error(e, p)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/save-as":
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                d = obj.get("dir", "").strip()
                name = (obj.get("name") or "未命名.md").strip()
                content = obj.get("content", "")
                if not d or not os.path.isdir(d):
                    self._send(400, json.dumps({"ok": False,
                        "error": "目录不存在"}, ensure_ascii=False))
                    return
                to_smd = _smd is not None and name.lower().endswith(".smd")
                if not to_smd and not name.lower().endswith(".md"):
                    name += ".md"
                path = os.path.join(d, name)
                if to_smd:
                    # 另存为 .smd：正文进 doc.md；资产三级来源——
                    # ① base/assets（.smd 会话，引用已是包内 assets/ 契约，整目录跟随）
                    # ② src 同目录 <stem>.assets（普通文档，磁盘契约），整目录跟随
                    #    后把 "<stem>.assets/" 引用统一改写为 "assets/"
                    # ③ materialize_into：手写 data URI / blob / 本机绝对路径中
                    #    真实存在的图当场收进包内 assets/（不存在的原样保留，破图可见）
                    # 响应回传改写后正文给前端同步编辑区（否则下次 Ctrl+S 把旧引用写回包）
                    stage = _smd.base_dir_for(path) if os.path.isfile(path) else \
                        os.path.join(_smd._tmp_root(),
                                     hashlib.md5(os.path.abspath(path).lower().encode("utf-8")).hexdigest()[:16])
                    os.makedirs(stage, exist_ok=True)
                    src = (obj.get("src") or "").strip()
                    base = (obj.get("base") or "").strip()
                    src_assets = None
                    cand = None
                    if base and os.path.isdir(os.path.join(base, "assets")):
                        src_assets = os.path.join(base, "assets")
                    elif src and os.path.isfile(src):
                        cand = os.path.join(os.path.dirname(src),
                                            os.path.splitext(os.path.basename(src))[0] + ".assets")
                        if os.path.isdir(cand):
                            src_assets = cand
                        else:
                            cand = None
                    if materialize_into:
                        content, _mi = materialize_into(
                            content, os.path.join(stage, "assets"), "assets")
                    dst_assets = os.path.join(stage, "assets")
                    if src_assets and os.path.normpath(src_assets) != os.path.normpath(dst_assets):
                        os.makedirs(dst_assets, exist_ok=True)
                        import shutil as _sh
                        for fn in os.listdir(src_assets):
                            fp = os.path.join(src_assets, fn)
                            if os.path.isfile(fp):
                                _sh.copy2(fp, os.path.join(dst_assets, fn))
                    if cand:
                        content, _nr = _rewrite_assets_ref(
                            content, os.path.basename(cand), "assets")
                    # newline=""：禁用换行翻译，磁盘=包内=响应字节一致
                    with open(os.path.join(stage, _smd.DOC_NAME), "w", encoding="utf-8",
                              newline="") as f:
                        f.write(content)
                    _smd.pack_from_dir(path, os.path.join(stage, _smd.DOC_NAME), dst_assets)
                    _LAST_DOC_DIR[0] = stage
                    self._send(200, json.dumps({"ok": True, "path": path, "smd": True,
                                                "base": stage, "content": content,
                                                "images": []},
                                               ensure_ascii=False))
                    return
                added = []
                base = (obj.get("base") or "").strip()
                if _smd is not None and base and os.path.isdir(os.path.join(base, "assets")):
                    # .smd 会话导出普通 .md：包内 "assets/" 契约反向换算为磁盘
                    # "<stem>.assets/" 契约，图片一并落盘到目标目录
                    newstem = os.path.splitext(name)[0]
                    dst_assets = os.path.join(d, newstem + ".assets")
                    os.makedirs(dst_assets, exist_ok=True)
                    import shutil as _sh
                    for fn in os.listdir(os.path.join(base, "assets")):
                        fp = os.path.join(base, "assets", fn)
                        if os.path.isfile(fp):
                            _sh.copy2(fp, os.path.join(dst_assets, fn))
                    content, _nr = _rewrite_assets_ref(content, "assets",
                                                       newstem + ".assets")
                if materialize_images:
                    content, added = materialize_images(path, content)
                else:
                    added = []
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                _LAST_DOC_DIR[0] = d
                self._send(200, json.dumps({"ok": True, "path": path,
                                            "content": content, "images": added},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": _friendly_save_error(e, path)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/restore-backup":
            # 用失败备份覆盖 .smd —— 仅在前端用户点过"恢复"确认后到达这里
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                p = os.path.abspath(obj.get("path") or "")
                bak = os.path.abspath(obj.get("backup") or "")
                if not p or not bak:
                    self._send(400, json.dumps({"ok": False, "error": "bad payload"}, ensure_ascii=False))
                    return
                # 安全校验：备份必须确实是该文档的 tmp（同目录同名 .tmp<时间戳>
                # 模式 + zip 有效性；防误传任意路径覆盖好包）
                ok_pat = bool(re.match(re.escape(os.path.basename(p)) + r"\.tmp\d+$",
                                       os.path.basename(bak)))
                same_dir = os.path.dirname(bak) == os.path.dirname(p)
                valid = False
                if ok_pat and same_dir and os.path.isfile(bak):
                    try:
                        with zipfile.ZipFile(bak) as _z:
                            _z.namelist()
                        valid = True
                    except Exception:
                        pass
                if valid:
                    os.replace(bak, p)   # 目标在不在都允许落位；base_dir_for 指纹检测会自动重解包
                    self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
                else:
                    self._send(400, json.dumps({"ok": False, "error": "备份与文档不匹配或已损坏"}, ensure_ascii=False))
            except OSError as e:
                self._send(500, json.dumps({"ok": False,
                    "error": _friendly_save_error(e, obj.get("path") or "")}, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
        if u.path == "/api/paste-image":
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                doc_path = obj.get("docPath") or ""
                data_url = obj.get("dataUrl") or ""
                if not doc_path:
                    self._send(400, json.dumps({"ok": False,
                        "error": "文档尚未保存"}, ensure_ascii=False))
                    return
                head, _, b64 = data_url.partition(",")
                ext = ".png"
                if "jpeg" in head: ext = ".jpg"
                elif "webp" in head: ext = ".webp"
                elif "gif" in head: ext = ".gif"
                if _smd is not None and _smd.is_smd(doc_path):
                    # .smd：图片落解包工作目录的 assets/，引用为 assets/<fname>
                    base = _smd.base_dir_for(doc_path)
                    assets = os.path.join(base, "assets")
                    os.makedirs(assets, exist_ok=True)
                    fname = "%s_%s%s" % (time.strftime("%Y%m%d_%H%M%S"),
                                         str(int(time.time() * 1000))[-4:], ext)
                    with open(os.path.join(assets, fname), "wb") as f:
                        f.write(base64.b64decode(b64))
                    self._send(200, json.dumps({"ok": True,
                        "rel": "assets/%s" % fname}, ensure_ascii=False))
                    return
                stem = os.path.splitext(os.path.basename(doc_path))[0]
                assets = os.path.join(os.path.dirname(doc_path), stem + ".assets")
                os.makedirs(assets, exist_ok=True)
                fname = "%s_%s%s" % (time.strftime("%Y%m%d_%H%M%S"),
                                     str(int(time.time() * 1000))[-4:], ext)
                with open(os.path.join(assets, fname), "wb") as f:
                    f.write(base64.b64decode(b64))
                self._send(200, json.dumps({"ok": True,
                    "rel": "%s.assets/%s" % (stem, fname)}, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/export-html":
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                html = build_standalone_html(obj.get("path") or None,
                                             obj.get("bodyHtml", ""),
                                             obj.get("tsCss", ""),
                                             obj.get("docTitle") or "")
                name = "document.html"
                with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
                    f.write(html)
                self._send(200, json.dumps({"ok": True, "url": "/static/" + name},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/export-paged":
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                md_path = obj.get("path") or None
                body_html = obj.get("bodyHtml", "")
                ts_css = obj.get("tsCss", "")
                page_cfg = obj.get("cfg", {}) or {}
                html = build_paged_html(md_path, body_html, ts_css, page_cfg,
                                        obj.get("docTitle") or "")
                # /static/ 路由会把前缀剥掉后映射到工具目录（/static/x -> HERE/x），
                # 因此文件写在 HERE 下、URL 用 /static/<name> 即可正确访问
                name = "document.paged.html"
                with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
                    f.write(html)
                self._send(200, json.dumps({"ok": True, "url": "/static/" + name},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/export":
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                name = obj.get("name", "")
                content = obj.get("content", "")
                if not re.match(r"^[A-Za-z0-9._-]+\.html$", name):
                    self._send(400, json.dumps({"ok": False, "error": "bad name"}, ensure_ascii=False))
                    return
                with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
                    f.write(content)
                self._send(200, json.dumps({"ok": True, "url": "/static/" + name}, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
        if u.path == "/api/tools":
            # 保存手工路径（四个键，脏值归一），存完立刻重探并回传新结果
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                import md_tools
                cfg = md_tools.norm_tools_config(obj.get("config"))
                settings = _load_json(SETTINGS_PATH, {})
                if not isinstance(settings, dict):
                    settings = {}
                settings["tools"] = cfg
                _save_json(SETTINGS_PATH, settings)
                _TOOLS_CACHE["val"] = None          # 强制重探（工具可能刚装/刚搬）
                self._send(200, json.dumps({"ok": True,
                                            "tools": _tools_probe_cached(cfg),
                                            "configured": cfg},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/run-py":
            # 执行 Python 代码块（内置便携运行时；只回 stdout/stderr）
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                code = obj.get("code") or ""
                if not code.strip():
                    self._send(400, json.dumps({"ok": False, "error": "代码为空"},
                                               ensure_ascii=False))
                    return
                self._send(200, json.dumps(_run_py_code(code), ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/run-r":
            # 执行 R 代码块。跑的是**用户自己的代码**（UI 已明示），只在本机执行。
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                code = obj.get("code") or ""
                if not code.strip():
                    self._send(400, json.dumps({"ok": False, "error": "代码为空"},
                                               ensure_ascii=False))
                    return
                settings = _load_json(SETTINGS_PATH, {})
                cfg = settings.get("tools") if isinstance(settings, dict) else {}
                cfg = cfg if isinstance(cfg, dict) else {}
                import md_tools
                rscript = md_tools.find_r(md_tools._cfg(cfg, "rscript_path", "rscript"))
                if not rscript:
                    self._send(400, json.dumps({"ok": False,
                        "error": "未检测到 R 运行时（Rscript.exe）：请安装 R，"
                                 "或在「设置 → 外部工具」里指定 Rscript 路径"},
                        ensure_ascii=False))
                    return
                res = _run_r_code(code, rscript)
                res["ok"] = bool(res.get("ok"))
                self._send(200, json.dumps(res, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)},
                                           ensure_ascii=False))
            return
        if u.path == "/api/export-docx":
            # Word 导出：前端交 markdown **源文**（不是 bodyHtml）——pandoc 吃源文，
            # 公式、脚注、定义列表由它原生落成 Word 结构（公式→OMML）。
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                md_path = (obj.get("path") or "").strip()
                md_text = obj.get("markdown") or ""
                if not md_path:
                    self._send(400, json.dumps({"ok": False, "error": "请先保存文档再导出 Word"},
                                               ensure_ascii=False))
                    return
                if not os.path.isfile(md_path):
                    self._send(400, json.dumps({"ok": False,
                        "error": "文档不存在：%s" % md_path}, ensure_ascii=False))
                    return
                if _is_builtin_doc(md_path):
                    self._send(400, json.dumps({"ok": False,
                        "error": "内置文档不能直接导出（会写进安装目录）："
                                 "请先「另存为」到你自己的目录，再导出 Word"},
                        ensure_ascii=False))
                    return
                stem = os.path.splitext(os.path.basename(md_path))[0]
                okp, out = _norm_out_path((obj.get("outPath") or "").strip(), md_path, "docx")
                if not okp:
                    self._send(400, json.dumps({"ok": False, "error": out},
                                               ensure_ascii=False))
                    return
                import md_pandoc
                settings = _load_json(SETTINGS_PATH, {})
                cfg = settings.get("tools") if isinstance(settings, dict) else {}
                cfg = cfg if isinstance(cfg, dict) else {}
                import md_tools
                md_pandoc.export_docx(md_text, md_path, out,
                                      md_tools._cfg(cfg, "pandoc_path", "pandoc"))
                self._send(200, json.dumps({"ok": True, "path": out}, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
        if u.path == "/api/export-pdf":
            # PDF 直出：复用分页 HTML，用 headless Chromium 打印成文件（不开打印对话框）。
            # 依赖本机 Edge/Chrome；缺了就明确报错并引导用「打印」。
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                md_path = (obj.get("path") or "").strip()
                if not md_path:
                    self._send(400, json.dumps({"ok": False, "error": "请先保存文档再导出 PDF"},
                                               ensure_ascii=False))
                    return
                if not os.path.isfile(md_path):
                    self._send(400, json.dumps({"ok": False,
                        "error": "文档不存在：%s" % md_path}, ensure_ascii=False))
                    return
                if _is_builtin_doc(md_path):
                    self._send(400, json.dumps({"ok": False,
                        "error": "内置文档不能直接导出（会写进安装目录）："
                                 "请先「另存为」到你自己的目录，再导出 PDF"},
                        ensure_ascii=False))
                    return
                import md_tools
                settings = _load_json(SETTINGS_PATH, {})
                cfg = settings.get("tools") if isinstance(settings, dict) else {}
                cfg = cfg if isinstance(cfg, dict) else {}
                browser = md_tools.find_browser(md_tools._cfg(cfg, "browser_path", "browser"))
                if not browser:
                    self._send(400, json.dumps({"ok": False,
                        "error": "未检测到 Chromium 内核浏览器（Edge/Chrome），无法直出 PDF；"
                                 "可改用「打印」按钮"}, ensure_ascii=False))
                    return
                html = build_paged_html(md_path, obj.get("bodyHtml", ""),
                                        obj.get("tsCss", ""), obj.get("cfg", {}) or {},
                                        obj.get("docTitle") or "")
                # 唯一文件名：并发导出（多标签 / 打印 + PDF 同时）不会互相覆盖半截文件
                name = "document.paged.%s.html" % uuid.uuid4().hex[:10]
                paged_path = os.path.join(HERE, name)
                with open(paged_path, "w", encoding="utf-8") as f:
                    f.write(html)
                # 端口取真实监听端口：服务可能不在 18766（测试就起在 18777），
                # 用模块常量会让浏览器去连别的服务，产出「看起来成功但内容不对」的文件。
                port = self.server.server_address[1]
                url = "http://127.0.0.1:%d/static/%s" % (port, name)
                stem = os.path.splitext(os.path.basename(md_path))[0]
                okp, out = _norm_out_path((obj.get("outPath") or "").strip(), md_path, "pdf")
                if not okp:
                    self._send(400, json.dumps({"ok": False, "error": out},
                                               ensure_ascii=False))
                    return
                import _cdp
                part = out + ".part"
                ok = False
                err = ""
                pages = 0
                try:
                    # CDP 单会话：等页面写下 data-paged-done（页码脚本按"页数连续稳定"判定）
                    # 再 printToPDF。不能用「--dump-dom + --print-to-pdf」两趟——
                    # 那是两次独立加载，实测同一文档页数在 0/1/2/3 之间乱跳，必出半截 PDF。
                    want = _cdp.print_pdf(url, out, browser)
                    data = open(part, "rb").read()
                    got = len(re.findall(rb"/Type\s*/Page[^s]", data))
                    if want and want == got:
                        os.replace(part, out)      # 校验通过才落位：失败不动已有同名文件
                        ok, pages = True, got
                    else:
                        err = ("分页校验不一致（DOM %d 页 / PDF %d 页），未生成文件；"
                               "请改用「打印」按钮" % (want, got))
                except Exception as e:
                    err = str(e)
                finally:
                    # 清理必须在**发响应之前**：否则客户端会先看到响应、后看到临时文件消失
                    for p in (part, paged_path):
                        try:
                            if os.path.exists(p):
                                os.remove(p)
                        except Exception:
                            pass
                if ok:
                    self._send(200, json.dumps({"ok": True, "path": out, "pages": pages},
                                               ensure_ascii=False))
                else:
                    self._send(500, json.dumps({"ok": False, "error": err},
                                               ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
        if u.path == "/api/annotations":
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                p = obj.get("path", "")
                anns = obj.get("annotations", [])
                if not p or not isinstance(anns, list):
                    self._send(400, json.dumps({"ok": False, "error": "bad payload"}, ensure_ascii=False))
                    return
                clean = []
                for a in anns:
                    if not isinstance(a, dict):
                        continue
                    clean.append({
                        "id": str(a.get("id", ""))[:64],
                        "text": str(a.get("text", ""))[:8000],
                        "note": str(a.get("note", ""))[:8000],
                        "created": a.get("created", 0),
                        "updated": a.get("updated", int(time.time())),
                    })
                if len(clean) > 2000:
                    clean = clean[:2000]
                apath = _annotations_path(p)
                _save_json(apath, clean)
                if _smd is not None and _smd.is_smd(p):
                    # .smd：批注随包分发——写解包目录后增量追加进包，
                    # 否则包内 annotations.json 停留在旧版（仅存于临时目录）
                    try:
                        _smd.save_from_dir(p, os.path.dirname(os.path.dirname(apath)))
                    except Exception as e:
                        self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                        return
                self._send(200, json.dumps({"ok": True, "count": len(clean)}, ensure_ascii=False),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
        if u.path == "/api/llm-config":
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
                cfg = obj.get("config")
                if not isinstance(cfg, dict):
                    self._send(400, json.dumps({"ok": False, "error": "bad payload"}, ensure_ascii=False))
                    return
                merged = _norm_llm_config(cfg)
                settings = _load_json(SETTINGS_PATH, {})
                if not isinstance(settings, dict):
                    settings = {}
                settings["llm"] = merged
                rag_cfg = obj.get("rag")          # 同一保存动作可捎带 RAG 段
                if isinstance(rag_cfg, dict):
                    settings["rag"] = _norm_rag_config(rag_cfg)
                _save_json(SETTINGS_PATH, settings)
                self._send(200, json.dumps({"ok": True, "config": merged,
                                            "rag": settings.get("rag", _rag_saved_config())},
                                           ensure_ascii=False),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
        # ---- LLM 动作路由：业务性失败（连不上/没模型）一律 200 + ok:false，前端统一读 error ----
        if u.path in ("/api/llm-models", "/api/llm-test", "/api/annotate", "/api/rewrite"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "error": "请求体解析失败: %s" % e},
                                           ensure_ascii=False), "application/json; charset=utf-8")
                return
            try:
                client = _llm_from_request(obj)
                if u.path == "/api/llm-models":
                    models = client.list_models()
                    self._send(200, json.dumps({"ok": True, "models": models}, ensure_ascii=False),
                               "application/json; charset=utf-8")
                    return
                if u.path == "/api/llm-test":
                    ok, msg = client.test_connection()
                    self._send(200, json.dumps({"ok": ok, "message": msg}, ensure_ascii=False),
                               "application/json; charset=utf-8")
                    return
                text = str(obj.get("text", ""))[:30000]
                if not text.strip():
                    self._send(200, json.dumps({"ok": False, "error": "选区内容为空"}, ensure_ascii=False),
                               "application/json; charset=utf-8")
                    return
                if client.backend in ("ollama", "openai") and not client.model:
                    self._send(200, json.dumps({"ok": False,
                                                "error": "该后端需先在 LLM 设置中选择模型"},
                                               ensure_ascii=False), "application/json; charset=utf-8")
                    return
                # 联网查询开启时：先搜索 → 资料拼 prompt → LLM；失败静默降级纯模型
                ws_cfg = _llm_config_from_request(obj).get("web_search") or {}
                ws_flag = "off"
                ws_ctx = ""
                if ws_cfg.get("enabled"):
                    if _ws_mod is None:
                        ws_flag = "degraded"
                    else:
                        sr = _ws_mod.WebSearch(ws_cfg).search(text[:200])
                        if sr.get("success") and sr.get("results"):
                            ws_flag = "ok"
                            ws_ctx = _ws_mod.format_results(sr["results"])
                        else:
                            ws_flag = "degraded"
                is_ann = (u.path == "/api/annotate")
                if ws_flag == "ok":
                    sysp = (_WS_SYS_EXPLAIN if is_ann else _WS_SYS_POLISH) % ws_ctx
                    result = client.chat([{"role": "system", "content": sysp},
                                          {"role": "user", "content": text}])
                else:
                    result = client.explain(text) if is_ann else client.polish(text)
                payload = {"ok": True, "web_search": ws_flag}
                payload["note" if is_ann else "text"] = result
                self._send(200, json.dumps(payload, ensure_ascii=False),
                           "application/json; charset=utf-8")
            except _LLM_ERR as e:
                self._send(200, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
        # ---- RAG 启停：手动管理（编辑器退出不联动停，仅按钮触发） ----
        if u.path in ("/api/rag/start", "/api/rag/stop"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception:
                obj = {}
            try:
                if u.path == "/api/rag/start":
                    path = str(obj.get("path", "")).strip()
                    if not path or not os.path.isdir(path):
                        self._send(200, json.dumps(
                            {"ok": False, "error": "rag-assistant 路径无效或不存在，请检查 AI 设置中的路径"},
                            ensure_ascii=False), "application/json; charset=utf-8")
                        return
                    ok, msg = _rag_start_async(path)
                    self._send(200, json.dumps(
                        {"ok": ok, "message": msg if ok else "", "error": "" if ok else msg},
                        ensure_ascii=False), "application/json; charset=utf-8")
                else:
                    alive = _rag_stop()
                    if alive:
                        self._send(200, json.dumps(
                            {"ok": False, "error": "RAG 带看护自动重启（停止后端口仍存活），请在其运行窗口手动退出"},
                            ensure_ascii=False), "application/json; charset=utf-8")
                    else:
                        self._send(200, json.dumps(
                            {"ok": True, "message": "RAG 服务已停止", "kbs": []},
                            ensure_ascii=False), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
        # ---- RAG 检索增强润色/解释：query 拿上下文 → 拼 prompt → 走 LLM ----
        if u.path in ("/api/rag/annotate", "/api/rag/rewrite"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                obj = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "error": "请求体解析失败: %s" % e},
                                           ensure_ascii=False), "application/json; charset=utf-8")
                return
            try:
                if _ragc is None:
                    raise _LLM_ERR("rag_client.py 加载失败，详见 runtime/_ragc.err")
                client = _llm_from_request(obj)
                text = str(obj.get("text", ""))[:30000]
                if not text.strip():
                    self._send(200, json.dumps({"ok": False, "error": "选区内容为空"},
                                               ensure_ascii=False),
                               "application/json; charset=utf-8")
                    return
                if client.backend in ("ollama", "openai") and not client.model:
                    self._send(200, json.dumps(
                        {"ok": False, "error": "该后端需先在 LLM 设置中选择模型"},
                        ensure_ascii=False), "application/json; charset=utf-8")
                    return
                rag_cfg = _rag_from_request(obj)
                try:
                    # 检索 query 用选中文本截断（embedding 输入不宜过长）
                    hit = _ragc.RAGClient().query(rag_cfg["kb"], text[:2000], top_k=5)
                except _ragc.RAGClientError as e:
                    raise _LLM_ERR("RAG 检索失败（服务可能未启动，可在 AI 设置中启动）：%s" % e)
                if not hit.get("has_context"):
                    raise _LLM_ERR("知识库未检索到相关内容（可稍后重试，或在 AI 设置中更换知识库）")
                sysp = (_RAG_SYS_POLISH if u.path == "/api/rag/rewrite"
                        else _RAG_SYS_EXPLAIN) % (hit.get("context") or "")
                result = client.chat([{"role": "system", "content": sysp},
                                      {"role": "user", "content": text}])
                if u.path == "/api/rag/annotate":
                    self._send(200, json.dumps({"ok": True, "note": result}, ensure_ascii=False),
                               "application/json; charset=utf-8")
                else:
                    self._send(200, json.dumps({"ok": True, "text": result}, ensure_ascii=False),
                               "application/json; charset=utf-8")
            except _LLM_ERR as e:
                self._send(200, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return
        self._send(404, "not found")

    def log_message(self, *a):  # 静默
        pass


class Server(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.httpd = ReuseTCPServer(("127.0.0.1", PORT), Handler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        try:
            self.httpd.shutdown()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 系统托盘（纯 ctypes，无 pystray）
# ---------------------------------------------------------------------------
def build_tray(server):
    import ctypes
    from ctypes import wintypes

    # 部分 ctypes 分发版未导出指针宽类型，这里显式定义（Win64）
    LRESULT = ctypes.c_longlong
    UINT_PTR = ctypes.c_ulonglong

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    WM_TRAY = 0x0400 + 1
    WM_COMMAND = 0x0111
    WM_DESTROY = 0x0002
    WM_RBUTTONUP = 0x0205
    WM_LBUTTONUP = 0x0202

    NIF_MESSAGE = 0x1
    NIF_ICON = 0x2
    NIF_TIP = 0x4
    NIM_ADD = 0x0
    NIM_DELETE = 0x1

    user32.EnumWindows.restype = wintypes.BOOL
    _ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [_ENUMPROC, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                    wintypes.WPARAM, wintypes.LPARAM]

    TPM_RIGHTBUTTON = 0x0002
    TPM_RETURNCMD = 0x0100

    MF_STRING = 0x0000
    IDI_APPLICATION = 32512
    ID_TRAY = 1
    ID_NEW = 1001
    ID_EXIT = 1002

    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD), ("pt", POINT),
        ]

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT), ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HANDLE), ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_char * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]

    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadIconW.restype = wintypes.HICON
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, UINT_PTR, wintypes.LPCWSTR]
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPCVOID]
    user32.TrackPopupMenu.restype = wintypes.BOOL
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = LRESULT
    user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.restype = LRESULT
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

    hinst = kernel32.GetModuleHandleW(None)
    # 资源 ID 按 Windows 约定以 (LPWSTR)(UINT_PTR)id 形式传入
    # 托盘图标：优先用工具自带 md-editor.ico，取不到才退回系统默认
    hicon = None
    _ico = os.path.join(HERE, "md-editor.ico")
    try:
        if os.path.exists(_ico):
            user32.LoadImageW.restype = wintypes.HANDLE
            user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                          ctypes.c_uint, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_uint]
            hicon = user32.LoadImageW(None, _ico, 1, 16, 16, 0x10)
    except Exception:
        hicon = None
    if not hicon:
        hicon = user32.LoadIconW(0, ctypes.c_wchar_p(IDI_APPLICATION))

    class Tray:
        def __init__(self):
            self.hwnd = None
            self._wndproc = None  # 防止回调被 GC

        def wndproc(self, hwnd, msg, wparam, lparam):
            if msg == WM_TRAY and lparam == WM_LBUTTONUP:
                self.toggle_editor()
                return 0
            if msg == WM_TRAY and lparam == WM_RBUTTONUP:
                self.show_menu()
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        def find_editor_windows(self):
            found = []
            _ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                           wintypes.LPARAM)

            def cb(h, l):
                try:
                    if not user32.IsWindowVisible(h):
                        return True
                    n = user32.GetWindowTextLengthW(h)
                    if n > 0:
                        buf = ctypes.create_unicode_buffer(n + 1)
                        user32.GetWindowTextW(h, buf, n + 1)
                        if ("MDEditor" in buf.value
                                or "Markdown 编辑器" in buf.value):
                            found.append(h)
                except Exception:
                    pass
                return True

            try:
                user32.EnumWindows(_ENUMPROC(cb), 0)
            except Exception:
                pass
            return found

        def toggle_editor(self):
            wins = self.find_editor_windows()
            if not wins:
                webbrowser.open("http://127.0.0.1:%d/" % PORT)
                return
            h = wins[0]
            try:
                if user32.IsIconic(h):
                    user32.ShowWindow(h, 9)          # SW_RESTORE
                    user32.SetForegroundWindow(h)
                elif user32.GetForegroundWindow() == h:
                    user32.ShowWindow(h, 6)          # SW_MINIMIZE
                else:
                    user32.SetForegroundWindow(h)    # 前置已开窗口
            except Exception:
                pass

        def show_menu(self):
            hmenu = user32.CreatePopupMenu()
            user32.AppendMenuW(hmenu, MF_STRING, ID_NEW, "新建空白文档")
            user32.AppendMenuW(hmenu, MF_STRING, ID_EXIT, "退出")
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetForegroundWindow(self.hwnd)
            cmd = user32.TrackPopupMenu(hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                       pt.x, pt.y, 0, self.hwnd, None)
            user32.DestroyMenu(hmenu)
            if cmd == ID_NEW:
                webbrowser.open("http://127.0.0.1:%d/" % PORT)
            elif cmd == ID_EXIT:
                self.quit()

        def quit(self):
            # 关闭编辑器窗口（“退出”= 整个应用都关掉）
            for h in self.find_editor_windows():
                try:
                    user32.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE
                except Exception:
                    pass
            time.sleep(0.25)
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(nid)
            nid.hWnd = self.hwnd
            nid.uID = ID_TRAY
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            try:
                server.stop()
            except Exception:
                pass
            user32.PostQuitMessage(0)

        def run(self):
            self._wndproc = WNDPROC(self.wndproc)
            cls = WNDCLASSEXW()
            cls.cbSize = ctypes.sizeof(cls)
            cls.lpfnWndProc = self._wndproc
            cls.hInstance = hinst
            cls.lpszClassName = "MDViewerTrayWnd"
            atom = user32.RegisterClassExW(ctypes.byref(cls))
            if not atom:
                raise ctypes.WinError(ctypes.get_last_error())
            self.hwnd = user32.CreateWindowExW(
                0, "MDViewerTrayWnd", None, 0, 0, 0, 0, 0,
                None, None, hinst, None)
            if not self.hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(nid)
            nid.hWnd = self.hwnd
            nid.uID = ID_TRAY
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAY
            nid.hIcon = hicon
            nid.szTip = "Markdown 编辑器"
            if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                raise ctypes.WinError(ctypes.get_last_error())
            msg = MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

    Tray().run()




# ---------------------------------------------------------------------------
# 分页导出组装（py 全权负责；前端只提交渲染好的 body 与排版 CSS）
# ---------------------------------------------------------------------------
PAGED_PAGE_BOX = {"bc": "@bottom-center", "br": "@bottom-right", "bl": "@bottom-left",
                  "tc": "@top-center", "tr": "@top-right"}

# 命名纸张的纵向高度（mm，portrait）——用于推导图片版面 max-height
PAPER_H_MM = {"A0": 1189, "A1": 841, "A2": 594, "A3": 420, "A4": 297, "A5": 210,
              "B0": 1414, "B1": 1000, "B2": 707, "B3": 500, "B4": 353, "B5": 250,
              "Letter": 279.4, "Legal": 355.6, "Ledger": 431.8}
PAPER_W_MM = {"A0": 841, "A1": 594, "A2": 420, "A3": 297, "A4": 210, "A5": 148,
              "B0": 1000, "B1": 707, "B2": 500, "B3": 353, "B4": 250, "B5": 176,
              "Letter": 215.9, "Legal": 215.9, "Ledger": 279.4}

# 分页导出基础正文样式（镜像编辑器预览 .markdown-body；固定色值——
# 导出文档里 CSS 变量未定义，不能直接搬预览样式；排版规范借鉴
# Cogito_Scribit STYLE_GUIDE 一章（表格）与十一章（版面缩放纪律））：
#   * border-box / pre pre-wrap+anywhere / code anywhere（十一章 print 硬约束）
#   * 表格 width:100% + table-layout:auto + th/td 细边框 keep-all+anywhere（1.1）
#   * thead 跨页自动重复表头 + tr/li break-inside:avoid（表格切分行不腰斩）
#   * 引用编号索引表（表头=编号|引用|出处）ref-table 固定列宽 8%/47%/45%（1.2）
PAGED_BASE_CSS = """
*{box-sizing:border-box;}
.markdown-body{color:#222;line-height:1.7;word-wrap:break-word;overflow-wrap:anywhere;}
.markdown-body h1,.markdown-body h2,.markdown-body h3,.markdown-body h4,.markdown-body h5,.markdown-body h6{line-height:1.35;margin:1.4em 0 .6em;font-weight:650;}
.markdown-body h1{font-size:1.9em;border-bottom:1px solid #ddd;padding-bottom:.3em;}
.markdown-body h2{font-size:1.5em;border-bottom:1px solid #ddd;padding-bottom:.25em;}
.markdown-body h3{font-size:1.25em;}
.markdown-body h4{font-size:1.08em;}
.markdown-body p{margin:.85em 0;}
.markdown-body a{color:#4a6cf7;text-decoration:none;}
.markdown-body strong{font-weight:700;}
.markdown-body em{font-style:italic;}
.markdown-body del{opacity:.6;}
.markdown-body code{font-family:Consolas,monospace;font-size:.88em;background:#f4f4f4;padding:.15em .4em;border-radius:5px;overflow-wrap:anywhere;}
.markdown-body pre{background:#f4f4f4;border:1px solid #ddd;border-radius:6px;padding:14px 16px;margin:.9em 0;white-space:pre-wrap !important;overflow-wrap:anywhere !important;}
.markdown-body pre code{background:none;padding:0;font-size:.85em;line-height:1.6;}
.markdown-body blockquote{margin:.9em 0;padding:.4em 1em;border-left:3px solid #4a6cf7;background:#f5f7ff;border-radius:0 6px 6px 0;}
.markdown-body blockquote p{margin:.4em 0;}
.markdown-body ul,.markdown-body ol{margin:.7em 0;padding-left:1.6em;}
.markdown-body li{margin:.3em 0;break-inside:avoid;}
.markdown-body li.task{list-style:none;margin-left:-1.4em;}
.markdown-body li.task input{margin-right:.5em;vertical-align:middle;}
.markdown-body hr{border:none;border-top:1px solid #ddd;margin:1.6em 0;}
.markdown-body table{border-collapse:collapse;margin:1em 0;width:100%;table-layout:auto;font-size:.93em;break-inside:auto;}
.markdown-body thead{display:table-header-group;}
.markdown-body tr{break-inside:avoid;}
.markdown-body th,.markdown-body td{border:1px solid #bbb;padding:7px 12px;text-align:left;word-break:keep-all;overflow-wrap:anywhere;}
.markdown-body th{background:#f0f2f6;font-weight:650;}
.markdown-body img{display:block;margin:0 auto;max-width:100%;max-height:__IMGMAXH__mm;break-inside:avoid;}
.markdown-body p:has(>img){margin:0;}
.markdown-body table.ref-table{table-layout:fixed;}
.markdown-body table.ref-table th:nth-child(1),.markdown-body table.ref-table td:nth-child(1){width:8%;}
.markdown-body table.ref-table th:nth-child(2),.markdown-body table.ref-table td:nth-child(2){width:47%;}
.markdown-body table.ref-table th:nth-child(3),.markdown-body table.ref-table td:nth-child(3){width:45%;}
"""

# ---------- 超高长图切片（导出渲染期产物，源资产 SSOT 不动） ----------
# 规则：渲染高 ≤ 版心的图整图原子一页；高 > 版心的长截图按小条带竖切
# 续排（像表格跨页一样流入剩余空间），条带渲染高 = 版心高/3（3 条正好满页）。
# 切点吸附静默行（截图里的空白行/段间距），不切断文字行、不重叠不遗漏。
# 切片落 HERE/_slice/<sha1>/，同字节图幂等复用；PIL 缺失或读图失败原样保留（fail-closed）。
_SLICE_SNAP_MM = 8.0  # 切点吸附搜索窗口（半宽）


def _slice_tall_images(body_html, icb_w_mm, img_maxh_mm):
    img_re = re.compile(r'<img[^>]*?src="(/img\?path=[^"]+)"[^>]*?>')

    def _quiet_cuts(bright, h, nominal, win):
        # 在 nominal±win 内找亮度最平稳处下刀（空白行/段间隙）；找不到用原切点
        lo, hi = max(1, nominal - win), min(h - 1, nominal + win)
        best, best_d = nominal, None
        for i in range(lo, hi + 1):
            d = abs(bright[i] - bright[i - 1])
            if best_d is None or d < best_d:
                best, best_d = i, d
        return best

    def _repl(m):
        tag = m.group(0)
        try:
            from PIL import Image
        except ImportError:
            return tag
        path = urllib.parse.unquote(m.group(1).split("path=", 1)[1])
        if not os.path.isfile(path):
            return tag
        try:
            im = Image.open(path)
            im.load()
        except Exception:
            return tag
        w, h = im.size
        if w <= 1 or h <= 1:
            return tag
        # 宽度参数：style="width:N%"（前端 {N} 后缀产出）→ 版面宽度的 N%。无参数满宽。
        # 切片决策一切基于调整后的真实落地尺寸：eff_w_mm 为实际渲染宽，切片几何全按它换算
        pm = re.search(r'width:\s*([\d.]+)\s*%', tag)
        pct = 1.0
        if pm:
            try:
                pct = min(max(float(pm.group(1)), 0.0), 100.0) / 100.0
            except ValueError:
                pct = 1.0
            if pct <= 0.001:
                pct = 1.0  # 宽度为 0 的样式不当真，回满宽
        eff_w_mm = icb_w_mm * pct
        # 调整后渲染高不超版心 → 整图原子，不切
        if eff_w_mm * h / w <= img_maxh_mm:
            return tag
        import hashlib
        with open(path, "rb") as f:
            digest = hashlib.sha1(f.read()).hexdigest()[:12]
        # 条带像素高：渲染高 = 版心高/6（细条带续排，页面剩余留白上限 = 一条高）。
        # 1/3 版心实测留白过大（吸附后 3 条塞不进一页即剩 ~80mm 空白），故取 1/6
        strip_px = max(1, int(round(max(20.0, img_maxh_mm / 6.0) / eff_w_mm * w)))
        # 缓存键 = 内容 sha1 + 条带几何（strip_px）——几何参数变更时旧切片不复用
        digest = "%s-%d" % (digest, strip_px)
        n = (h + strip_px - 1) // strip_px
        gap = max(1, strip_px // 4)
        # 静默行亮度剖面：宽度压成 1px 即每行平均亮度（BILINEAR 均值）
        bright = list(im.convert("L").resize((1, h), Image.BILINEAR).getdata())
        win = max(1, int(round(_SLICE_SNAP_MM / eff_w_mm * w)))
        cuts = [0]
        for k in range(1, n):
            c = _quiet_cuts(bright, h, k * strip_px, win)
            if c <= cuts[-1] + gap:
                c = cuts[-1] + gap
            if c >= h - gap:
                break  # 剩余不足小条，并入末条
            cuts.append(c)
        cuts.append(h)
        out_dir = os.path.join(HERE, "_slice", digest)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError:
            return tag
        am = re.search(r'alt="([^"]*)"', tag)
        alt = am.group(1) if am else ""
        # 条带继承源图宽度约束：按同一百分比显示时，条带高度与切片几何严格一致
        style = ' style="width:%s%%"' % pm.group(1).strip() if pm else ""
        tags = []
        for i in range(len(cuts) - 1):
            fp = os.path.join(out_dir, "strip-%02d.png" % (i + 1))
            if not os.path.exists(fp):  # 幂等：已切过的直接复用
                try:
                    im.crop((0, cuts[i], w, cuts[i + 1])).save(fp, "PNG")
                except Exception:
                    return tag
            tags.append('<img src="/static/_slice/%s/strip-%02d.png" alt="%s"%s>'
                        % (digest, i + 1, alt, style))
        return "".join(tags)

    return img_re.sub(_repl, body_html)

PAGED_FILLER_TMPL = """
(function(){
  var tpl = __TPL__;
  var sel = __SEL__;
  var size = __SIZE__;
  var lastN = -1, stable = 0, done = false;
  var mo = new MutationObserver(function(){ if(!done) lastN = -1; });
  mo.observe(document.body, {childList:true, subtree:true});
  /* 纯目录页判定：页内有目录且无任何正文标题锚——目录不计入页码（6.4） */
  function tocOnly(pg){
    return !!(pg.querySelector('.md-toc-wrap') && !pg.querySelector('[id^="md-h-"]'));
  }
  function pageOf(el){
    var n = el;
    while(n && !(n.classList && n.classList.contains('pagedjs_page'))) n = n.parentNode;
    return n;
  }
  var iv = null;
  function startWatch(){
    if(iv) return;
    iv = setInterval(function(){
      var pgs = document.querySelectorAll('.pagedjs_page');
      var n = pgs.length;
      if(!n) return;
    if(n !== lastN){ lastN = n; stable = 0; return; }
    stable++;
    if(stable < 3) return;
    clearInterval(iv); mo.disconnect(); done = true;
    /* 分页完成标记：外部（headless 打印）据此判断"可以出 PDF 了"，
       不必靠 virtual-time-budget 猜时机——猜不准就会打出半截文档。 */
    document.documentElement.setAttribute('data-paged-done', '1');
    /* 页码映射：纯目录页不编号；正文页码 = 物理序 - 已跳过的目录页数 */
    var skip = [], shown = [], P = 0, c = 0, i;
    for(i=0;i<n;i++){ skip[i] = tocOnly(pgs[i]); if(!skip[i]) P++; }
    for(i=0;i<n;i++){ shown[i] = skip[i] ? 0 : ++c; }
    for(i=0;i<n;i++){
      if(skip[i]) continue;
      /* 外侧奇右偶左（6.4）；固定位置模式 odd/even 同盒 */
      var boxSel = (shown[i] % 2 === 1) ? sel.odd : sel.even;
      var el = pgs[i].querySelector(boxSel);
      if(el){
        el.textContent = tpl.replace('{p}', shown[i]).replace('{P}', P);
        el.style.fontSize = size + 'pt';
        el.style.color = '#666';
      }
    }
    /* 目录条目页码：按标题锚真实落页的显示页码回填（口径与页脚一致），
       点线引导 + 页码右对齐列（6.4 目录规范） */
    var links = document.querySelectorAll('.md-toc a[href^="#md-h-"]');
    for(i=0;i<links.length;i++){
      var href = links[i].getAttribute('href') || '';
      var dst = document.getElementById(decodeURIComponent(href.slice(1)));
      if(!dst) continue;
      var dpg = pageOf(dst);
      var idx = -1;
      for(var k=0;k<n;k++){ if(pgs[k] === dpg){ idx = k; break; } }
      if(idx < 0 || skip[idx]) continue;
      var dots = document.createElement('span');
      dots.className = 'toc-dots';
      var sp = document.createElement('span');
      sp.className = 'md-toc-pg';
      sp.textContent = shown[idx];
      links[i].appendChild(dots);
      links[i].appendChild(sp);
    }
  }, 300);
  }
  startWatch();   /* 立即开始判稳：字体事件在 headless 虚拟时间下可能永不就绪，
                     等它就等于永不开始（实测会出现「完成标记永不出现」）。 */
})();
"""


def _strip_tags(s):
    return re.sub(r"<[^>]+>", "", s)


# 导出时剥离仅供编辑期交互的节点（代码块复制按钮）：
# 独立 HTML 里 clipboard 在 file:// 下不可靠，按钮对读者也无意义。
# 在服务端统一剥离，两条导出出口（独立 HTML / 分页）都经过这里。
_EXPORT_ARTIFACT_RE = re.compile(r'<button[^>]*class="copy-btn"[^>]*>.*?</button>', re.S)


def _strip_export_artifacts(html):
    return _EXPORT_ARTIFACT_RE.sub("", html)




# R1 新语法样式（导出用固定色值：导出文档内未定义 CSS 变量；
# 与 markdown-editor.html 主 <style> 中的同名规则一一对应，改一处必须同步改另一处）
SYNTAX_CSS = (
    ".markdown-body mark{background:#f5d76e;color:inherit;padding:.05em .25em;border-radius:3px;}"
    ".markdown-body sup,.markdown-body sub{font-size:.72em;line-height:0;}"
    ".markdown-body dl{margin:.9em 0;}"
    ".markdown-body dt{font-weight:650;margin-top:.6em;}"
    ".markdown-body dd{margin:.2em 0 .2em 1.6em;}"
    ".markdown-body .callout{margin:.9em 0;padding:.6em 1em;border-left:4px solid #4a6cf7;"
    "border-radius:0 6px 6px 0;background:#f5f7ff;}"
    ".markdown-body .callout-title{margin:0 0 .35em;font-weight:700;font-size:.92em;}"
    ".markdown-body .callout-note{border-left-color:#4a6cf7;background:#f5f7ff;}"
    ".markdown-body .callout-tip{border-left-color:#2f9e5f;background:#eefaf2;}"
    ".markdown-body .callout-important{border-left-color:#8a5cf5;background:#f3eefe;}"
    ".markdown-body .callout-warning{border-left-color:#d99a4e;background:#fdf5e9;}"
    ".markdown-body .callout-caution{border-left-color:#d9534f;background:#fdeceb;}"
    ".markdown-body .callout p{margin:.3em 0;}"
    ".markdown-body .fn-ref{font-size:.72em;line-height:0;margin-left:.1em;}"
    ".markdown-body .fn-ref a{text-decoration:none;}"
    ".markdown-body .footnotes{margin-top:2em;font-size:.92em;color:#666;}"
    ".markdown-body .footnotes ol{margin:.3em 0;padding-left:1.4em;}"
    ".markdown-body .footnotes li{margin:.3em 0;}"
    ".markdown-body .fn-back{text-decoration:none;margin-left:.3em;}"
    ".markdown-body .fn-sep{border-top:1px solid #ddd;}"
)


def _hljs_theme_css():
    """导出内联 highlight.js 主题（亮色）。

    导出用的 bodyHtml 来自预览 DOM，代码块里已经带着 `hljs-*` span；
    不注入主题 CSS，导出的代码就全是黑字（预览正常、导出裸奔）。
    独立 HTML 必须单文件可分，故内联而非 <link>。
    """
    p = os.path.join(HERE, "highlight", "styles", "github.css")
    try:
        return io.open(p, encoding="utf-8").read()
    except Exception:
        return ""


def _doc_title_or_fallback(doc_title, fallback):
    """front matter 的 title 只在**确实是字符串**时才算数。

    YAML 里 `title: 2026` 会被解析成数字、`title:` 后跟列表会成数组，
    直接 .strip() 会抛 AttributeError 让导出 500——元数据是尽力而为的，
    拿不到就回退首个 <h1>，不该让整次导出失败。
    """
    return (doc_title if isinstance(doc_title, str) else "").strip() or fallback


# 工具探测缓存：/api/tools 每次页面加载都会调一次，而探测要起几个子进程。
# 缓存 30s，避免刷新页面/多标签把机器拖慢（工具装/卸是低频动作）。
_TOOLS_CACHE = {"t": 0.0, "sig": None, "val": None}


def _is_builtin_doc(p):
    """内置文档（使用指南 / 版权声明）住在应用目录 docs/ 下。

    导出会往安装目录里写产物：既污染安装（下次升级被覆盖、卸载删不干净），
    也可能因为装在 Program Files 而写不进去。引导用户先「另存为」。
    """
    try:
        docs_dir = os.path.normcase(os.path.normpath(os.path.join(HERE, "docs")))
        target = os.path.normcase(os.path.normpath(os.path.abspath(p)))
        return target.startswith(docs_dir + os.sep)
    except Exception:
        return False


def _tools_probe_cached(cfg, ttl=30.0):
    import md_tools
    sig = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
    c = _TOOLS_CACHE
    now = time.time()
    if c["val"] is not None and c["sig"] == sig and (now - c["t"]) < ttl:
        return c["val"]
    val = md_tools.probe_all(cfg)
    c.update({"t": now, "sig": sig, "val": val})
    return val


def build_standalone_html(md_path, body_html, ts_css, doc_title=""):
    """普通 .html 导出组装（py 全权：图片路径还原 + katex css + 排版样式）"""
    katex_css = ""
    kp = os.path.join(HERE, "katex", "katex.min.css")
    if os.path.exists(kp):
        katex_css = io.open(kp, encoding="utf-8").read().replace(
            "url(fonts/", "url(/static/katex/fonts/")
    def _proxy(m):
        p = urllib.parse.unquote(m.group(1)).replace("\\", "/")
        return 'src="file:///' + p + '"'
    body = re.sub(r'src="/img\?path=([^"]+)"', _proxy, body_html)
    body = _strip_export_artifacts(body)
    if md_path:
        mdir = os.path.dirname(md_path).replace("\\", "/")
        body = re.sub(r'src="(?!https?:|file:|/|#)([^"]+)"',
                      lambda m: 'src="file:///%s/%s"' % (mdir, m.group(1)), body)
    m1 = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", body)
    title = re.sub(r"<[^>]+>", "", m1.group(1)).strip() if m1 else "未命名文档"
    # front matter 的 title 优先（前端 render() 已把 front matter 剥离出 bodyHtml，
    # 故只有在结构化数据里才拿得到，直接传进来）
    title = _doc_title_or_fallback(doc_title, title)
    ts = ts_css.replace("#preview", ".markdown-body")
    html = ('<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="UTF-8"><title>__TITLE__</title>'
        "<style>__KATEX__</style><style>div.md-math-block{overflow-x:auto;margin:.8em 0;}"
        "span.md-math-inline{white-space:nowrap;}__SYNTAX____TS__</style>"
        '<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",'
        '"Microsoft YaHei",sans-serif;max-width:820px;margin:40px auto;padding:0 20px;'
        'line-height:1.7;color:#222;}'
        'h1,h2{border-bottom:1px solid #eee;padding-bottom:.3em;}'
        'code{background:#f4f4f4;padding:.15em .4em;border-radius:4px;font-family:Consolas,monospace;}'
        'pre{background:#f4f4f4;padding:14px;border-radius:8px;overflow:auto;}'
        'blockquote{border-left:3px solid #4a6cf7;background:#f5f7ff;padding:.4em 1em;margin:1em 0;}'
        'table{border-collapse:collapse;width:100%;}th,td{border:1px solid #ddd;padding:7px 12px;}'
        'img{max-width:100%;}a{color:#4a6cf7;}</style></head><body class="markdown-body">__BODY__</body></html>')
    html = html.replace("__TITLE__", html_module.escape(title))
    html = html.replace("__KATEX__", katex_css)
    html = html.replace("__SYNTAX__", SYNTAX_CSS + _hljs_theme_css())
    html = html.replace("__TS__", ts)
    html = html.replace("__BODY__", body)
    return html

def build_paged_html(md_path, body_html, ts_css, page_cfg, doc_title=""):
    paper = page_cfg.get("paper", "A4")
    pw, ph = page_cfg.get("pw", ""), page_cfg.get("ph", "")
    if paper == "custom" and pw and ph:
        size_str = "%smm %smm" % (pw, ph)
        try:
            paper_h = float(ph)
        except (TypeError, ValueError):
            paper_h = PAPER_H_MM["A4"]
    else:
        size_str = paper
        paper_h = PAPER_H_MM.get(paper, 297)
    mt = page_cfg.get("mt", 25)
    mr = page_cfg.get("mr", 18)
    mb = page_cfg.get("mb", 25)
    ml = page_cfg.get("ml", 18)
    # 图片版面预算：max-height = 纸高 − 上下边距 − 2mm 安全余量。
    # 1mm 余量曾引爆长截图事故：图 246mm + 打印版 p/img 自身边距 > 247mm 版心，
    # 图在任一页都放不下 → Paged.js 反复推页产出连续空白页、图被溢出裁掉。
    # 现打印版 img margin=0 且 p:has(>img) margin=0，2mm 余量兜底舍入误差。
    # 浏览器对 img 的 max-width/max-height 约束天然保持宽高比——
    # 宽超按宽缩、高超按高缩，图片不超出版面。
    try:
        img_maxh = max(20.0, float(paper_h) - float(mt) - float(mb) - 2.0)
    except (TypeError, ValueError):
        img_maxh = 245.0
    # 版心宽（切片条带的渲染宽度基准）
    try:
        paper_w = (float(pw) if (paper == "custom" and pw)
                   else float(PAPER_W_MM.get(paper, 210.0)))
        icb_w = max(40.0, paper_w - float(mr) - float(ml))
    except (TypeError, ValueError):
        icb_w = 174.0
    pn = page_cfg.get("pn", {}) or {}
    toc_cfg = page_cfg.get("toc", {}) or {}

    # @page：纸张 + 边距 + 页码 margin box（占位空白，正文文本由填充脚本写入；
    # 页码形态照抄书册规范 STRUCTURE_GUIDE 6.4：默认外侧奇右偶左、纯数字、9pt 灰）
    page_css = "@page{size:%s;margin:%smm %smm %smm %smm;" % (size_str, mt, mr, mb, ml)
    if pn.get("on") == "on":
        sz = pn.get("size", 9)
        if pn.get("pos", "outer") == "outer":
            page_css += ('@bottom-right{content:" ";font-size:%spt;}'
                         '@bottom-left{content:" ";font-size:%spt;}' % (sz, sz))
        else:
            box = PAGED_PAGE_BOX.get(pn.get("pos"), "@bottom-center")
            page_css += '%s{content:" ";font-size:%spt;}' % (box, sz)
    page_css += "}"
    # 分页规则（STRUCTURE_GUIDE 6.2 书籍标准，逐条对齐 PRINT_CSS）：
    # h1 每篇独立起页；小节标题不落页末；段落防孤立行 2/2；
    # 单行 bullet 1/1（widows 2 会永久推页留白）；hr 禁断但不加 break-before
    #（与 h2 break-after 形成保护链会整块推页留半页空白，2026-08-28 判例）；
    # 纵向结构（table/pre）允许内容单元间拆页，横向结构（blockquote）不拆
    page_css += (
        ".md-toc-wrap{break-after:page;}"
        "h1{break-before:page;}"
        "h2,h3,h4{break-after:avoid;}"
        "p{orphans:2;widows:2;}li{orphans:1;widows:1;}"
        "hr{break-inside:avoid;break-after:avoid;}"
        "table{break-inside:auto;}blockquote{break-inside:avoid;}"
    )

    # TOC + 锚点
    heads = []

    body_html = _strip_export_artifacts(body_html)   # 复制按钮不进导出（见 _strip_export_artifacts）

    def _head(m):
        lvl = int(m.group(1))
        inner = m.group(2)
        heads.append((lvl, inner))
        return '<h%s id="md-h-%d">%s</h%s>' % (lvl, len(heads), inner, lvl)

    body = re.sub(r"<h([123])[^>]*>([\s\S]*?)</h\1>", _head, body_html)
    toc_html = ""
    if toc_cfg.get("on") == "on" and heads:
        items = "".join(
            '<div class="toc-l%d"><a href="#md-h-%d">%s</a></div>' % (lvl, i, txt)
            for i, (lvl, txt) in enumerate(heads, 1))
        solo = "break-before:page;break-after:page;" if toc_cfg.get("solo", True) else "break-after:page;"
        toc_html = ('<div class="md-toc-wrap" style="%s"><nav class="md-toc">'
                    '<div class="md-toc-title">目 录</div>%s</nav></div>') % (solo, items)
        if toc_cfg.get("pos", "top") == "afterh1":
            body = re.sub(r"(<h1[\s\S]*?</h1>)", lambda m: m.group(1) + toc_html, body, count=1)
        else:
            body = toc_html + body

    # 引用编号索引表识别（STYLE_GUIDE 1.2）：表头 = 编号|引用|出处 → ref-table 固定列宽
    body = re.sub(
        r'<table>(\s*<thead>\s*<tr>\s*<th[^>]*>\s*编号\s*</th>\s*'
        r'<th[^>]*>\s*引用\s*</th>\s*<th[^>]*>\s*出处\s*</th>)',
        r'<table class="ref-table">\1', body)

    # 超高长图切片：高 > 版心的图切小条带续排（切点吸附静默行）
    body = _slice_tall_images(body, icb_w, img_maxh)

    # 基础正文样式（表格边框/图片版面/断行纪律）——此前缺失是表格边框
    # 在分页导出中消失的根因；置于 ts_css 之前，排版设置的 !important 仍可覆盖
    base_css = PAGED_BASE_CSS.replace("__IMGMAXH__", ("%.2f" % img_maxh))

    # 资源内嵌（全部本地，离线可用）
    katex_css = ""
    kp = os.path.join(HERE, "katex", "katex.min.css")
    if os.path.exists(kp):
        katex_css = io.open(kp, encoding="utf-8").read().replace(
            "url(fonts/", "url(/static/katex/fonts/")
    paged_js = ""
    pp = os.path.join(HERE, "pagedjs", "paged.polyfill.min.js")
    if os.path.exists(pp):
        paged_js = io.open(pp, encoding="utf-8").read().replace("</script", "<\\/script")

    # 页码填充脚本（Paged.js 分页完成、DOM 稳定后填入；模板/位置/字号由配置注入。
    # 外侧模式：奇页右下、偶页左下（书册规范 6.4），sel 传 odd/even 两个选择器）
    pn_pos = pn.get("pos", "outer")
    if pn_pos == "outer":
        sel = {"odd": ".pagedjs_margin-bottom-right .pagedjs_margin-content",
               "even": ".pagedjs_margin-bottom-left .pagedjs_margin-content"}
    else:
        _s = ".pagedjs_margin-%s .pagedjs_margin-content" % PAGED_PAGE_BOX.get(
            pn_pos, "bottom-center").replace("@", "")
        sel = {"odd": _s, "even": _s}
    filler_vals = {
        "__TPL__": json.dumps(pn.get("tpl", "{p}"), ensure_ascii=False),
        "__SEL__": json.dumps(sel),
        "__SIZE__": json.dumps(str(pn.get("size", 9))),
    }
    filler = PAGED_FILLER_TMPL
    for k, v in filler_vals.items():
        filler = filler.replace(k, v)
    filler = filler.replace("</script", "<\\/script")

    # 目录版式（STRUCTURE_GUIDE 6.4：点线引导 + 页码右对齐列；
    # 11.4 几何纪律：页码列统一右缘、点线与页码留间距不重叠）
    toc_css = (
        ".md-toc-title{font-size:1.7em;font-weight:700;text-align:center;margin:0 0 1.4em;}"
        ".md-toc .toc-l1{font-weight:600;margin:.9em 0 .25em;}"
        ".md-toc .toc-l2{padding-left:1.6em;}"
        ".md-toc .toc-l3{padding-left:3.2em;}"
        ".md-toc a{display:flex;align-items:baseline;text-decoration:none;color:inherit;padding:.18em 0;}"
        ".md-toc .toc-dots{flex:1;min-width:1.5em;border-bottom:1px dotted #999;"
        "margin:0 6px;transform:translateY(-.25em);}"
        ".md-toc .md-toc-pg{white-space:pre;font-variant-numeric:tabular-nums;}"
    )

    m1 = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", body)
    title = _strip_tags(m1.group(1)) if m1 else "未命名文档"
    title = title.strip() or "未命名文档"
    title = _doc_title_or_fallback(doc_title, title)

    html = (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="UTF-8"><title>%s</title>'
        "<style>%s</style><style>%s</style><style>%s%s%s%s</style>"
        '</head><body class="markdown-body"><div id="paged-content" class="markdown-body">%s</div>'
        "<script>%s</script>"
        "<script>%s</script></body></html>"
    ) % (
        html_module.escape(title),
        page_css,
        base_css,
        katex_css,
        toc_css,
        SYNTAX_CSS + _hljs_theme_css(),
        ts_css,
        body,
        paged_js,
        filler,
    )
    return html


if HERE not in sys.path:
    sys.path.insert(0, HERE)
try:
    from md_assets import materialize_images
    from md_assets import materialize_into
except Exception:
    import traceback as _tb
    try:
        with open(os.path.join(HERE, "runtime", "md_assets.err"), "a",
                  encoding="utf-8") as _ef:
            _ef.write(_tb.format_exc() + "\n")
    except Exception:
        pass
    materialize_images = None
    materialize_into = None


_SHELL_FOLDERS_KEY = ("Software\\Microsoft\\Windows\\CurrentVersion\\"
                      "Explorer\\User Shell Folders")


def _shell_folder(regval, fallback=""):
    """读取 HKCU User Shell Folders 中的真实路径。
    这样能正确处理 OneDrive 重定向（例如桌面实际在 D:\\...\\OneDrive\\Desktop），
    而不是想当然地拼 C:\\Users\\<name>\\Desktop。失败则用 fallback。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            _SHELL_FOLDERS_KEY) as k:
            v, _ = winreg.QueryValueEx(k, regval)
            v = os.path.expandvars(v)
            if v and os.path.isdir(v):
                return v
    except Exception:
        pass
    return fallback


def _common_dirs():
    home = os.path.expanduser("~")
    cands = {
        "desktop": _shell_folder("Desktop", os.path.join(home, "Desktop")),
        "docs": _shell_folder("Personal", os.path.join(home, "Documents")),
        "downloads": _shell_folder(
            "{374DE290-123F-4565-9164-39C4925E467B}",
            os.path.join(home, "Downloads")),
        "home": home,
    }
    return {k: v for k, v in cands.items() if v and os.path.isdir(v)}


_LAST_DOC_DIR = [""]
_LAST_PING = [time.time()]          # 最近一次页面心跳时间
_START_TIME = [time.time()]         # 服务启动时间（用于宽限期）
_BYE_AT = [0.0]                     # 所有会话均已卸载的时间（0=无待退出）
_LIVE_SESSIONS = {}                 # 活跃页面会话: token -> 最后心跳时间
                                    # （token 由前端每标签生成，见 markdown-editor.html
                                    #  sessionToken；多窗口/多标签共享本服务）


def _live_tok(qs):
    """从 query string 取会话 token；缺失/损坏时归一为固定占位（兼容旧页面）"""
    try:
        return (urllib.parse.parse_qs(qs or "").get("tok", [""])[0] or "").strip() or "_legacy"
    except Exception:
        return "_legacy"


def _keepalive_ping(tok):
    """会话心跳：登记存活并撤销"全体待退出"。闲置（切标签/最小化）绝不触发退出。"""
    now = time.time()
    _LIVE_SESSIONS[tok] = now
    _LAST_PING[0] = now
    _BYE_AT[0] = 0.0                 # 任一会话恢复心跳 => 撤销待退出（刷新/重开场景）


def _keepalive_bye(tok):
    """会话卸载：只下线本会话；仅当【最后一个】会话下线才进入待退出倒计时。"""
    _LIVE_SESSIONS.pop(tok, None)
    try:
        with io.open(os.path.join(HERE, "runtime", "lifecycle.log"),
                     "a", encoding="utf-8") as _f:
            _f.write("%s bye tok=%s live=%d bye_at=%s\n"
                     % (time.strftime("%H:%M:%S"), tok, len(_LIVE_SESSIONS),
                        time.strftime("%H:%M:%S", time.localtime(_BYE_AT[0]))))
    except Exception:
        pass
    if _LIVE_SESSIONS:
        _BYE_AT[0] = 0.0             # 还有其他窗口/标签活着，服务继续保活
    elif _BYE_AT[0] == 0.0:
        _BYE_AT[0] = time.time()


def _run_picker(script, tmpname):
    """在独立进程中弹选择框；结果经临时文件回传（空串=取消或不可用）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    picker = os.path.join(here, script)
    if not os.path.exists(picker):
        return ""
    tmp = os.path.join(tempfile.gettempdir(), tmpname)
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except Exception:
        pass
    exe_dir = os.path.dirname(sys.executable)
    py_exe = os.path.join(exe_dir, "python.exe")
    if not os.path.exists(py_exe):
        py_exe = sys.executable
    try:
        subprocess.run([py_exe, picker, tmp], timeout=900,
                       creationflags=0x08000000)
    except Exception:
        pass
    try:
        return io.open(tmp, encoding="utf-8").read().strip()
    except Exception:
        return ""


def _save_dialog_subprocess(title, default_name, initdir, ext):
    """原生「保存文件」框（GetSaveFileNameW）；返回用户选择的完整路径，取消返回空串。

    与 `_pick_file_subprocess` 同一模式：独立子进程弹窗（避免阻塞服务线程），
    路径经临时文件回传。**过滤串由 _savefile.py 内部按扩展名构造**——Win32 的
    filter 必须含内嵌 NUL，而命令行参数不允许 NUL（会抛 embedded null character，
    弹框根本出不来，用户看到的是「已取消导出」）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    picker = os.path.join(here, "_savefile.py")
    if not os.path.exists(picker):
        return ""
    ext = (ext or "").lower().lstrip(".")
    if ext not in ("docx", "pdf"):
        return ""
    tmp = os.path.join(tempfile.gettempdir(), "md_save_dialog.txt")
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except Exception:
        pass
    exe_dir = os.path.dirname(sys.executable)
    py_exe = os.path.join(exe_dir, "python.exe")
    if not os.path.exists(py_exe):
        py_exe = sys.executable
    try:
        subprocess.run([py_exe, picker, tmp, title, default_name, initdir, ext],
                       timeout=900, creationflags=0x08000000)
    except Exception:
        pass
    try:
        return io.open(tmp, encoding="utf-8").read().strip()
    except Exception:
        return ""


def _norm_out_path(out_path, md_path, ext):
    """校验前端指定的导出路径：绝对路径、父目录存在、扩展名正确、不能是内置文档目录。

    返回 (ok, path_or_error)。
    """
    if not out_path:
        stem = os.path.splitext(os.path.basename(md_path))[0]
        return True, os.path.join(os.path.dirname(os.path.abspath(md_path)),
                                  stem + "." + ext)
    if not os.path.isabs(out_path):
        return False, "导出路径必须是绝对路径"
    p = os.path.abspath(out_path)
    if os.path.splitext(p)[1].lower() != "." + ext:
        return False, "导出路径必须是 .%s 文件" % ext
    parent = os.path.dirname(p)
    if not os.path.isdir(parent):
        return False, "目标目录不存在：%s" % parent
    if _is_builtin_doc(p):
        return False, "不能导出到安装目录 docs/ 下，请换一个目录"
    return True, p


_R_WRAPPER = r'''
a <- commandArgs(trailingOnly = TRUE)
out_txt <- a[1]; err_txt <- a[2]; out_png <- a[3]; code_file <- a[4]; meta <- a[5]
code <- paste(readLines(code_file, warn = FALSE, encoding = "UTF-8"), collapse = "\n")
con_err <- file(err_txt, open = "wt", encoding = "UTF-8")
sink(out_txt, split = FALSE)
sink(con_err, type = "message")
err <- NULL
res <- NULL
png(out_png, width = 1200, height = 800, res = 150)
res <- tryCatch(withVisible(eval(parse(text = code), envir = globalenv())),
                error = function(e) { err <<- conditionMessage(e); NULL })
if (is.null(err)) {
  v <- res$value
  if (inherits(v, "ggplot")) print(v)
  else if (is.function(v)) v()
}
invisible(dev.off())
sink(type = "message"); sink()
try(close(con_err), silent = TRUE)
writeLines(c(paste0("haserr=", if (is.null(err)) "0" else "1"),
             paste0("err=", if (is.null(err)) "" else gsub("[\r\n]+", " ", err))), meta)
'''

_R_DIR_NAME = "r"


def _r_tmp_dir():
    d = os.path.join(HERE, "runtime", "tmp", _R_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _png_is_blank(path):
    """判定 png 是不是空白图。

    png 设备即使一行图都没画也会生成文件（纯白），不判就会出现一个空白图块。
    实测空白图**0 个暗像素**、真图数千以上，故按暗像素计数判定。
    PIL 不可用时退化成体积阈值（空白约 1KB）。
    """
    try:
        from PIL import Image
        im = Image.open(path).convert("L")
        return sum(im.histogram()[:250]) == 0
    except Exception:
        try:
            return os.path.getsize(path) < 2500
        except Exception:
            return True


def _prune_r_pngs(keep=50):
    try:
        d = _r_tmp_dir()
        pngs = [os.path.join(d, n) for n in os.listdir(d) if n.endswith(".png")]
        pngs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for p in pngs[keep:]:
            try:
                os.remove(p)
            except Exception:
                pass
    except Exception:
        pass


def _run_r_code(code, rscript, timeout=60):
    """跑用户 R 代码：返回 {ok, stdout, stderr, image, error}。

    设计要点（都是踩出来的）：
    - 用户代码写独立 `.R` 文件、wrapper 用 readLines + eval(parse(text=))，
      **不做字符串插值**——中文、引号、注释、`#` 都原样；
    - `sink(file)` 抓 stdout；stderr 的 sink **必须先开连接**（传文件名会报
      "'file' must be NULL or an already open connection"）；
    - 图写 png 设备，事后按暗像素判是否真画（见 _png_is_blank）；
    - 超时/timeout 由调用方 kill，异常统一转成人话。
    """
    d = _r_tmp_dir()
    uid = uuid.uuid4().hex[:12]
    code_path = os.path.join(d, uid + ".R")
    run_path = os.path.join(d, uid + "-run.R")
    out_txt = os.path.join(d, uid + ".out")
    err_txt = os.path.join(d, uid + ".err")
    meta = os.path.join(d, uid + ".meta")
    png = os.path.join(d, uid + ".png")
    try:
        with open(code_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(code)
        with open(run_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_R_WRAPPER)
        try:
            subprocess.run([rscript, "--vanilla", run_path,
                            out_txt, err_txt, png, code_path, meta],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout,
                           creationflags=0x08000000)
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": "", "image": "",
                    "error": "执行超时（%d 秒）：代码可能陷入死循环" % timeout}
        so = ""
        se = ""
        try:
            so = io.open(out_txt, encoding="utf-8", errors="replace").read()[:20000]
        except Exception:
            pass
        try:
            se = io.open(err_txt, encoding="utf-8", errors="replace").read()[:20000]
        except Exception:
            pass
        has_err, err_msg = False, ""
        try:
            for ln in io.open(meta, encoding="utf-8", errors="replace").read().splitlines():
                if ln.startswith("haserr="):
                    has_err = ln.split("=", 1)[1].strip() == "1"
                elif ln.startswith("err="):
                    err_msg = ln.split("=", 1)[1].strip()
        except Exception:
            pass
        image = ""
        if os.path.isfile(png) and not _png_is_blank(png):
            image = png
        if has_err:
            return {"ok": False, "stdout": so, "stderr": se, "image": image,
                    "error": err_msg or "R 执行出错"}
        return {"ok": True, "stdout": so, "stderr": se, "image": image, "error": ""}
    finally:
        for p in (code_path, run_path, out_txt, err_txt, meta):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        if not os.path.isfile(png):
            pass
        else:
            _prune_r_pngs()


def _run_py_code(code, timeout=60):
    """跑用户 Python 代码（用**内置便携运行时**，零额外依赖）。

    只返回 stdout/stderr：打包运行时里没有 matplotlib，画图不在支持范围内，
    不假装支持（要画图请用 R 代码块）。
    """
    d = os.path.join(HERE, "runtime", "tmp", "py")
    os.makedirs(d, exist_ok=True)
    uid = uuid.uuid4().hex[:12]
    script = os.path.join(d, uid + ".py")
    try:
        with open(script, "w", encoding="utf-8", newline="\n") as f:
            f.write(code)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        try:
            r = subprocess.run([sys.executable, "-X", "utf8", script],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout, cwd=d, env=env,
                               creationflags=0x08000000)
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": "",
                    "error": "执行超时（%d 秒）：代码可能陷入死循环" % timeout}
        so = (r.stdout or "")[:20000]
        se = (r.stderr or "")[:20000]
        if r.returncode != 0:
            return {"ok": False, "stdout": so, "stderr": se,
                    "error": (se.strip().splitlines() or ["执行失败"])[-1][:600]}
        return {"ok": True, "stdout": so, "stderr": se, "error": ""}
    finally:
        try:
            if os.path.exists(script):
                os.remove(script)
        except Exception:
            pass


def _pick_file_subprocess(initdir=""):
    """原生"打开文件"框（GetOpenFileNameW，过滤 .md/.smd）；独立子进程弹窗，
    路径经临时文件回传（与 _pick_dir_subprocess 同模式）。取消/失败返回空串。"""
    here = os.path.dirname(os.path.abspath(__file__))
    picker = os.path.join(here, "_pickfile.py")
    if not os.path.exists(picker):
        return ""
    tmp = os.path.join(tempfile.gettempdir(), "mdeditor_pickfile.txt")
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except Exception:
        pass
    exe_dir = os.path.dirname(sys.executable)
    py_exe = os.path.join(exe_dir, "python.exe")
    if not os.path.exists(py_exe):
        py_exe = sys.executable
    try:
        subprocess.run([py_exe, picker, tmp, initdir or ""], timeout=900,
                       creationflags=0x08000000)
    except Exception:
        pass
    try:
        return io.open(tmp, encoding="utf-8").read().strip()
    except Exception:
        return ""


def _pick_dir_subprocess():
    """只使用现代文件夹选择框（IFileOpenDialog + FOS_PICKFOLDERS）。
    用户取消 -> 返回空串，不再回退（回退会二次弹老式框，用户已明确弃用）。
    现代框不可用时返回空串并写诊断日志。"""
    r = _run_picker("_pickdir_modern.py", "mdeditor_pickdir2.txt")
    if r == "@CANCEL@":
        _pickdir_log("modern: 用户取消")
        return ""
    if r:
        _pickdir_log("modern: 选中 %s" % r)
        return r
    _pickdir_log("modern: 不可用/无返回（未回退）")
    return ""


def _pickdir_log(msg):
    try:
        import time as _t
        with io.open(os.path.join(HERE, "runtime", "pickdir.log"), "a",
                     encoding="utf-8") as f:
            f.write("%s %s\n" % (_t.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _idle_watchdog(grace=None, check=0.5):
    """只在【所有窗口/标签都确实关闭】时退出服务。

    多窗口/多标签共享本后端，会话以 token 区分（前端每标签生成，见
    markdown-editor.html sessionToken；/api/ping、/api/bye 带 ?tok=）：
    - 主判定：全部会话都收到卸载通知(/api/bye，pagehide→sendBeacon)后
      进入宽限倒计时；宽限期内出现任何新会话心跳（刷新/重开）即撤销。
    - 保活：只要还有任一会话存活（_LIVE_SESSIONS 非空），服务绝不退出
      ——关闭某个窗口不影响其它窗口（这正是多开的核心语义）。
    - 兜底：WebView2 被直接拽掉时 pagehide 跑不到、bye 发不出，该会话
      按最后心跳停滞超 orphan 宽限（默认 5 分钟）做幽灵清理；全部会话
      清光后按 max(最后心跳, 服务启动) 超 orphan 同样回收，防僵尸端口。
      后台标签页心跳节流最长约 1 分钟，5 分钟足够保守，不误杀
      最小化/切走的窗口。

    明确不做的事：**不做"空闲超时"判定**。
    切换标签页、最小化、长时间不操作都不等于关闭 —— 只要会话还在，
    服务就活着。可用环境变量 MD_EXIT_GRACE/MD_EXIT_ORPHAN_GRACE
    覆盖宽限期（便于测试）。"""
    if grace is None:
        grace = float(os.environ.get("MD_EXIT_GRACE", "8"))
    orphan = float(os.environ.get("MD_EXIT_ORPHAN_GRACE", "300"))
    _START_TIME[0] = time.time()
    if not _auto_stop_enabled():
        return

    def _do_stop(reason):
        try:
            with io.open(os.path.join(HERE, "runtime", "lifecycle.log"),
                         "a", encoding="utf-8") as f:
                f.write("%s %s -> stop service\n"
                        % (time.strftime("%H:%M:%S"), reason))
        except Exception:
            pass
        if _smd is not None:
            try:
                _smd.clear_tmp()   # 会话结束，清 .smd 解包缓存
            except Exception:
                pass
        os._exit(0)

    while True:
        time.sleep(check)
        now = time.time()
        # 幽灵清理：无 bye 的会话心跳停滞超过 orphan（页面/窗口被强杀）
        for t in [t for t, ts in _LIVE_SESSIONS.items() if now - ts >= orphan]:
            del _LIVE_SESSIONS[t]
        if _LIVE_SESSIONS:
            continue          # 仍有存活窗口/标签，服务保活
        bye = _BYE_AT[0]
        if not bye:
            # 兜底：从未 bye 且已无存活会话，心跳断流超 orphan 宽限。
            # 基准取「最后心跳 / 服务启动」的较大者——页面从未打开过的
            # 孤儿服务（起服务后 5 分钟无页面接入）同样回收。
            if now - max(_LAST_PING[0], _START_TIME[0]) >= orphan:
                _do_stop("heartbeat lost (page killed without bye)")
            continue
        if now - bye < grace:
            continue
        # 宽限期内又收到过心跳 => 是刷新/重开，撤销退出
        if now - _LAST_PING[0] < grace:
            continue
        _do_stop("page closed")


def _auto_stop_enabled():
    """runtime/settings.json 里的 auto_stop（默认开启）。"""
    try:
        import json as _json
        p = os.path.join(HERE, "runtime", "settings.json")
        d = _json.loads(io.open(p, encoding="utf-8").read())
        return bool(d.get("auto_stop", True))
    except Exception:
        return True


def main():
    if _smd is not None:
        try:
            _smd.clear_tmp()   # 启动清掉上次会话的 .smd 解包缓存（数据以 .smd 为准）
        except Exception:
            pass
    srv = Server()
    srv.start()
    atexit.register(srv.stop)
    # 空闲自动退出：页面关闭后无人使用，服务自行结束（无需手动 md_stop）
    threading.Thread(target=_idle_watchdog, daemon=True).start()
    ev = threading.Event()
    try:
        ev.wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
