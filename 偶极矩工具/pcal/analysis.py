# -*- coding: utf-8 -*-
"""偶极矩实验 —— 参数模型与一次完整计算。"""
from __future__ import annotations

import copy
import json
import os

from . import dipole


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
        'M1': 84.159,                # 环己烷摩尔质量（手册值，视为常数）
        'M2': 74.121,                # 正丁醇摩尔质量（手册值，视为常数）
        'lit_mu': dipole.LIT_MU,     # 正丁醇偶极矩文献值 / D
        'sigma_n': 0.0002,           # 折射率的不确定度（假设值）
        'sigma_rho2': 0.00002,       # 正丁醇密度的不确定度（假设值）
        'sigma_c_check': 0.01,       # 4.1.1 电容误差假设 / pF
        'sigma_T_check': 1.0,        # 4.1.2 温度波动假设 / ℃
        'P_atom_frac': dipole.P_ATOM_FRAC,   # 4.1.3 原子极化度占比
        'report_title': '稀溶液法测定极性分子的偶极矩',
    }


PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'room_temp', 'pressure', 'M1', 'M2', 'lit_mu',
    'sigma_n', 'sigma_rho2', 'sigma_c_check', 'sigma_T_check', 'P_atom_frac',
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
        self.data = copy.deepcopy(data) if data is not None else dipole.sample_data()
        self.result = None

    def run(self):
        self.result = dipole.analyze(self.data, self.cfg)
        return self.result


def load_data(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def save_data(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path
