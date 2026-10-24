# -*- coding: utf-8 -*-
"""磁化率测定实验报告生成工具 —— 启动入口。"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from pcal.server import main

if __name__ == '__main__':
    main()
