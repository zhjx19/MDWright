# 写作与渲染

MDWright 是 Windows 上的单机 Markdown 写作台：**左边写 `.md`，右边就是成品**。
排版、分页、导出、代码块运行全部在本地完成，断网照常用。

## 行内语法与公式

这是**加粗强调**，这是*斜体*，这是 `行内代码`，这是[链接](https://example.com)。

行内公式 $E = mc^2$ 一目了然；块级公式单独成行：

$$
\hat{\beta} = \operatorname*{arg\,min}_{\beta} \sum_{i=1}^{n}\left(y_i - x_i^{\top}\beta\right)^2
$$

## 列表与表格

+ 实时渲染：所写即所得，长文档分块增量渲染
  - 分屏 / 仅编辑 / 仅预览 / 即时渲染，四种模式显式切换
+ 离线依赖：KaTeX、Paged.js、Mermaid、Graphviz 全部随包内置

| 能力 | 说明 | 离线 |
|---|---|:--:|
| 数学公式 | KaTeX 渲染行内与块级公式 | 是 |
| 图表 | Mermaid / Graphviz / Vega-Lite | 是 |
| 导出 | HTML / 分页 HTML / Word / PDF | 是 |
