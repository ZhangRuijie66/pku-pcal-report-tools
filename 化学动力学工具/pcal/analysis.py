# -*- coding: utf-8 -*-
"""化学反应动力学实验 —— 参数模型与一次完整计算。"""
from __future__ import annotations

import copy
import json

from . import kinetics
from .atomicio import atomic_write_json


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
        # 标称酸浓度 → 实际 c(H⁺) 的换算系数。实验里母液混合后浓度减半，
        # 所以默认 0.5；只在某组没手填 c(H⁺) 时生效。
        'acid_ratio': 0.5,
        # 浏览/导入文件的文件夹（数据本体在 data/化学动力学数据.json）。
        # None = 交给 server.default_data_dir() 运行时推导，不写死盘符。
        'data_dir': None,
        'report_title': '化学反应动力学探究',
    }


PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'room_temp', 'pressure', 'alpha_inf_mode', 'order_group', 'acid_ratio',
    'data_dir',
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
    """原子写盘：先在内存里序列化成功，再整体替换。

    旧写法 ``open(path, 'w')`` 会**先把文件截断成 0 字节**，之后 ``json.dump``
    中途抛异常就把用户的实验读数留在半截状态，而且没有任何备份。
    """
    return atomic_write_json(path, data)
