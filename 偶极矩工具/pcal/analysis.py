# -*- coding: utf-8 -*-
"""偶极矩实验 —— 参数模型与一次完整计算。"""
from __future__ import annotations

import copy
import json
import os

from . import dipole
from .atomicio import atomic_write_json

# 默认数据目录：**运行时推导**，不写死任何一台机器上的绝对路径。
# 偶极矩的数据是手工录入的 JSON（<工具>/data/偶极矩数据.json），随工具目录走；
# 课程给的「数据处理2.xlsx」只是**导入来源**，不能拿它当数据目录——
# 那会把「数据文件存哪儿」从工具目录悄悄挪到课程原始数据目录，
# 既有用户的 data/偶极矩数据.json 就不再被读到（静默丢数据）。
_TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 本模块自己的数据目录（手工录入的结构化数据，随工具走）
DATA_SUBDIR = 'data'
DATA_FILENAME = '偶极矩数据.json'
DEFAULT_DATA_DIR = os.path.join(_TOOL_DIR, DATA_SUBDIR)

#: 导入用的候选目录（相对套件根）：课程原始数据处理表常在这里。
#: 只用于「从文件夹选文件并导入」，不影响数据文件存哪儿。
IMPORT_DIR_CANDIDATES = (
    os.path.join('物理化学实验', '物理化学实验', '偶极矩'),
    '偶极矩',                                                 # 精简布局
)


def _default_data_dir():
    """默认数据目录：固定 ``<工具>/data``（不存在也没关系，写盘时自动建）。

    刻意**不**把课程原始数据目录纳入候选：那是导入来源，不是数据家的位置。
    换机器/换版本时这个路径始终跟着工具目录走，绝不写死盘符。
    """
    return DEFAULT_DATA_DIR


#: 默认数据文件绝对路径（工具目录下 data/偶极矩数据.json）
DEFAULT_DATA_FILE = os.path.join(DEFAULT_DATA_DIR, DATA_FILENAME)


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
        # ---- 数据目录（导入 xlsx/csv 时从这里找；换机器后自动推导，不写死盘符）
        'data_dir': DEFAULT_DATA_DIR,
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
    'room_temp', 'pressure', 'data_dir', 'M1', 'M2', 'lit_mu',
    'sigma_n', 'sigma_rho2', 'sigma_c_check', 'sigma_T_check', 'P_atom_frac',
)


def data_file_for(cfg, default_file=None):
    """当前配置对应的数据文件路径。

    偶极矩的数据是**单个 JSON**（不是目录里散落的多份文件），所以约定：
    ``<data_dir>/偶极矩数据.json``。数据目录换了，数据文件跟着走，
    避免「界面上换了目录、存盘却还写回工具目录」这种静默错位。
    """
    cfg = cfg or {}
    path = str(cfg.get('data_file') or '').strip()
    if path:
        return path
    data_dir = str(cfg.get('data_dir') or '').strip()
    if data_dir and os.path.normcase(os.path.abspath(data_dir)) != os.path.normcase(
            os.path.abspath(DEFAULT_DATA_DIR)):
        return os.path.join(data_dir, DATA_FILENAME)
    return default_file or DEFAULT_DATA_FILE


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
    """原子写盘：先在内存里序列化成功，再整体替换。

    旧写法 ``open(path, 'w')`` 会**先把文件截断成 0 字节**，之后 ``json.dump``
    中途抛异常就把用户的实验读数留在半截状态，而且没有任何备份。
    """
    return atomic_write_json(path, data)
