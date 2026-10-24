# -*- coding: utf-8 -*-
"""电解质溶液电导率的测定 —— 参数模型与一次完整计算。

界面、自检、报告生成都只跟这里的 :class:`Analysis` 打交道：
换参数就重建一个 Analysis 并 ``run()`` 一次，得到全部结果。

原始读数存放在 ``<data_dir>/电导率数据.json``（界面可编辑并保存）；
封面等偏好在 settings.json（PERSIST_KEYS）。
"""
from __future__ import annotations

import copy
import os

import numpy as np

from . import conduct

DEFAULT_DATA_DIR = (r'D:\北大\课程\26秋大三上\物理化学实验'
                    r'\物理化学实验\物理化学实验\电导率')

STRONG_KEYS = ('NaNO3', 'NaAc', 'HNO3')


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
        # ---- 数据
        'data_dir': DEFAULT_DATA_DIR,
    }


PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'room_temp', 'pressure', 'data_dir',
)


def merge_saved(cfg, saved):
    if not saved:
        return cfg
    for k, v in saved.items():
        if k in PERSIST_KEYS and v is not None:
            cfg[k] = v
    return cfg


def default_config_with_saved(saved):
    return merge_saved(default_config(), saved)


class Analysis:
    """一次完整的实验数据处理。"""

    def __init__(self, config):
        self.cfg = copy.deepcopy(config) if config else default_config()
        self.warnings = []
        self.data = {}
        self.data_path = None
        self.ctx = {}
        self.tables = {}      # key -> 基本处理行
        self.fits = {}        # key -> Kohlrausch 拟合
        self.esa = None       # (Λm∞(HAc), σ)
        self.kmean = None
        self.kfit = None

    # ------------------------------------------------------------ 主流程
    def run(self):
        cfg = self.cfg
        data_dir = cfg.get('data_dir') or DEFAULT_DATA_DIR
        self.data_dir = data_dir
        self.warnings = []

        self.data, self.data_path = conduct.load_data(data_dir)
        self.ctx = conduct.prepare(self.data)

        sols = self.data.get('solutions', {})
        for key in ('NaNO3', 'NaAc', 'HNO3', 'HAc'):
            sol = sols.get(key)
            if not sol or not sol.get('kappa'):
                self.warnings.append('缺少 %s 的测量数据' % conduct.SPECIES_LABEL.get(key, key))
                continue
            rows = conduct.solution_table(sol, self.ctx['kappa_w'])
            if any(not np.isfinite(r['lam']) for r in rows):
                self.warnings.append('%s 数据里有无法解析的读数' % conduct.SPECIES_LABEL.get(key, key))
            self.tables[key] = rows
            if key in STRONG_KEYS:
                self.fits[key] = conduct.kohlrausch(rows)

        missing = [k for k in STRONG_KEYS if k not in self.fits]
        if missing:
            self.warnings.append('强电解质数据不齐（%s），无法求 Λm∞(HAc)' %
                                 '、'.join(conduct.SPECIES_LABEL.get(k, k) for k in missing))
            return self

        combo = self.data.get('combo') or {'add': ['NaAc', 'HNO3'], 'sub': ['NaNO3']}
        lam_hac, sigma_hac = conduct.combo_lambda_inf(self.fits, combo)
        self.esa = dict(lam_inf=lam_hac, sigma=sigma_hac, combo=combo)

        # 文献对比表（表6）
        self.lit_table = []
        for key, lam_exp, sig in (
                ('NaNO3', self.fits['NaNO3']['lam_inf'], self.fits['NaNO3']['sigma_inf']),
                ('NaAc', self.fits['NaAc']['lam_inf'], self.fits['NaAc']['sigma_inf']),
                ('HNO3', self.fits['HNO3']['lam_inf'], self.fits['HNO3']['sigma_inf']),
                ('HAc', lam_hac, sigma_hac)):
            theo = conduct.LAMBDA_THEO[key]
            self.lit_table.append(dict(
                key=key, exp=lam_exp, sigma=sig, theo=theo,
                er=conduct.er_percent(lam_exp, theo)))

        # 弱电解质
        if 'HAc' in self.tables and np.isfinite(lam_hac):
            rows = self.tables['HAc']
            self.kmean = conduct.k_from_mean(rows, lam_hac, sigma_hac)
            self.kfit = conduct.k_from_fit(rows, lam_hac, sigma_hac)
        else:
            self.warnings.append('缺少 HAc 数据或 Λm∞(HAc) 不可用，跳过 K° 计算')

        return self

    # ------------------------------------------------------------ 便捷
    def strong_keys(self):
        return list(STRONG_KEYS)

    def has(self, key):
        return key in self.tables
