# AGENTS.md — MDWright

Windows 单机 Markdown 写作台：Python 后端（`md_server.py`）+ 单文件前端（`mdwright.html`），衍生自 MDEditor v2.0，AGPL-3.0-or-later。

- **权威记忆**：项目暂无 `MEMORY.md`；版本与已交付以 `CHANGELOG.md` 为准，在研范围看 `docs/superpowers/plans/`。
- 上层索引：`E:\Positron-demo\记忆管理\主记忆.md`（跨项目，只读）
- **发布必改三处**：`md_server.py` 的 `MD_SERVER_VERSION` +1、`APP_VERSION` 与 `CHANGELOG.md` 首段版本号同步；`CHANGELOG.md` 按体例加段（只有 `## vX.Y.Z` 作标题）。
- **分发有清单**：增删随包文件要同步 `docs/分发清单.md`，`tests/_test_dist_verify.py` 按该最小集从零跑全链。
- **跑测试前先停实例**：先执行 `md_stop.cmd`；否则 18766 被正式实例占着会出与代码无关的 FAIL，用例自用 18777 / 18790。全套 `python\python.exe tests\run_all.py`。
- **解析器段不可改标记**：`mdwright.html` 的 `/*PARSER_START*/`～`/*PARSER_END*/` 被测试原文抽取跑 Node，比的是真函数。
- **`python/` 整目录分发**：内含 pythonnet 原生桥接 DLL，缺了内嵌窗口静默无窗口；`.gitignore` 的 `/runtime/` 必须锚定，勿误伤。
