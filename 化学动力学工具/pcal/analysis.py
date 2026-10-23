# -*- coding: utf-8 -*-
"""化学反应动力学实验 —— 参数模型与一次完整计算。"""
from __future__ import annotations

import copy
import json
import os

from . import kinetics


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
        'alpha_inf_mode': 'measured',    # 'measured' 实验值 / 'theory' 理论值
        'order_group': '4M',             # 用哪一组判定蔗糖反应级数
        'report_title': '化学反应动力学探究',
    }


PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'room_temp', 'pressure', 'alpha_inf_mode', 'order_group',
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
        self.data = copy.deepcopy(data) if data is not None else kinetics.sample_data()
        self.result = None

    def run(self):
        self.result = kinetics.analyze(self.data, self.cfg)
        return self

    @property
    def groups(self):
        return self.result['groups']

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
