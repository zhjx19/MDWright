# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 or later.
"""运行结果侧车：三种落点、代码改动失效、坏文件容错、.smd 整理后不丢。

落点口径见 spec §4.2：单开 runs/ 目录，避开 .smd 保存时的 assets 孤儿清理。
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
import shutil
import sys
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, _ROOT)
import md_runs  # noqa: E402
import _smd     # noqa: E402

fails = []


def check(name, cond, detail=""):
    print("%-46s %s %s" % (name, "PASS" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        fails.append(name)


PNG = _os.path.join(_ROOT, "docs", "screenshots", "writing.png")


def main():
    tmp = tempfile.mkdtemp(prefix="mdruns-")
    try:
        # ── .md：落点、图片、读回 ────────────────────────────
        doc = _os.path.join(tmp, "a.md")
        io.open(doc, "w", encoding="utf-8").write("# t\n")
        entry = md_runs.save_output("r", "x <- 1", {"stdout": "[1] 1\n", "image": PNG},
                                    doc, "")
        store_dir = _os.path.join(tmp, "a.md.assets", "runs")
        check(".md 侧车落位", _os.path.isfile(_os.path.join(store_dir, "run-outputs.json")),
              store_dir)
        check(".md 图片落到 runs/",
              bool(entry.get("image")) and _os.path.isfile(
                  _os.path.join(store_dir, _os.path.basename(entry["image"]))), str(entry))

        back = md_runs.read_outputs(doc, "")
        check("读回按代码匹配", any(b["code"] == "x <- 1" for b in back), str(back)[:200])
        hit = [b for b in back if b["code"] == "x <- 1"][0]
        check("读回时图片解析成绝对路径",
              bool(hit.get("imageAbs")) and _os.path.isfile(hit["imageAbs"]),
              str(hit.get("imageAbs")))
        check("代码改动后匹配不到",
              not any(b["code"] == "x <- 2" for b in back), "")

        # 重复跑同一段代码：覆盖而不是追加
        md_runs.save_output("r", "x <- 1", {"stdout": "[1] 2\n"}, doc, "")
        back2 = md_runs.read_outputs(doc, "")
        check("同代码重跑覆盖旧条目",
              len([b for b in back2 if b["code"] == "x <- 1"]) == 1, str(len(back2)))

        # ── 坏文件容错 ───────────────────────────────────────
        io.open(_os.path.join(store_dir, "run-outputs.json"), "w",
                encoding="utf-8").write("{坏 json")
        check("侧车损坏当空", md_runs.read_outputs(doc, "") == [], "")

        # ── .smd：包内 runs/，且整理（compact）后仍在 ─────────
        smd = _os.path.join(tmp, "b.smd")
        src = _os.path.join(tmp, "pack")
        _os.makedirs(_os.path.join(src, "assets"), exist_ok=True)
        io.open(_os.path.join(src, "doc.md"), "w", encoding="utf-8").write("# t\n")
        shutil.copy2(PNG, _os.path.join(src, "assets", "keep.png"))
        io.open(_os.path.join(src, "doc.md"), "a", encoding="utf-8").write("\n![](assets/keep.png)\n")
        _smd.pack_from_dir(smd, _os.path.join(src, "doc.md"), _os.path.join(src, "assets"))

        md_runs.save_output("r", "y <- 2", {"stdout": "ok\n", "image": PNG}, smd, "")
        with zipfile.ZipFile(smd) as z:
            names = z.namelist()
        check(".smd 包内有 runs/ 侧车",
              any(n.startswith("runs/") for n in names), str(names)[:200])

        bdir = _smd.base_dir_for(smd)
        # 造一个孤儿资产 → 触发 compact 全量重建（最容易丢 runs/ 的路径）
        io.open(_os.path.join(bdir, "assets", "orphan.png"), "wb").write(b"x" * 4000)
        _smd.save_from_dir(smd, bdir)
        with zipfile.ZipFile(smd) as z:
            names2 = z.namelist()
        check(".smd 整理后 runs/ 未被丢弃",
              any(n.startswith("runs/") for n in names2), str(names2)[:240])
        check(".smd 整理后孤儿资产已清", "assets/orphan.png" not in names2, "")
        check(".smd 读回仍能拿到输出",
              any(b["code"] == "y <- 2" for b in md_runs.read_outputs(smd, "")), "")

        # ── 未命名 ───────────────────────────────────────────
        md_runs.save_output("python", "z = 3", {"stdout": "3\n"}, "", "tok123")
        tmp_store = _os.path.join(_ROOT, "runtime", "tmp", "runs", "tok123",
                                  "run-outputs.json")
        check("未命名落点在 runtime/tmp/runs",
              _os.path.isfile(tmp_store), tmp_store)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        md_runs.shutdown_all()
    print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
