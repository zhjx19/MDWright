# -*- coding: utf-8 -*-
"""_smd.py -- .smd 自包含文档格式（v1.2.0）

.smd = ZIP 容器，内部结构：
    doc.md       正文（UTF-8）
    assets/...   图片资源（对应普通文档的 <stem>.assets/）
    meta.json    {"format": 1}

设计要点：
  - 读取以"最后一次出现的同名 entry"为准（zipfile.NameToInfo 后者覆盖前者），
    因此保存走 ZIP 追加模式：只追加变化的 entry，不重写整包。
  - 断电安全：entry 数据先写、central directory 由 zipfile 在 close() 时最后写，
    中途崩溃只丢本次保存，旧包完整可读。
  - 垃圾积累用阈值整理（compact）：死空间 >30% 且文件 >5MB 时全量重建，原子替换。
  - 安全：解包前校验全部 entry 名，拒绝绝对路径/盘符/.. 穿越。
"""
import os
import io
import re
import json
import time
import hashlib
import zipfile
import shutil
import warnings

FORMAT_VERSION = 1
DOC_NAME = "doc.md"
ASSETS_DIR = "assets"
META_NAME = "meta.json"

# 不入包清理纪律的白名单：annotations.json 是编辑器批注数据，doc.md 不会
# 引用它，但必须与文档一起打包保存，且不能当作孤儿资产被清理/剔除。
PROTECTED = {"annotations.json"}

# 包内资产引用（格式契约：包内引用恒为 assets/<文件名>，打包/另存为时已改写）
_ASSET_REF_RE = re.compile(r'assets/([^\s"\')\]]+)')


def referenced_assets(doc_text):
    """doc.md 中引用到的资产文件名集合（保存清理/打包过滤共用口径）。"""
    return set(_ASSET_REF_RE.findall(doc_text))

# 阈值整理触发条件：死空间占比与文件大小双门槛
COMPACT_DEAD_RATIO = 0.3
COMPACT_MIN_BYTES = 5 * 1024 * 1024


def is_smd(path):
    return str(path).lower().endswith(".smd")


def _safe_entry(name):
    """entry 名安全校验：拒绝绝对路径、盘符、.. 穿越。合法原样返回。"""
    n = str(name).replace("\\", "/")
    if n.startswith("/") or (len(n) > 1 and n[1] == ":"):
        raise ValueError("unsafe zip entry (absolute): %r" % name)
    if any(part == ".." for part in n.split("/")):
        raise ValueError("unsafe zip entry (traversal): %r" % name)
    return n


def _check_all_entries(smd_path):
    with zipfile.ZipFile(smd_path, "r") as z:
        for info in z.infolist():
            _safe_entry(info.filename)


def _sig(smd_path):
    """文件指纹（mtime+size），用于解包目录失效判断。"""
    st = os.stat(smd_path)
    return {"mtime_ns": st.st_mtime_ns, "size": st.st_size}


def _tmp_root():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "runtime", "tmp")


def base_dir_for(smd_path):
    """返回该 .smd 的解包工作目录；未解包或包已变化（外部修改）则重新解包。

    目录名 = md5(绝对路径小写)，跨会话稳定；目录内 .source.json 记录
    打开时的包指纹，保存/贴图后同步更新，外部改动会触发重解包。
    """
    abspath = os.path.abspath(smd_path)
    d = os.path.join(_tmp_root(), hashlib.md5(abspath.lower().encode("utf-8")).hexdigest()[:16])
    doc = os.path.join(d, DOC_NAME)
    sig_file = os.path.join(d, ".source.json")
    if os.path.isfile(doc) and os.path.isfile(sig_file):
        try:
            with io.open(sig_file, "r", encoding="utf-8") as f:
                rec = json.load(f)
            cur = _sig(smd_path)
            if rec.get("mtime_ns") == cur["mtime_ns"] and rec.get("size") == cur["size"]:
                return d                      # 命中：目录有效且包未变化
        except Exception:
            pass
        # 包被外部修改：丢弃旧目录重解
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    _check_all_entries(smd_path)
    with zipfile.ZipFile(smd_path, "r") as z:
        z.extractall(d)
    if not os.path.isfile(doc):
        shutil.rmtree(d, ignore_errors=True)
        raise ValueError("not a valid .smd (missing %s): %s" % (DOC_NAME, smd_path))
    _write_sig(smd_path, sig_file)
    return d


def _write_sig(smd_path, sig_file):
    try:
        with io.open(sig_file, "w", encoding="utf-8") as f:
            json.dump(_sig(smd_path), f)
    except Exception:
        pass


def pack_from_dir(smd_path, doc_src, assets_src=None):
    """全量打包（新建/另存为/整理用）。临时文件 + os.replace 原子替换。

    打包过滤：assets_src 中未被 doc.md 引用的文件不入包（保存清理纪律——
    包内资产与引用严格对齐；历史旧包的孤儿资产借此在全量重建时移除）。
    """
    tmp = "%s.tmp%d" % (smd_path, int(time.time() * 1000))
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        with io.open(doc_src, "r", encoding="utf-8") as f:
            doc_text = f.read()
        z.writestr(DOC_NAME, doc_text)
        if assets_src and os.path.isdir(assets_src):
            refs = referenced_assets(doc_text) | PROTECTED
            for fn in sorted(os.listdir(assets_src)):
                if fn not in refs:
                    continue
                fp = os.path.join(assets_src, fn)
                if os.path.isfile(fp):
                    z.write(fp, ASSETS_DIR + "/" + fn)
        z.writestr(META_NAME, json.dumps({"format": FORMAT_VERSION}, ensure_ascii=False))
    os.replace(tmp, smd_path)


def _live_sizes(smd_path):
    """名字 -> 该名下最后 entry 的字节数（重名以后写为准）。"""
    with zipfile.ZipFile(smd_path, "r") as z:
        live = {}
        for info in z.infolist():
            live[info.filename] = info.file_size
        return live


def needs_compact(smd_path, base_dir):
    """死空间 >30% 且文件 >5MB 时需要整理。

    死空间 = 包内总字节 - 有效字节。有效以**解包目录现状**为准：
      - 重名覆盖的死 entry（append 痕迹）；
      - 业务上已被替换/删除的资源（包内有 entry 但 base 目录已不存在，
        或同名但内容大小已变化）。
    异常时返回 False（保守不整理）。
    """
    try:
        total = os.path.getsize(smd_path)
        if total < COMPACT_MIN_BYTES:
            return False
        with zipfile.ZipFile(smd_path, "r") as z:
            live = {}
            for info in z.infolist():
                live[info.filename] = info.file_size
        valid = {DOC_NAME: os.path.getsize(os.path.join(base_dir, DOC_NAME)),
                 META_NAME: 0}
        adir = os.path.join(base_dir, ASSETS_DIR)
        if os.path.isdir(adir):
            for fn in os.listdir(adir):
                fp = os.path.join(adir, fn)
                if os.path.isfile(fp):
                    valid[ASSETS_DIR + "/" + fn] = os.path.getsize(fp)
        dead = total - sum(live.values())                 # 重名覆盖死空间
        for nm, sz in live.items():                       # 业务淘汰死空间
            if nm not in valid or valid[nm] != sz:
                dead += sz
        return dead > total * COMPACT_DEAD_RATIO
    except Exception:
        return False


def _append_entries(pkg_path, entries):
    """在包上追加 (名字, 源文件) 列表。重名 entry 为设计依赖（读取以后写为准），
    压掉 zipfile 的 Duplicate name 告警。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(pkg_path, "a", zipfile.ZIP_DEFLATED) as z:
            for nm, fp in entries:
                z.write(fp, nm)
    _fsync_file(pkg_path)


def _fsync_file(path):
    fd = os.open(path, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_from_dir(smd_path, base_dir):
    """增量保存（两阶段提交）：

    1. 顺序拷贝当前包到临时副本（字节级复制，旧 entry 不重新压缩，
       成本为顺序 IO，远低于全量重新 deflate）；
    2. 在副本上追加变化 entry（doc.md 恒追加；assets 与包内按 (名字, 大小) diff）；
    3. fsync 后 os.replace 原子替换 —— 任意时刻断电：replace 前原包完好，
       replace 后新包完好，不存在半写状态。

    达到整理阈值则改为全量重建。返回 (追加 entry 数, 是否发生整理)。
    """
    doc = os.path.join(base_dir, DOC_NAME)
    if not os.path.isfile(doc):
        raise ValueError("doc.md missing in unpacked dir: %s" % base_dir)
    try:
        live = _live_sizes(smd_path)
    except Exception:
        live = {}
    with io.open(doc, "r", encoding="utf-8") as f:
        doc_text = f.read()
    to_add = [(DOC_NAME, doc)]
    adir = os.path.join(base_dir, ASSETS_DIR)
    orphans = 0
    if os.path.isdir(adir):
        refs = referenced_assets(doc_text)
        for fn in sorted(os.listdir(adir)):
            fp = os.path.join(adir, fn)
            if not os.path.isfile(fp):
                continue
            if fn not in refs and fn not in PROTECTED:
                # 保存清理纪律：doc.md 未引用的资产从解包目录删除；
                # 删除失败保守留存（不阻断保存）
                try:
                    os.remove(fp)
                    orphans += 1
                except OSError:
                    pass
                continue
            nm = ASSETS_DIR + "/" + fn
            if nm not in live or os.path.getsize(fp) != live[nm]:
                to_add.append((nm, fp))
    if orphans:
        # 包内旧 entry 是追加式的，增量保存清不掉——孤儿已出目录，
        # 全量重建才能把它们从包内移除
        compact(smd_path, base_dir)
        return len(to_add), True
    if needs_compact(smd_path, base_dir):
        compact(smd_path, base_dir)
        return len(to_add), True
    tmp = "%s.tmp%d" % (smd_path, int(time.time() * 1000))
    # 失败时保留 tmp：会话结束工作目录会被 clear_tmp 清掉，它是本次内容
    # 跨会话的唯一幸存副本（恢复入口 = 打开文档时检测同名 .tmp<时间戳>）。
    # 成功替换后 tmp 已被 os.replace 消费，天然无残留，无需任何清理。
    shutil.copyfile(smd_path, tmp)
    _append_entries(tmp, to_add)
    os.replace(tmp, smd_path)
    sig_file = os.path.join(base_dir, ".source.json")
    _write_sig(smd_path, sig_file)          # 保存后刷新指纹，本会话继续复用该目录
    return len(to_add), False


def compact(smd_path, base_dir):
    """整理：按解包目录现状重建全量包，原子替换，天然清掉死空间与已删除资源。"""
    pack_from_dir(smd_path,
                  os.path.join(base_dir, DOC_NAME),
                  os.path.join(base_dir, ASSETS_DIR))
    sig_file = os.path.join(base_dir, ".source.json")
    _write_sig(smd_path, sig_file)


def clear_tmp():
    """服务启动/退出时清理解包缓存目录（会话级数据，正文与资源以 .smd 为准）。"""
    shutil.rmtree(_tmp_root(), ignore_errors=True)
