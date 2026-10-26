# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""图片宽度参数 {N} 测试（v2.0.0）：
- 前端解析：![alt](src){30} → style="width:30%"；钳制/无效值/空格/标题共存/纯链接不受影响
- 路径改写保留：_rewrite_assets_ref 只动括号内路径，){30} 后缀原样保留
- 分页切片：切片决策基于调整后宽度（eff_w_mm = 版心 × pct）；条带透传同一宽度样式；
  调整后不超高则整图原子不切
前端部分从 mdwright.html 提取 /*PARSER_START*/../*PARSER_END*/ 段跑 node。"""
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
import re
import subprocess
import sys

# Windows 控制台默认 GBK，失败详情里可能含 GBK 外字符（如脚注回链 ↩）；
# 统一 stdout 为 UTF-8 + replace，避免「打印」把测试搞崩。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import tempfile

HERE = _ROOT          # 仓库根（本文件在 tests/ 下）
HTML = os.path.join(HERE, "mdwright.html")
RESULTS = []


def check(name, ok, extra=""):
    RESULTS.append((name, ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + extra) if extra else ""))


def js_part():
    src = open(HTML, encoding="utf-8").read()
    m = re.search(r"/\*PARSER_START\*/(.*?)/\*PARSER_END\*/", src, re.S)
    if not m:
        check("parser segment found", False)
        return
    js = m.group(1)
    # parseInline 依赖 escapeHtml/escAttr/sanitizeUrl，连同依赖一起提取后只调 parseInline
    harness = js + r"""
const cases = [
  ["![a](x.png){30}", '<img src="x.png" alt="a" style="width:30%">'],
  ['![a](x.png "t"){45}', '<img src="x.png" alt="a" title="t" style="width:45%">'],
  ["![a](x.png){150}", '<img src="x.png" alt="a" style="width:100%">'],
  ["![a](x.png){0}", null],                       // {0} 不进参数组，原样留在正文
  ["![a](x.png){abc}", null],                     // 非数字同上
  ["![a](x.png)", '<img src="x.png" alt="a">'],   // 无参数无 style
  ["![a](x.png) {30}", '<img src="x.png" alt="a" style="width:30%">'],  // 允许一个空格
  ["[t](u){30}", null],                           // 纯链接不受影响
];
let fails = 0;
for (const [input, expect] of cases) {
  const out = parseInline(input);
  if (expect === null) {
    // 期望：不产生 width style，且参数文本保持字面
    if (/style="width:/.test(out) && input.indexOf('{30}') >= 0 && input.indexOf(' {30}') < 0 && !/link/.test(input)) {
      console.log('FAIL(should-not-style) ' + input + ' -> ' + out); fails++;
    } else if (input === "[t](u){30}" && (out.indexOf('<img') >= 0)) {
      console.log('FAIL(link-became-img) ' + out); fails++;
    } else {
      console.log('PASS ' + input);
    }
  } else if (out === expect) {
    console.log('PASS ' + input);
  } else {
    console.log('FAIL ' + input + ' -> ' + out + ' (expect ' + expect + ')'); fails++;
  }
}
console.log('JS-FAILS=' + fails);

/* ---- 围栏 {N}（与图片同规矩：空白可选、钳 100、非法 fail-closed） ---- */
const fl = parseFenceLang;
const fenceCases = [
  ['mermaid {30}', 'mermaid', 30],      // 带空格（与图片 " {30}" 对称）
  ['mermaid{30}', 'mermaid', 30],       // 紧贴
  ['dot {50}', 'dot', 50],
  ['vega-lite {25}', 'vega-lite', 25],
  ['mermaid {150}', 'mermaid', 100],    // 钳制
  ['mermaid', 'mermaid', 0],            // 无参数
  ['mermaid {0}', 'mermaid {0}', 0],    // 非数字/0 → 原样（fail-closed）
  ['mermaid {abc}', 'mermaid {abc}', 0],
  ['python {30}', 'python', 30],        // 解析通用；宽度仅图表消费
];
let ffails = 0;
for (const [raw, el, ew] of fenceCases) {
  const r = fl(raw);
  if (r.lang !== el || r.width !== ew) {
    console.log('FAIL fence ' + raw + ' -> ' + JSON.stringify(r) + ' (expect ' + el + ',' + ew + ')'); ffails++;
  } else console.log('PASS fence ' + raw);
}
/* 端到端：图表围栏产出带宽容器；非图表围栏保持字面 */
const md1 = parseMarkdown('```mermaid {30}\ngraph TD\nA-->B\n```\n');
if (/class="diagram" data-diagram="mermaid"[^>]*style="width:30%"/.test(md1)) console.log('PASS md diagram {30}');
else { console.log('FAIL md diagram {30} -> ' + md1.slice(0, 160)); ffails++; }
const md2 = parseMarkdown('```mermaid{50}\ngraph TD\nA-->B\n```\n');
if (/data-diagram="mermaid"[^>]*style="width:50%"/.test(md2)) console.log('PASS md diagram{50}');
else { console.log('FAIL md diagram{50}'); ffails++; }
const md3 = parseMarkdown('```python {30}\nx=1\n```\n');
if (/class="lang-python \{30\}"/.test(md3)) console.log('PASS md python {30} literal kept');
else { console.log('FAIL md python {30} -> ' + md3.slice(0, 160)); ffails++; }
const md4 = parseMarkdown('```mermaid {0}\ngraph TD\nA-->B\n```\n');
if (/class="lang-mermaid \{0\}"/.test(md4)) console.log('PASS md mermaid {0} falls back');
else { console.log('FAIL md mermaid {0} -> ' + md4.slice(0, 160)); ffails++; }
/* I5：围栏信息串是用户输入，必须转义后才能进 class 属性（否则可注入事件属性） */
const md5 = parseMarkdown('```py" onmouseover="alert(1)\nx=1\n```\n');
if (md5.indexOf('onmouseover="alert(1)"') < 0 && md5.indexOf('&quot;') >= 0) console.log('PASS fence lang escaped');
else { console.log('FAIL fence lang escaped -> ' + md5.slice(0, 200)); ffails++; }
console.log('FENCE-FAILS=' + ffails);
"""
    tmp = os.path.join(HERE, "_tmp_img_width.js")
    open(tmp, "w", encoding="utf-8").write(harness)
    r = subprocess.run(["node", tmp], capture_output=True, text=True)
    os.remove(tmp)
    out = r.stdout
    print(out.rstrip())
    n_pass = len(re.findall(r"^PASS ", out, re.M))
    n_fail = len(re.findall(r"^FAIL", out, re.M)) + (
        0 if re.search(r"^JS-FAILS=0$", out, re.M) else 1) + (
        0 if re.search(r"^FENCE-FAILS=0$", out, re.M) else 1)
    check("js parse cases %d pass / %d fail" % (n_pass, n_fail),
          n_fail == 0 and n_pass >= 6, "rc=%d %s" % (r.returncode, r.stderr[:80]))


def py_part():
    sys.path.insert(0, HERE)
    import md_server

    # 1) 路径改写保留 {30} 后缀（_rewrite_assets_ref 返回 (content, 替换数)）
    out, _nr = md_server._rewrite_assets_ref(
        "![截图](old/abc.png){30}\n![b](old/def.png)", "old", "new")
    check("rewrite keeps {30}", out == "![截图](new/abc.png){30}\n![b](new/def.png)", out)

    # 2) 切片：调整后尺寸决策 + 条带透传宽度
    from PIL import Image
    tmpdir = tempfile.mkdtemp(prefix="md_imgw_")
    tall = os.path.join(tmpdir, "tall.png")
    short = os.path.join(tmpdir, "short.png")
    # 纯色竖条纹图（亮度均匀，静默吸附退化到均分切点即可）
    Image.new("L", (400, 2400), 200).save(tall)
    Image.new("L", (400, 300), 200).save(short)

    icb, maxh = 150.0, 240.0
    # 满宽：渲染高 900mm > 240 → 切；条带无 style
    body = '<p><img src="/img?path=%s" alt="满宽"></p>' % tall.replace("\\", "/")
    out = md_server._slice_tall_images(body, icb, maxh)
    strips = re.findall(r'<img src="/static/_slice/[^"]+" alt="满宽">', out)
    check("full-width sliced, strips carry no style",
          len(strips) >= 4 and "style=" not in out, "strips=%d" % len(strips))

    # 宽度 50%：eff_w=75mm，渲染高 450mm > 240 → 仍切但几何不同；条带带 width:50%
    body50 = '<p><img src="/img?path=%s" alt="半宽" style="width:50%%"></p>' % tall.replace("\\", "/")
    out50 = md_server._slice_tall_images(body50, icb, maxh)
    m = re.search(r'style="width:50%"', out50)
    strips50 = len(re.findall(r'/strip-\d+\.png', out50))
    check("50% width sliced with style passthrough",
          bool(m) and strips50 >= 8, "strips=%d" % strips50)
    # 50% 的条带数应显著多于满宽（同一张图，调整后更窄→渲染高虽减半但条带按 eff 换算更细）
    # 满宽 strip_px = (240/6)/150*400 = 106.7→107；50% strip_px = 40/75*400 = 213→213
    # 满宽 n=ceil(2400/107)=23；50% n=ceil(2400/213)=12 —— 满宽条带更多
    mw = len(re.findall(r'/strip-\d+\.png', out))
    check("slice geometry respects eff width", mw > strips50,
          "full=%d half=%d" % (mw, strips50))

    # 调整后不超高：50% 宽的短图（300px → 渲染高 56mm < 240）→ 原子不切
    body_short = '<p><img src="/img?path=%s" alt="矮" style="width:50%%"></p>' % short.replace("\\", "/")
    out_short = md_server._slice_tall_images(body_short, icb, maxh)
    check("adjusted-height fits → atomic (no slice)",
          out_short == body_short, out_short[:80])


def main():
    js_part()
    py_part()
    n_pass = sum(1 for _, ok in RESULTS if ok)
    n_all = len(RESULTS)
    print("%d/%d passed" % (n_pass, n_all))
    return 0 if n_pass == n_all else 1


if __name__ == "__main__":
    sys.exit(main())
