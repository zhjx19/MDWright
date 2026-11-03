# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""MDWright 内嵌窗口应用
- pywebview 开原生窗口指向本地服务（无浏览器 UI）
- 自带 WebView2 内核优先（runtime/WebView2），不存在则用系统内核
- 暴露 py API 供页面直接调用（原生目录/保存对话框选路径、常用目录、窗口控制；
  写盘一律由页面走服务端路由——桥不落盘，SSOT 单一实现）
用法：pythonw md_app.pyw [要打开的 .md 路径]
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 18766
sys.path.insert(0, HERE)

BUNDLED_RUNTIME = os.path.join(HERE, "runtime", "WebView2")
USER_DATA = os.path.join(HERE, "runtime", "userdata")
WIN_CONF = os.path.join(HERE, "runtime", "window.json")
SETTINGS = os.path.join(HERE, "runtime", "settings.json")
LOG = os.path.join(HERE, "runtime", "md_app.log")


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def load_settings():
    """可选设置：disable_gpu=true 时改用软件渲染（排障用）。"""
    try:
        d = json.loads(io.open(SETTINGS, encoding="utf-8").read())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def ensure_default_settings():
    if os.path.exists(SETTINGS):
        return
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        io.open(SETTINGS, "w", encoding="utf-8").write(json.dumps({
            "_comment": "内嵌窗口设置。disable_gpu=true 改用软件渲染（界面卡顿时可试）",
            "disable_gpu": False
        }, ensure_ascii=False, indent=2))
    except Exception:
        pass


def service_alive(min_ver=0):
    try:
        d = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:%d/api/version" % PORT, timeout=0.1).read().decode())
        return int(d.get("version", 0)) >= min_ver if min_ver else True
    except Exception:
        return False


def ensure_service(start=True):
    """等服务就绪；start=False 时只等不拉起（启动器已经起过服务了）。

    start=False 是并行启动的关键：`md_launch` 会在 spawn 服务后立刻拉起本窗口，
    两件事同时跑。此时若这里再 spawn 一次，Windows 的 SO_REUSEADDR 会让两个
    服务同时绑定 18766（请求随机落到其中一个），所以必须区分「谁负责起服务」。
    """
    if service_alive():
        return True
    if start:
        try:
            exe = os.path.join(HERE, "python", "pythonw.exe")
            if not os.path.exists(exe):
                exe = sys.executable
            subprocess.Popen([exe, os.path.join(HERE, "_md_run.py")],
                             cwd=HERE, creationflags=0x08000000)
        except Exception as e:
            log("start service failed: %s" % e)
            return False
    end = time.time() + 15
    while time.time() < end:
        if service_alive():
            return True
        time.sleep(0.05)
    return False


def _open_browser(target):
    """内嵌窗口起不来时至少把页面开出来（浏览器模式仍然完整可用）。"""
    q = ("?file=" + urllib.parse.quote(target)) if target else ""
    try:
        webbrowser.open("http://127.0.0.1:%d/%s" % (PORT, q))
        log("fallback: opened in default browser")
    except Exception as e:
        log("fallback browser open failed: %s" % e)


def load_window_size():
    try:
        d = json.loads(io.open(WIN_CONF, encoding="utf-8").read())
        return int(d.get("w", 1360)), int(d.get("h", 880))
    except Exception:
        return 1360, 880


def save_window_size(w, h):
    try:
        os.makedirs(os.path.dirname(WIN_CONF), exist_ok=True)
        io.open(WIN_CONF, "w", encoding="utf-8").write(
            json.dumps({"w": int(w), "h": int(h)}))
    except Exception:
        pass


class Api:
    """供前端通过 window.pywebview.api.* 直接调用。"""

    def __init__(self):
        self.window = None

    # ---- 文件/目录对话框（原生，返回完整路径）----
    def pick_folder(self, last_dir=""):
        try:
            import webview
            res = self.window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=last_dir if last_dir and os.path.isdir(last_dir) else "")
            if res:
                return res[0] if isinstance(res, (list, tuple)) else res
        except Exception as e:
            log("pick_folder err: %s" % e)
        return ""

    def pick_save_path(self, default_name="", last_dir=""):
        """另存为：只弹原生保存对话框选路径，写盘由页面统一走服务端
        /api/save-as（SSOT——物化/契约改写/回传只在服务端一份实现）。
        返回完整路径；取消返回空串。缺后缀补 .md，已带 .md/.smd 尊重用户。

        起始目录不能留空：留空时系统会退到**进程工作目录**（安装目录），
        用户一路回车就把稿子存进了 Program Files。优先上次目录 → 文档 → 主目录。
        """
        start = last_dir if last_dir and os.path.isdir(last_dir) else ""
        if not start:
            for cand in (os.path.join(os.path.expanduser("~"), "Documents"),
                         os.path.expanduser("~")):
                if cand and os.path.isdir(cand):
                    start = cand
                    break
        try:
            import webview
            kwargs = dict(
                directory=start,
                save_filename=default_name or "未命名.md")
            # 文件类型限定为 .md/.smd（pywebview 6.x：每个元素须为完整 '描述 (通配)' 格式）
            try:
                dlg = self.window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    file_types=("Markdown (*.md;*.smd)",), **kwargs)
            except Exception as e2:
                # 过滤参数任何形态的失败（版本差异/格式差异）都回退无过滤调用，保证可用性
                log("pick_save_path file_types fallback: %s" % e2)
                dlg = self.window.create_file_dialog(webview.SAVE_DIALOG, **kwargs)
            res = dlg
            if not res:
                return ""
            path = res if isinstance(res, str) else (res[0] if res else "")
            if not path:
                return ""
            low = path.lower()
            if not (low.endswith(".md") or low.endswith(".smd")):
                path += ".md"
            return path
        except Exception as e:
            log("pick_save_path err: %s" % e)
            return ""

    def common_dirs(self):
        home = os.path.expanduser("~")
        cand = {"docs": os.path.join(home, "Documents"),
                "desktop": os.path.join(home, "Desktop"),
                "downloads": os.path.join(home, "Downloads"),
                "home": home}
        return {k: v for k, v in cand.items() if os.path.isdir(v)}

    def api_version(self):
        log("api_version() called BY PAGE -> bridge OK")
        return {"port": PORT, "embedded": True}

    def restart_backend(self):
        """页面发现后端断了会调这里：重新把本地服务拉起来。

        内嵌模式下页面自己没法起进程，而后端可能因为空闲回收、崩溃、或端口被
        别的实例抢走后释放而消失。没有这条通路，窗口只能一直显示「后端已断开」。
        """
        try:
            ok = ensure_service()
            log("restart_backend -> %s" % ok)
            return {"ok": bool(ok)}
        except Exception as e:
            log("restart_backend failed: %s" % e)
            return {"ok": False, "error": str(e)}

    # ---- 窗口控制（托盘/页面可调用）----
    def minimize(self):
        try:
            self.window.minimize()
        except Exception:
            pass
        return True

    def toggle(self):
        """最小化 <-> 恢复"""
        try:
            if self.window.events:  # 占位
                pass
        except Exception:
            pass
        return True

    def close_app(self):
        threading.Thread(target=self._shutdown, daemon=True).start()
        return True

    def _shutdown(self):
        time.sleep(0.15)
        try:
            self.window.destroy()
        except Exception:
            pass



def on_closing():
    try:
        w = webview.windows[0] if webview.windows else None
        if w is not None:
            save_window_size(w.width, w.height)
    except Exception:
        pass


def _install_hang_watchdog():
    """卡死自动取证（心跳式）：后台线程每 2 秒醒一次，
    若实际醒来延迟明显超出预期，说明主线程/GIL 被长时间占用（=卡死），
    此时把【所有线程的调用栈】写入 runtime/hang.log。
    只在检测到异常时写文件，不做无条件 dump。"""
    def _worker():
        import sys
        import traceback
        import time as _t
        path = os.path.join(HERE, "runtime", "hang.log")
        while True:
            try:
                t0 = _t.time()
                _t.sleep(2.0)
                delay = (_t.time() - t0) - 2.0
                if delay > 1.5:           # 睡 2 秒却晚了 1.5 秒以上
                    with io.open(path, "a", encoding="utf-8",
                                 errors="replace") as f:
                        f.write("\n===== 检测到阻塞 %.1fs  %s =====\n"
                                % (delay, _t.strftime("%H:%M:%S")))
                        for tid, frame in sys._current_frames().items():
                            f.write("--- thread %s ---\n" % tid)
                            traceback.print_stack(frame, file=f)
            except Exception:
                pass
    try:
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        log("hang watchdog armed (heartbeat) -> runtime/hang.log")
    except Exception as e:
        log("hang watchdog failed: %s" % e)


def _open_dropped(win, path):
    try:
        win.evaluate_js("window.mdwDropOpen && window.mdwDropOpen(%s)"
                        % json.dumps(path))
    except Exception as e:
        log("drop open failed: %s" % e)


def _drop_path_from_uri(uri):
    """file:///C:/x.md → C:\\x.md；非 .md/.smd 返回空串。"""
    try:
        u = urllib.parse.urlparse(uri or "")
        if u.scheme.lower() != "file":
            return ""
        p = urllib.parse.unquote(u.path or "")
        if u.netloc and u.netloc.lower() not in ("", "localhost"):
            p = "//" + u.netloc + p
        elif len(p) > 2 and p[0] == "/" and p[2] == ":":
            p = p[1:]
        p = os.path.normpath(p)
        return p if os.path.splitext(p)[1].lower() in (".md", ".smd") else ""
    except Exception:
        return ""


def _enable_native_file_drop(win):
    """把 Windows 的「拖 .md 到窗口」接到页面。

    WebView2 的 File 对象不暴露本机路径，但**默认允许外部拖放**：把文件拖进
    窗口时它会尝试打开一个 file:// 新窗口/导航。我们不去关 AllowExternalDrop
    （关掉反而会显示禁止图标、宿主也收不到 DragDrop），而是拦下这两个动作，
    从 URI 里还原完整路径，交给页面的 window.mdwDropOpen。
    """
    state = {"installed": False, "handlers": None, "last": (0.0, "")}

    def open_once(p):
        now = time.time()
        last_t, last_p = state["last"]
        if p == last_p and now - last_t < 1.0:
            return
        state["last"] = (now, p)
        threading.Thread(target=_open_dropped, args=(win, p), daemon=True).start()

    def install(core):
        if state["installed"] or core is None:
            return

        def on_new_window(sender, e):
            p = _drop_path_from_uri(e.Uri)
            if p:
                try:
                    e.Handled = True
                except Exception:
                    pass
                open_once(p)

        def on_nav(sender, e):
            p = _drop_path_from_uri(e.Uri)
            if p:
                try:
                    e.Cancel = True
                except Exception:
                    pass
                open_once(p)
            elif e.Uri and e.Uri.lower().startswith("file:"):
                # 拖进来的不是 .md/.smd：别让窗口变成一段纯文本
                try:
                    e.Cancel = True
                except Exception:
                    pass

        core.NewWindowRequested += on_new_window
        core.NavigationStarting += on_nav
        state["handlers"] = (on_new_window, on_nav)   # 防 GC
        state["installed"] = True
        log("native file drop enabled (corewebview2)")

    def poke(window):
        try:
            from System import Action
            from webview.platforms import winforms as wf
            form = wf.BrowserView.instances.get(win.uid)
            if form is None:
                return

            def work():
                try:
                    view = getattr(form, "webview", None)
                    install(view.CoreWebView2 if view is not None else None)
                except Exception as e:
                    log("drop hook ui failed: %s" % e)

            form.Invoke(Action(work))
        except Exception as e:
            log("drop hook poke failed: %s" % e)

    try:
        win.events.loaded += poke
    except Exception as e:
        log("drop hook register failed: %s" % e)


def _patch_new_window_open():
    """pywebview 默认把 NewWindowRequested 的 URI 全丢给系统浏览器。

    文件拖放也会走这个回调：文档已经在应用里打开了，浏览器却又弹一个
    file:/// 页。这里只对 file:// 静默；http(s) 等外部链接保持原行为。
    """
    try:
        from webview.platforms import edgechromium
        orig = edgechromium.EdgeChrome.on_new_window_request

        def on_new_window_request(self, sender, args):
            try:
                uri = str(args.get_Uri())
            except Exception:
                uri = ""
            if uri.lower().startswith("file:"):
                try:
                    args.set_Handled(True)
                except Exception:
                    pass
                return
            return orig(self, sender, args)

        edgechromium.EdgeChrome.on_new_window_request = on_new_window_request
        log("new-window file:// suppress patched")
    except Exception as e:
        log("new-window patch failed: %s" % e)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    q = ("?file=" + urllib.parse.quote(target)) if target else ""
    log("start, target=%s" % target)
    _install_hang_watchdog()

    # 自带内核优先（必须在 webview 初始化前设好环境变量）
    if os.path.isdir(BUNDLED_RUNTIME) and os.path.exists(
            os.path.join(BUNDLED_RUNTIME, "msedgewebview2.exe")):
        os.environ["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = BUNDLED_RUNTIME
        log("using bundled runtime")
    else:
        log("bundled runtime missing, fallback to system")
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", USER_DATA)

    # 预导入 pywebview（pythonnet 约 0.7s）与等服务并行：这段开销正好藏在
    # 服务启动后面，不占关键路径。
    _wv = {}

    def _preload():
        try:
            import webview as _w
            _wv["m"] = _w
        except Exception as e:
            _wv["err"] = e

    _loader = threading.Thread(target=_preload, daemon=True)
    _loader.start()

    # 启动器刚 spawn 过服务时不要重复起（见 ensure_service 注释）
    launcher_spawned = os.environ.get("MDW_LAUNCH_SPAWNED") == "1"
    if not ensure_service(start=not launcher_spawned):
        log("service unavailable, abort")
        return 1
    _loader.join(timeout=20)

    webview = _wv.get("m")
    if webview is None:
        log("pywebview import failed: %s" % _wv.get("err"))
        _open_browser(target)
        return 1
    _patch_new_window_open()
    api = Api()
    w, h = load_window_size()
    try:
        win = webview.create_window("墨匠 MDWright", "http://127.0.0.1:%d/%s" % (PORT, q),
                                    width=w, height=h, min_size=(900, 600),
                                    js_api=api)
        api.window = win
        win._serializable = False  # 打断 js_api 序列化循环引用（api.window ↔ win.js_api），否则 get_functions 无限递归卡死
        win.events.closing += on_closing
        _enable_native_file_drop(win)
        ensure_default_settings()
        st = load_settings()
        start_args = ["--disable-gpu"] if st.get("disable_gpu") else None
        if start_args:
            log("disable_gpu settings -> software rendering")
        webview.start(icon=os.path.join(HERE, "mdwright.ico"), args=start_args)
    except Exception as e:
        # 常见于 WebView2 运行时缺失 / pythonnet 被安全策略挡住：至少开浏览器，
        # 而不是像以前那样写一行 fatal 就没了下文（用户看不到任何窗口）。
        log("embedded window failed: %s" % e)
        _open_browser(target)
        return 1
    log("window closed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log("fatal: %s" % e)
        sys.exit(1)
