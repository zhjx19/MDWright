# -*- coding: utf-8 -*-
"""splitRow/parseTable 行为回归：从 mdwright.html 抽取真实函数源码执行（非副本）。"""
import io, re, subprocess, sys, os

H = io.open('mdwright.html', encoding='utf-8').read()

def grab(name):
    m = re.search(r'function %s\([\s\S]*?\n\}' % name, H)
    assert m, 'function %s not found' % name
    return m.group(0)

js = '''
var PASS = 0, FAIL = 0;
function check(name, cond, detail) {
  if (cond) { PASS++; console.log('PASS ' + name); }
  else { FAIL++; console.log('FAIL ' + name + (detail ? ' :: ' + detail : '')); }
}
''' + grab('escapeHtml') + grab('escAttr') + grab('sanitizeUrl') + grab('splitRow') + grab('parseInline') + grab('parseTable') + r'''
// ---- T1: 行内代码内的 \| 不切列，还原为字面 | ----
var r1 = splitRow('| A | B | 围栏错配+引用表`\\|`切列已修）；待后台手动四步发布 |');
check('T1 格数=3（不多切）', r1.length === 3, 'n=' + r1.length);
check('T1 代码内字面竖线保留', r1[2].indexOf('引用表`|`切列已修') >= 0, r1[2]);

// ---- T2: 裸 | 在代码内被多切 → 合并回前一列，内容不丢 ----
var lines = [
  '| # | 标题 | 状态 | 备注 |',
  '| --- | --- | --- | --- |',
  '| 13 | 本地TS | 否 | 围栏错配+引用表`|`切列已修）；四步发布 |',
  '| 21 | BGM | 否 | 无图 |'
];
var out2 = parseTable(lines, 0);
var tds2 = (out2[0].match(/<td>/g) || []).length;
check('T2 正文格数=8（2行×4列，幽灵列消失）', tds2 === 8, 'td=' + tds2);
check('T2 合并后 | 保留在格内', out2[0].indexOf('引用表<code>|</code>切列已修') >= 0, out2[0].slice(0, 400));

// ---- T3: 格数不足补空 td（列边框对齐） ----
var lines3 = [
  '| A | B | C |',
  '| --- | --- | --- |',
  '| 只有一格 |'
];
var out3 = parseTable(lines3, 0);
var tds3 = (out3[0].match(/<td>/g) || []).length;
check('T3 不足补齐=3 td', tds3 === 3, 'td=' + tds3);

// ---- T4: 正常表格不受影响 + 对齐样式 ----
var lines4 = [
  '| 左 | 中 | 右 |',
  '| :--- | :---: | ---: |',
  '| a | b | c |'
];
var out4 = parseTable(lines4, 0);
check('T4 对齐样式 center', out4[0].indexOf('text-align:center') >= 0);
check('T4 对齐样式 right', out4[0].indexOf('text-align:right') >= 0);

// ---- T5: 多行连续 \| 与行尾 \| 混排 ----
var r5 = splitRow('| x\\|y | 尾部\\| |');
check('T5 两处转义都还原', r5.length === 2 && r5[0] === 'x|y' && r5[1] === '尾部|', JSON.stringify(r5));

console.log('---');
console.log('TOTAL: ' + (PASS + FAIL) + ', FAIL: ' + FAIL);
if (FAIL > 0) { process.exit(1); }
'''

io.open('_t_table.js', 'w', encoding='utf-8').write(js)
r = subprocess.run(['node', '_t_table.js'], capture_output=True, text=True, encoding='utf-8')
print(r.stdout)
if r.returncode != 0:
    print(r.stderr)
os.remove('_t_table.js')
sys.exit(r.returncode)
