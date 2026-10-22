# -*- coding: utf-8 -*-
"""物化实验报告工具 —— 统一入口的启动脚本。

    python run.py                 启动入口页，并把各实验模块一并拉起来
    python run.py --no-browser    不自动打开浏览器
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    from portal import main as portal_main
    sys.exit(portal_main())


if __name__ == '__main__':
    main()
