# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""串行跑 tests/ 下的全部回归测试，逐文件超时保护。

为什么逐文件、前台、串行：本机 R/Python 长链路静默崩溃过一次，整体一次调用会让
已经跑通的用例跟着归零，也分不清是谁挂的。这里一个文件一个进程，超时就杀，
失败只留最后一个失败用例的尾巴，别把整屏日志倒给使用者。

用途：`python\\python.exe tests\\run_all.py [--only 子串] [--timeout 秒] [--list]`
退出码：全通过 0，有失败/超时 1。
"""
import argparse
import io
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

try:                                     # Windows 控制台默认 GBK，中文日志会炸在这里
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKIP_NAMES = {"run_all.py"}


def discover(only=None):
    out = []
    for name in sorted(os.listdir(HERE)):
        if not (name.startswith("_test_") and name.endswith(".py")):
            continue
        if name in SKIP_NAMES:
            continue
        if only:
            keys = [k.strip().lower() for k in only.split(",") if k.strip()]
            if keys and not any(k in name.lower() for k in keys):
                continue
        out.append(name)
    return out


def tail(text, n=12):
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


# 用例会自己 bind 这几个端口（18766 后端 / 18777 浏览器级 / 18790 截图流水线）。
# 上一个用例的进程刚被 kill 时端口可能还没真正释放，下一个用例 bind 上去要么
# 失败、要么请求被路由到即将退出的旧进程——实测会造成「与代码无关的 FAIL」。
# 所以每个用例开跑前等端口安静下来；等不到就明确说一句，别让失败原因靠猜。
PORTS = (18766, 18777, 18790)


def _port_busy(port):
    s = socket.socket()
    s.settimeout(0.25)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def wait_ports_free(timeout=15.0):
    end = time.time() + timeout
    busy = [p for p in PORTS if _port_busy(p)]
    while busy and time.time() < end:
        time.sleep(0.3)
        busy = [p for p in PORTS if _port_busy(p)]
    return busy


def run_one(name, timeout):
    path = os.path.join(HERE, name)
    busy = wait_ports_free()
    if busy:
        print("        端口仍被占用：%s（用例可能因此失败）" % busy)
    started = time.time()
    try:
        r = subprocess.run([PY, path], cwd=ROOT, capture_output=True, timeout=timeout,
                           text=True, encoding="utf-8", errors="replace")
        cost = time.time() - started
        if r.returncode == 0:
            return "PASS", cost, ""
        if r.returncode == 77:                   # 约定的 SKIP 码：缺可选依赖，不算失败
            return "SKIP", cost, tail(r.stdout, 2)
        return "FAIL", cost, tail(r.stdout + "\n" + r.stderr)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", time.time() - started, "超过 %ds 未结束" % timeout
    except Exception as e:                       # 启动失败也要记成一件事，不吞掉
        return "ERROR", time.time() - started, str(e)


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--only", default="", help="只跑文件名含该子串的用例（多个用逗号分隔）")
    ap.add_argument("--timeout", type=int, default=300, help="单个文件超时秒数（默认 300）")
    ap.add_argument("--list", action="store_true", help="只列出将运行的用例")
    a = ap.parse_args(argv[1:])

    names = discover(a.only)
    if not names:
        print("没有匹配的用例")
        return 1
    if a.list:
        for n in names:
            print(n)
        return 0

    print("运行 %d 个用例（单文件超时 %ds，工作目录 %s）\n" % (len(names), a.timeout, ROOT))
    rows = []
    for i, name in enumerate(names, 1):
        print("[%2d/%d] %-28s " % (i, len(names), name), end="", flush=True)
        status, cost, detail = run_one(name, a.timeout)
        print("%-8s %5.1fs" % (status, cost))
        if detail:
            for ln in detail.splitlines():
                print("        " + ln)
        rows.append((name, status, cost))

    bad = [r for r in rows if r[1] not in ("PASS", "SKIP")]
    print("\n—" * 30)
    print("合计 %d：PASS %d / SKIP %d / FAIL %d / TIMEOUT %d / ERROR %d，用时 %.1fs"
          % (len(rows),
             sum(1 for r in rows if r[1] == "PASS"),
             sum(1 for r in rows if r[1] == "SKIP"),
             sum(1 for r in rows if r[1] == "FAIL"),
             sum(1 for r in rows if r[1] == "TIMEOUT"),
             sum(1 for r in rows if r[1] == "ERROR"),
             sum(r[2] for r in rows)))
    if bad:
        print("未通过：" + "、".join(r[0] for r in bad))
        return 1
    print("全部通过（SKIP 为缺可选依赖，非失败）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
