# AGENTS.md — MDWright

Windows 单机 Markdown 写作台：Python 后端（`md_server.py`）+ 单文件前端（`mdwright.html`），衍生自 MDEditor v2.0，AGPL-3.0-or-later。

- **权威记忆**：项目暂无 `MEMORY.md`；版本与已交付以 `CHANGELOG.md` 为准，在研范围看 `docs/superpowers/plans/`。
- 上层索引：`E:\Positron-demo\记忆管理\主记忆.md`（跨项目，只读）
- **发布必改三处**：`md_server.py` 的 `MD_SERVER_VERSION` +1、`APP_VERSION` 与 `CHANGELOG.md` 首段版本号同步；`CHANGELOG.md` 按体例加段（只有 `## vX.Y.Z` 作标题）。
- **发版有门面清单**：About / Topics / Release 正文骨架 / 发布后四条核对，见 `docs/GitHub 仓库门面清单.md`（exe 只能手动上传，`_setup_out/` 不入库）。
- **发版提醒（v3.2.4 首发时踩过的，别再犯）**：
  - Release 正文**只放用户需要知道的发布说明**，不要粘自检清单、待办、命令——自检内容属于这份 AGENTS.md 与门面清单，不属于正文。正文从 `CHANGELOG.md` 对应版本段摘。
  - 发布后必核对 `assets[].digest` 与本地 `(Get-FileHash … -Algorithm SHA256).Hash.ToLower()` **逐字一致**；比大小可靠，这是唯一能证明「上传的包没坏」的字段。
  - 首次发布、或中间几版没单独发过 Release 时，正文要把那些版本的修复一并列出——用户看不到它们的条目。
  - 最后一关是**装一次从 Release 下载回来的包**：「关于」显示当前版本、标题栏是「墨匠 MDWright」，别只信本地构建。
- **仓库门面现状**：About 的 Description 与 14 个 topics 已按门面清单第一节填好；改文案以该节为准，**排除项不能删**（中文「墨匠」在公众号排版领域另有项目，不写清会有一半误访）。
- **网络**：`git push` / `curl` 走本机代理 `127.0.0.1:9567`。报 `Failed to connect to github.com port 443 via 127.0.0.1` 就是代理没起，不是仓库或代码问题——先 `Test-NetConnection 127.0.0.1 -Port 9567`，别去动 git 配置。
- **分发有清单**：增删随包文件要同步 `docs/分发清单.md`，`tests/_test_dist_verify.py` 按该最小集从零跑全链。
- **跑测试前先停实例**：先执行 `md_stop.cmd`；否则 18766 被正式实例占着会出与代码无关的 FAIL，用例自用 18777 / 18790。全套 `python\python.exe tests\run_all.py`。
- **解析器段不可改标记**：`mdwright.html` 的 `/*PARSER_START*/`～`/*PARSER_END*/` 被测试原文抽取跑 Node，比的是真函数。
- **`python/` 整目录分发**：内含 pythonnet 原生桥接 DLL，缺了内嵌窗口静默无窗口；`.gitignore` 的 `/runtime/` 必须锚定，勿误伤。
