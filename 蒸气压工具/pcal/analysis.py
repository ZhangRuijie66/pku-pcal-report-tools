# -*- coding: utf-8 -*-
"""蒸气压实验 —— 参数模型与一次完整计算。"""
from __future__ import annotations

import copy
import json

from . import vapor
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
        'p1': vapor.P_NORM,          # 常压沸点的定义压强 / kPa
        'lit_tb_water': vapor.DEFAULT_LIT['water']['tb'],
        'lit_dh_water': vapor.DEFAULT_LIT['water']['dh'],
        'lit_tb_cyclo': vapor.DEFAULT_LIT['cyclo']['tb'],
        'lit_dh_cyclo': vapor.DEFAULT_LIT['cyclo']['dh'],
        'trouton': vapor.TROUTON,
        'shift_check': 1.0,          # 水的「整体温度偏高 Δt ℃」复算，0 = 关
        # 浏览/导入文件的文件夹（不是数据本身：数据在 data/蒸气压数据.json）。
        # None = 交给 server.default_data_dir() 运行时推导，不写死盘符。
        'data_dir': None,
        'report_title': '液体饱和蒸气压的测定',
    }


PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'room_temp', 'pressure', 'p1',
    'lit_tb_water', 'lit_dh_water', 'lit_tb_cyclo', 'lit_dh_cyclo',
    'trouton', 'shift_check', 'data_dir',
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
        self.data = copy.deepcopy(data) if data is not None else vapor.sample_data()
        self.result = None

    def run(self):
        self.result = vapor.analyze(self.data, self.cfg)
        return self.result


def load_data(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def save_data(path, data):
    """原子写盘：先在内存里序列化成功，再整体替换。

    旧写法 ``open(path, 'w')`` 会**先把文件截断成 0 字节**，之后 ``json.dump``
    中途抛异常（数据里混进 numpy 标量 / set，或磁盘满）就把用户的实验读数
    留在半截状态，而且没有任何备份。
    """
    return atomic_write_json(path, data)
