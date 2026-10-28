# -*- coding: utf-8 -*-
"""表面吸附实验 —— 参数模型与一次完整计算。"""
from __future__ import annotations

import copy
import json
import os

from . import adsorption


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
        'conc_axis': 'lg',          # 'lg' = γ–lg c；'ln' = γ–ln c
        'zero_correction': True,    # 是否扣除压力计零点
        'height_mode': 'both',      # 'both' 两侧都读；'left' 只读左侧；'right' 只读右侧
        'height_sum': 0.0,          # 两臂液柱高度之和 S / cm，0 = 自动估计
        'repeat_n': 3,              # 每个点的平行测定次数
        'report_title': '溶液表面吸附的测定',
    }


PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'room_temp', 'pressure', 'conc_axis', 'zero_correction',
    'height_mode', 'height_sum', 'repeat_n',
)


def merge_saved(cfg, saved):
    for key, value in (saved or {}).items():
        if key in PERSIST_KEYS and value is not None:
            cfg[key] = value
    return cfg


def default_config_with_saved(saved):
    return merge_saved(default_config(), saved)


class Analysis:
    """一次完整的数据处理；换参数/换数据就重建一个并 run()。"""

    def __init__(self, config, data=None):
        self.cfg = copy.deepcopy(config) if config else default_config()
        self.data = copy.deepcopy(data) if data is not None else adsorption.sample_data()
        self.result = None

    def run(self):
        self.result = adsorption.analyze(self.data, self.cfg)
        return self

    # 便捷访问
    @property
    def bubble(self):
        return self.result['bubble']

    @property
    def plate(self):
        return self.result['plate']

    @property
    def warnings(self):
        return self.result['warnings']


def load_data(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def save_data(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path
