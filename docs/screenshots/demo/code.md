# 可执行代码块

带 `python` / `r` 语言标记的代码块，点「▶ 运行」就地执行，输出与图形显示在块下方。
用的是随包内置的运行时，不碰系统 `PATH`，也不需要另装任何东西。

```python
import statistics as st

xs = [2.1, 3.4, 3.9, 5.2, 6.8, 8.1]
print("n    =", len(xs))
print("mean =", round(st.mean(xs), 3))
print("sd   =", round(st.stdev(xs), 3))
```

输出留在原处，和正文一起保存、一起导出——写方法笔记时省掉来回切窗口。
