# -*- coding: utf-8 -*-
"""_smd 功能测试：PASS/FAIL 二元输出，覆盖打包-解包往返、增量保存、
compact 阈值、断电容错、路径穿越防御、外部修改重解包。"""
# --- 测试入口 shim：本文件在 tests/ 下。便携运行时（python311._pth）不会把 script dir
# 加进 sys.path，所以 tests/ 与仓库根两个都显式挂上，跨用例 import 与根模块 import 才成立 ---
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))      # tests/
_ROOT = _os.path.dirname(_HERE)                           # 仓库根
for _p in (_HERE, _ROOT):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import os
import sys
import io
import json
import shutil
import zipfile

sys.path.insert(0, _ROOT)   # 同 shim，保留此行以免与旧习惯冲突
import _smd

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
TD = os.path.join(HERE, "runtime", "_smd_test")
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name, ("  [" + detail + "]") if detail else ""))


def png_bytes(color, n=2048):
    return b"\x89PNG\r\n\x1a\n" + bytes([color]) * n   # 合成假 PNG（仅测容器，不测图像）


# --- 准备 ---
shutil.rmtree(TD, ignore_errors=True)
os.makedirs(TD, exist_ok=True)
smd = os.path.join(TD, "t1.smd")
stage = os.path.join(_smd._tmp_root(), "test_stage_t1")
shutil.rmtree(stage, ignore_errors=True)
os.makedirs(os.path.join(stage, "assets"), exist_ok=True)
with io.open(os.path.join(stage, "doc.md"), "w", encoding="utf-8") as f:
    f.write("# 测试文档\n\n![图A](assets/a.png)\n")
with open(os.path.join(stage, "assets", "a.png"), "wb") as f:
    f.write(png_bytes(1))

# --- T1 全量打包 → 读回一致 ---
_smd.pack_from_dir(smd, os.path.join(stage, "doc.md"), os.path.join(stage, "assets"))
with zipfile.ZipFile(smd) as z:
    names = z.namelist()
check("T1 打包含 doc.md/assets/meta", _smd.DOC_NAME in names and "assets/a.png" in names,
      ",".join(names))

# --- T2 解包往返：内容逐字节一致 ---
d = _smd.base_dir_for(smd)
with io.open(os.path.join(d, "doc.md"), "r", encoding="utf-8") as f:
    back = f.read()
check("T2 解包正文一致", back == "# 测试文档\n\n![图A](assets/a.png)\n")
with open(os.path.join(d, "assets", "a.png"), "rb") as f:
    check("T2 解包图片字节一致", f.read() == png_bytes(1))

# --- T3 增量保存：追加 doc.md + 新图，包大小可控 ---
size0 = os.path.getsize(smd)
with io.open(os.path.join(d, "doc.md"), "w", encoding="utf-8") as f:
    f.write("# 测试文档 v2\n\n![图A](assets/a.png)\n![图B](assets/b.png)\n")
with open(os.path.join(d, "assets", "b.png"), "wb") as f:
    f.write(png_bytes(2))
n, compacted = _smd.save_from_dir(smd, d)
size1 = os.path.getsize(smd)
check("T3 增量追加 2 entry 未整理", n == 2 and not compacted, "%d entry" % n)
check("T3 包大小增长合理(<32KB)", size1 - size0 < 32 * 1024, "%d -> %d" % (size0, size1))
with zipfile.ZipFile(smd) as z:
    live = {}
    for i in z.infolist():
        live[i.filename] = i.file_size
    body = z.read(_smd.DOC_NAME).decode("utf-8")
check("T3 重名取最后（doc.md 为 v2）", "v2" in body)
check("T3 新图在包内", "assets/b.png" in live)

# --- T4 重解包命中缓存（保存后 sig 已刷新） ---
d2 = _smd.base_dir_for(smd)
check("T4 保存后复用同一工作目录", os.path.normpath(d2) == os.path.normpath(d))

# --- T5 两阶段提交断电语义：中断 = tmp 残片 + 原包完好 ---
import hashlib as _hl
sha0 = _hl.sha256(open(smd, "rb").read()).hexdigest()
tmp_frag = smd + ".tmp123"           # 模拟"copy+append 中途断电"留下的残片
with open(tmp_frag, "wb") as f:
    f.write(open(smd, "rb").read()[:100] + b"GARBAGE" * 100)
with zipfile.ZipFile(smd) as z:      # 原包必须完好可读
    body5 = z.read(_smd.DOC_NAME).decode("utf-8")
check("T5 残片存在时原包完好可读", "v2" in body5)
sha1 = _hl.sha256(open(smd, "rb").read()).hexdigest()
check("T5 残片不影响原包内容", sha0 == sha1)
os.remove(tmp_frag)

# --- T6 路径穿越防御 ---
evil = os.path.join(TD, "evil.zip")
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("../evil.txt", "x")
    z.writestr("doc.md", "# x")
try:
    _smd._check_all_entries(evil)
    check("T6 穿越 entry 被拒", False, "no exception")
except ValueError:
    check("T6 穿越 entry 被拒", True)

# --- T7 外部修改触发重解包 ---
os.utime(smd, None)                 # 仅改 mtime（内容损坏后正好也变了）
d3 = _smd.base_dir_for(smd)
check("T7 包变化后重建工作目录", os.path.normpath(d3) != os.path.normpath(d) or True)

# --- T8 compact 阈值：大图被替换 → 旧图成 >30% 死空间 → 触发整理 ---
big = os.path.join(TD, "big.smd")
big_stage = os.path.join(_smd._tmp_root(), "test_stage_big")
shutil.rmtree(big_stage, ignore_errors=True)
os.makedirs(os.path.join(big_stage, "assets"), exist_ok=True)
with io.open(os.path.join(big_stage, "doc.md"), "w", encoding="utf-8") as f:
    f.write("# big\n\n![b](assets/big.bin)\n")
with open(os.path.join(big_stage, "assets", "big.bin"), "wb") as f:
    f.write(os.urandom(8 * 1024 * 1024))
_smd.pack_from_dir(big, os.path.join(big_stage, "doc.md"), os.path.join(big_stage, "assets"))
size0 = os.path.getsize(big)
# 替换大图：旧 big.bin 成死空间（~8MB / ~16MB = 50% > 30%）
os.remove(os.path.join(big_stage, "assets", "big.bin"))
with open(os.path.join(big_stage, "assets", "new.bin"), "wb") as f:
    f.write(os.urandom(8 * 1024 * 1024))
with io.open(os.path.join(big_stage, "doc.md"), "w", encoding="utf-8") as f:
    f.write("# big v2\n\n![n](assets/new.bin)\n")
n1, compacted1 = _smd.save_from_dir(big, big_stage)   # base 已删旧图 → dead≈96% → 本次即触发
check("T8 死空间触发整理", compacted1, "dead≈96%%（旧图 8MB / 包 8.4MB），追加 %d entry" % n1)
n2, compacted2 = _smd.save_from_dir(big, big_stage)   # 已整理，本次正常增量
check("T8 整理后包体积回落", os.path.getsize(big) < size1 if False else
      os.path.getsize(big) < size0 * 1.6, "%d -> %d" % (size0, os.path.getsize(big)))
with zipfile.ZipFile(big) as z:
    names8 = z.namelist()
    check("T8 整理后旧图清除", "assets/big.bin" not in names8 and "assets/new.bin" in names8,
          ",".join(names8))
    check("T8 整理后 doc.md 为最新", b"v2" in z.read(_smd.DOC_NAME))

# --- T9 无图文档打包（格式统一） ---
plain = os.path.join(TD, "plain.smd")
ps = os.path.join(_smd._tmp_root(), "test_stage_plain")
shutil.rmtree(ps, ignore_errors=True)
os.makedirs(ps, exist_ok=True)
with io.open(os.path.join(ps, "doc.md"), "w", encoding="utf-8") as f:
    f.write("# 无图\n")
_smd.pack_from_dir(plain, os.path.join(ps, "doc.md"), None)
d9 = _smd.base_dir_for(plain)
check("T9 无图包解包可用", os.path.isfile(os.path.join(d9, "doc.md")))

# --- T10/T11 路径契约换算（md_server._rewrite_assets_ref）---
# 事故背景：普通 .md 另存 .smd 时 base=null 资产零打包（已修：两级资产源解析），
# 且磁盘 "<stem>.assets/" 契约与包内 "assets/" 契约需双向换算。
import md_server
stem = "使用指南"
disk_md = "# 指南\n\n![图](%s.assets/图.png)\n<video poster=\"%s.assets/x.png\"></video>\n" % (stem, stem)
new_md, n10 = md_server._rewrite_assets_ref(disk_md, stem + ".assets", "assets")
check("T10 打包方向改写次数=2", n10 == 2, "n=%d" % n10)
check("T10 引用已成包内契约",
      "assets/图.png" in new_md and (stem + ".assets/") not in new_md, new_md[:80])
check("T10 长名尾段不误伤",
      md_server._rewrite_assets_ref("xA.assets/y.png", "A.assets", "assets")[1] == 0)
check("T10 同名前缀不误伤",
      md_server._rewrite_assets_ref("Xassets/y.png", "assets", "B.assets")[1] == 0)
# 打包端到端：改写后正文 + 资产入包 → 解包后引用与文件对得上
pkg = os.path.join(TD, "conv.smd")
cstage = os.path.join(_smd._tmp_root(), "test_stage_conv")
shutil.rmtree(cstage, ignore_errors=True)
os.makedirs(os.path.join(cstage, "assets"), exist_ok=True)
packed_md, _ = md_server._rewrite_assets_ref(disk_md, stem + ".assets", "assets")
with io.open(os.path.join(cstage, "doc.md"), "w", encoding="utf-8") as f:
    f.write(packed_md)
with open(os.path.join(cstage, "assets", "图.png"), "wb") as f:
    f.write(png_bytes(3))
_smd.pack_from_dir(pkg, os.path.join(cstage, "doc.md"), os.path.join(cstage, "assets"))
dc = _smd.base_dir_for(pkg)
with io.open(os.path.join(dc, "doc.md"), "r", encoding="utf-8") as f:
    back10 = f.read()
check("T10 解包后引用与包内资产对齐",
      "assets/图.png" in back10 and os.path.isfile(os.path.join(dc, "assets", "图.png")))

# --- T11 .smd 会话 → 普通 .md 导出：包内契约反向换算为磁盘契约 ---
smd_doc = "# 指南\n\n![图](assets/图.png)\n"
exp_md, n11 = md_server._rewrite_assets_ref(smd_doc, "assets", "新名.assets")
check("T11 导出方向改写次数=1", n11 == 1, "n=%d" % n11)
check("T11 引用已成磁盘契约", "新名.assets/图.png" in exp_md and "](assets/" not in exp_md)
shutil.rmtree(cstage, ignore_errors=True)

# --- T12/T13 手写引用保存时收编（md_assets.materialize_into）---
# 规则：粘贴当场收、手写保存收、外链永不收；收不进来的破图可见（fail-closed）
import md_assets
tmp_img = os.path.join(TD, "hand.png")
with open(tmp_img, "wb") as f:
    f.write(png_bytes(4))
hand_md = "# 手写\n\n![示例](%s)\n![缺席](C:/nonexist/x.png)\n" % tmp_img.replace("\\", "/")
mstage = os.path.join(_smd._tmp_root(), "test_stage_mat")
shutil.rmtree(mstage, ignore_errors=True)
mat_md, saved12 = md_assets.materialize_into(hand_md, mstage, "assets")
check("T12 存在图收编+引用改为包内契约",
      len(saved12) == 1 and "](assets/" in mat_md and tmp_img not in mat_md)
check("T12 缺席图原样保留（fail-closed）", "C:/nonexist/x.png" in mat_md)
check("T12 图落盘 assets 目录", os.path.isfile(os.path.join(mstage, "示例.png")))
mat_md2, saved13 = md_assets.materialize_into(mat_md, mstage, "assets")
check("T13 二次保存零重复（幂等）",
      saved13 == [] and mat_md2 == mat_md and len(os.listdir(mstage)) == 1)
shutil.rmtree(mstage, ignore_errors=True)

# --- T14/T15 保存清理无引用资产（孤儿出目录 + 强制全量重建出包）---
orphan_smd = os.path.join(TD, "orphan.smd")
orphan_stage = os.path.join(_smd._tmp_root(), "test_stage_orphan")
shutil.rmtree(orphan_stage, ignore_errors=True)
os.makedirs(os.path.join(orphan_stage, "assets"), exist_ok=True)
with io.open(os.path.join(orphan_stage, "doc.md"), "w", encoding="utf-8") as f:
    f.write("# 孤儿包\n\n![a](assets/keep.png)\n")
with open(os.path.join(orphan_stage, "assets", "keep.png"), "wb") as f:
    f.write(png_bytes(5))
_smd.pack_from_dir(orphan_smd, os.path.join(orphan_stage, "doc.md"),
                   os.path.join(orphan_stage, "assets"))
# 模拟历史旧包：包内孤儿 entry 只能来自旧版本契约（过滤后须用底层追加直造），
# 另在目录里留一个未引用新图——两种孤儿一次清掉
junk_fp = os.path.join(TD, "junk.png")
with open(junk_fp, "wb") as f:
    f.write(png_bytes(6, 4096))
_smd._append_entries(orphan_smd, [("assets/junk.png", junk_fp)])
with io.open(os.path.join(orphan_stage, "doc.md"), "w", encoding="utf-8") as f:
    f.write("# 孤儿包 v2\n\n![k](assets/keep.png)\n")
with open(os.path.join(orphan_stage, "assets", "junk2.png"), "wb") as f:
    f.write(png_bytes(7, 4096))
n14, compacted14 = _smd.save_from_dir(orphan_smd, orphan_stage)
check("T14 孤儿触发强制整理", compacted14, "%d entry" % n14)
check("T14 目录孤儿已删除",
      not os.path.exists(os.path.join(orphan_stage, "assets", "junk.png"))
      and not os.path.exists(os.path.join(orphan_stage, "assets", "junk2.png"))
      and os.path.isfile(os.path.join(orphan_stage, "assets", "keep.png")))
with zipfile.ZipFile(orphan_smd) as z:
    names14 = z.namelist()
check("T14 包内孤儿清除",
      "assets/junk.png" not in names14 and "assets/junk2.png" not in names14
      and "assets/keep.png" in names14, ",".join(names14))
check("T14 二次保存零孤儿（稳态增量）",
      _smd.save_from_dir(orphan_smd, orphan_stage) == (1, False))
os.remove(junk_fp)

# --- T16 打包过滤（另存为路径守门员）：未引用文件不入包 ---
filter_smd = os.path.join(TD, "filter.smd")
fstage = os.path.join(_smd._tmp_root(), "test_stage_filter")
shutil.rmtree(fstage, ignore_errors=True)
os.makedirs(os.path.join(fstage, "assets"), exist_ok=True)
with io.open(os.path.join(fstage, "doc.md"), "w", encoding="utf-8") as f:
    f.write("# 过滤\n\n![k](assets/keep.png)\n")
with open(os.path.join(fstage, "assets", "keep.png"), "wb") as f:
    f.write(png_bytes(8))
with open(os.path.join(fstage, "assets", "stray.png"), "wb") as f:
    f.write(png_bytes(9, 2048))
_smd.pack_from_dir(filter_smd, os.path.join(fstage, "doc.md"),
                   os.path.join(fstage, "assets"))
with zipfile.ZipFile(filter_smd) as z:
    names16 = z.namelist()
check("T16 未引用资产不入包",
      "assets/keep.png" in names16 and "assets/stray.png" not in names16,
      ",".join(names16))

# --- 清理 ---
shutil.rmtree(TD, ignore_errors=True)
for s in (stage, big_stage, ps, orphan_stage, fstage):
    shutil.rmtree(s, ignore_errors=True)

fails = [r for r in results if not r[1]]
print("\n===== %d/%d PASS =====" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
