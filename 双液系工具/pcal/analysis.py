# -*- coding: utf-8 -*-
"""双液系实验 —— 参数模型与一次完整计算。"""
from __future__ import annotations

import copy
import json
import os

from . import phase


def default_config():
    return {
        # ---- 封面
        'student_name': '',
        'student_id': '',
        'group': '',
        'group_no': '',
        'date': '',
        'room_temp': None,
        'pressure': None,
        # ---- 处理
        'composition_mode': 'ratio',   # 'ratio' 质量比（参照口径）/ 'frac' 质量分数（讲义字面）
        'sigma_n': 0.0005,             # 折射率读数标准差（最后一位估读）
        'lit_T_K': 337.95,             # 文献恒沸点（CRC，见参照报告引用）
        'lit_w': 0.3128,               # 文献恒沸组成：乙醇质量分数（会按口径换算）
        'report_title': '双液体系沸点-成分图的绘制',
    }


PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'room_temp', 'pressure', 'composition_mode', 'sigma_n',
    'lit_T_K', 'lit_w',
)


def merge_saved(cfg, saved):
    for key, value in (saved or {}).items():
        if key in PERSIST_KEYS and value is not None:
            cfg[key] = value
    return cfg


def default_config_with_saved(saved):
    return merge_saved(default_config(), saved)


class Analysis:
    def __init__(self, config, data=None):
        self.cfg = copy.deepcopy(config) if config else default_config()
        self.data = copy.deepcopy(data) if data is not None else phase.sample_data()
        self.result = None

    def run(self):
        self.result = phase.analyze(self.data, self.cfg)
        return self


def load_data(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def save_data(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path
