# -*- coding: utf-8 -*-
"""OpenAI 后端 + 联网查询 UI 行为验证（playwright）：
backend 联动显隐、联网区块显隐、保存落盘。settings.json 重定向临时文件。"""
import threading
import time
import sys
import os
import json
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = ["md_server.py"]
import md_server  # noqa: E402

TMP = tempfile.mkdtemp(prefix="md_llm_ui_")
md_server.SETTINGS_PATH = os.path.join(TMP, "settings.json")

httpd = md_server.ReuseTCPServer(("127.0.0.1", 18766), md_server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

fails = []


def check(name, cond, detail=""):
    print("%-52s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto("http://127.0.0.1:18766/")
    pg.wait_for_timeout(600)

    pg.click("#btnLLM")
    pg.wait_for_timeout(900)
    check("llmOverlay visible", pg.eval_on_selector("#llmOverlay", "el=>!el.hidden"))

    # 默认 lmstudio：key 行隐藏
    check("lmstudio: key row hidden",
          pg.eval_on_selector("#llmKeyRow", "el=>el.style.display==='none'"))

    # 切 openai：key 行显示、placeholder 跟随、地址自动填默认
    pg.select_option("#llmBackend", "openai")
    pg.wait_for_timeout(300)
    check("openai: key row visible",
          not pg.eval_on_selector("#llmKeyRow", "el=>el.style.display==='none'"))
    check("openai: base placeholder",
          pg.eval_on_selector("#llmBase", "el=>el.placeholder") == "https://api.openai.com/v1")
    check("openai: base auto default",
          pg.eval_on_selector("#llmBase", "el=>el.value") == "https://api.openai.com/v1")
    # openai 无 key 拉模型 → llmTestMsg 报错含 API Key（LM 在线也拦）
    msg = pg.eval_on_selector("#llmTestMsg", "el=>el.textContent")
    check("openai: models fetch blocked without key", "API Key" in msg, msg)

    # 填 key + 模型后保存
    pg.fill("#llmKey", "sk-ui-test")


    # 联网区块：默认关 + duckduckgo → key 行全隐
    check("ws default: enabled unchecked",
          not pg.eval_on_selector("#wsEnabled", "el=>el.checked"))
    check("ws duckduckgo: all key rows hidden",
          all(pg.eval_on_selector(sel, "el=>el.style.display==='none'")
              for sel in ("#wsKeyRow", "#wsBingRow", "#wsGoogleRow", "#wsCustomRow")))

    # 切 tavily → wsKeyRow 显示；切 google → google 行显示
    pg.select_option("#wsBackend", "tavily")
    check("ws tavily: key row visible",
          not pg.eval_on_selector("#wsKeyRow", "el=>el.style.display==='none'"))
    pg.select_option("#wsBackend", "google")
    check("ws google: google row visible",
          not pg.eval_on_selector("#wsGoogleRow", "el=>el.style.display==='none'")
          and pg.eval_on_selector("#wsKeyRow", "el=>el.style.display==='none'"))

    # 开联网 + 填 tavily key + 保存 → settings.json 校验
    pg.select_option("#wsBackend", "tavily")
    pg.fill("#wsKey", "tvly-ui-test")
    pg.check("#wsEnabled")
    pg.fill("#wsMax", "5")
    pg.click("#llmSave")
    pg.wait_for_timeout(600)
    saved = json.load(open(md_server.SETTINGS_PATH, encoding="utf-8"))
    llm = saved.get("llm", {})
    ws = llm.get("web_search", {})
    check("saved: api_key persisted", llm.get("api_key") == "sk-ui-test", str(llm.get("api_key")))
    check("saved: ws enabled/backend/key/max",
          ws.get("enabled") is True and ws.get("backend") == "tavily"
          and ws.get("api_key") == "tvly-ui-test" and ws.get("max_results") == 5, str(ws))

    # 重开面板：字段回读
    pg.click("#btnLLM")
    pg.wait_for_timeout(900)
    check("reopened: backend openai restored",
          pg.eval_on_selector("#llmBackend", "el=>el.value") == "openai")
    check("reopened: api_key restored",
          pg.eval_on_selector("#llmKey", "el=>el.value") == "sk-ui-test")
    check("reopened: ws enabled restored",
          pg.eval_on_selector("#wsEnabled", "el=>el.checked") is True)
    check("reopened: ws tavily + key restored",
          pg.eval_on_selector("#wsBackend", "el=>el.value") == "tavily"
          and pg.eval_on_selector("#wsKey", "el=>el.value") == "tvly-ui-test")

    check("no page JS errors", not errors, str(errors[:2]))
    b.close()

httpd.shutdown()
print("\nRESULT: %s (%d fail)" % ("PASS" if not fails else "FAIL", len(fails)))
sys.exit(1 if fails else 0)