# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 wUwproject. Licensed under GNU AGPL v3 (or later).
"""服务启动 shim（性能优化）

便携 Python 为 embeddable 发行版（._pth 不注入脚本目录），主脚本模式
`python md_server.py` 每次冷启动都要现场编译整个 85KB 源码（主脚本永不
命中 __pycache__ 的 .pyc，只有 import 模式走缓存）。

本 shim 以 import 方式加载 md_server 并调用 main()：
- 首次运行生成 .pyc，此后启动稳定 ~0.5s（实测主脚本模式 ~1.05s）
- 仅供 md_launch.pyw / md_app.pyw / md_stop.cmd 等启动器使用；
  `python md_server.py` 直跑仍完全可用（同一份 main()）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import md_server

md_server.main()