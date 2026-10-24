# -*- coding: utf-8 -*-
"""RAG 前端 UI 行为验证（playwright）：按钮初始置灰、AI 设置面板 RAG 管理区
状态/控件、保存写盘 rag 段。settings.json 重定向到临时文件。"""
# --- 测试入口 shim：本文件在 tests/ 下。便携运行时（python311._pth）不会把 script dir
# 加进 sys.path，所以 tests/ 与仓库根两个都显式挂上，跨用例 import 与根模块 import 才成立 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import threading
import time
import sys
import os
import json
import tempfile

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import md_server  # noqa: E402

TMP = tempfile.mkdtemp(prefix="md_rag_ui_")
md_server.SETTINGS_PATH = os.path.join(TMP, "settings.json")

httpd = md_server.ReuseTCPServer(("127.0.0.1", 18766), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


try:
    from playwright.sync_api import sync_playwright  # noqa: E402
except ImportError:
    # 没装 playwright 不算代码坏：这是缺一件可选开发工具。返回 77，run_all 记为 SKIP。
    print("SKIP 需要 playwright：pip install playwright && python -m playwright install chromium")
    sys.exit(77)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto("http://127.0.0.1:18766/")
    pg.wait_for_timeout(800)

    check("selRagPolish exists & disabled while offline",
          pg.eval_on_selector("#selRagPolish", "el=>el.disabled"))
    check("annRagAi exists & disabled while offline",
          pg.eval_on_selector("#annRagAi", "el=>el.disabled"))
    check("selPolish (plain) stays enabled",
          not pg.eval_on_selector("#selPolish", "el=>el.disabled"))

    # 打开 AI 设置面板
    pg.click("#btnLLM")
    pg.wait_for_timeout(1200)
    check("llmOverlay visible", pg.eval_on_selector("#llmOverlay", "el=>!el.hidden"))
    check("ragPath prefilled with default",
          pg.eval_on_selector("#ragPath", "el=>el.value") == md_server.RAG_DEFAULTS["path"],
          pg.eval_on_selector("#ragPath", "el=>el.value"))
    state_txt = pg.eval_on_selector("#ragState", "el=>el.textContent")
    check("ragState shows offline/starting (8767 down)", "离线" in state_txt or "启动中" in state_txt,
          state_txt)
    check("ragKb has auto-route option",
          pg.eval_on_selector("#ragKb option", "el=>el.textContent") == "（自动路由）")
    check("ragStart enabled when offline",
          not pg.eval_on_selector("#ragStart", "el=>el.disabled"))
    check("ragStop disabled when offline",
          pg.eval_on_selector("#ragStop", "el=>el.disabled"))

    # 修改 RAG 路径并保存 → settings.json 应含 rag 段
    pg.fill("#ragPath", "D:/playwright/rag")
    pg.select_option("#ragKb", "")
    pg.click("#llmSave")
    pg.wait_for_timeout(600)
    saved = json.load(open(md_server.SETTINGS_PATH, encoding="utf-8"))
    check("settings.json has rag section after save",
          saved.get("rag", {}).get("path") == "D:/playwright/rag", str(saved.get("rag")))
    check("llm section still saved alongside",
          isinstance(saved.get("llm"), dict) and "backend" in saved["llm"])
    check("llmOverlay closed after save", pg.eval_on_selector("#llmOverlay", "el=>el.hidden"))

    # 刷新按钮触发重探测（离线 → 状态行仍为离线，不报错）
    pg.click("#btnLLM")
    pg.wait_for_timeout(900)
    pg.click("#ragRefresh")
    pg.wait_for_timeout(900)
    state_txt2 = pg.eval_on_selector("#ragState", "el=>el.textContent")
    check("ragRefresh keeps offline state clean", "离线" in state_txt2 or "启动中" in state_txt2,
          state_txt2)

    b.close()

httpd.shutdown()
print("\nRESULT: %s (%d fail)" % ("PASS" if not fails else "FAIL", len(fails)))
sys.exit(1 if fails else 0)