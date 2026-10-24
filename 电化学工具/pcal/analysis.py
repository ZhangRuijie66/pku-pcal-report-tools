# -*- coding: utf-8 -*-
"""循环伏安法解析电极极化 —— 参数模型与一次完整计算。

界面、自检、报告生成都只跟这里的 :class:`Analysis` 打交道：
换参数就重建一个 Analysis 并 ``run()`` 一次，得到全部结果。
"""
from __future__ import annotations

import copy
import os

import numpy as np

from . import echem

# 默认数据目录（2025 参照数据；今年做完实验后在界面上改成自己的目录并「存为默认」）
DEFAULT_DATA_DIR = (r'D:\北大\课程\26秋大三上\物理化学实验'
                    r'\物理化学实验\物理化学实验\电化学\chi的全部附件20251028')

# 平滑窗口 / 起始电位判据 / ESA 积分窗口的默认值（都可在界面上改）
DEFAULT_SMOOTH = 9            # 点（1 mV/点 → 9 mV）
DEFAULT_THRESHOLD_UA = 1.0    # μA，起始电位判据：扣空白信号越过该值
ESA_LO = -0.26                # 氢脱附峰积分下限（= Low E）
ESA_HI = 0.15                 # 积分上限（双电层起点）
DL_LO, DL_HI = 0.10, 0.20     # 自动双电层基线的平均窗口
I_MIN = 3e-8                  # DMFC 电流网格下限 A
I_STEP = 5e-8                 # DMFC 电流网格步长 A


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
        # ---- 数据与文件映射
        'data_dir': DEFAULT_DATA_DIR,
        'file_n2_blank': echem.DEFAULT_FILES['n2_blank'],
        'file_n2_02': echem.DEFAULT_FILES['n2_02'],
        'file_n2_05': echem.DEFAULT_FILES['n2_05'],
        'file_o2_fast': echem.DEFAULT_FILES['o2_fast'],
        'file_o2_slow': echem.DEFAULT_FILES['o2_slow'],
        'file_o2_still': echem.DEFAULT_FILES['o2_still'],
        'file_meoh': echem.DEFAULT_FILES['meoh'],
        # ---- 处理参数
        'smooth_window': DEFAULT_SMOOTH,
        'onset_threshold_uA': DEFAULT_THRESHOLD_UA,
        'esa_lo': ESA_LO,
        'esa_hi': ESA_HI,
        'esa_baseline_uA': None,      # None = 自动（双电层窗口平均）
        'dl_lo': DL_LO,
        'dl_hi': DL_HI,
        'i_min_uA': I_MIN * 1e6,      # DMFC 电流网格下限（μA）
        'i_step_uA': I_STEP * 1e6,    # DMFC 电流网格步长（μA）
    }


PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'room_temp', 'pressure', 'data_dir',
    'file_n2_blank', 'file_n2_02', 'file_n2_05',
    'file_o2_fast', 'file_o2_slow', 'file_o2_still', 'file_meoh',
    'smooth_window', 'onset_threshold_uA',
    'esa_lo', 'esa_hi', 'esa_baseline_uA', 'dl_lo', 'dl_hi',
    'i_min_uA', 'i_step_uA',
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


def _num(v, default=0.0):
    try:
        if v in (None, ''):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


class Analysis:
    """一次完整的实验数据处理。"""

    def __init__(self, config):
        self.cfg = copy.deepcopy(config) if config else default_config()
        self.files = {}          # key -> CvFile
        self.warnings = []
        self.table1 = []
        self.esa = {}
        self.o2 = {}
        self.orr = {}
        self.mor = {}
        self.dmfc = {}

    # ------------------------------------------------------------ 主流程
    def run(self):
        cfg = self.cfg
        data_dir = cfg.get('data_dir') or DEFAULT_DATA_DIR
        self.data_dir = data_dir
        self.warnings = []

        w = int(_num(cfg.get('smooth_window'), DEFAULT_SMOOTH))
        thr = _num(cfg.get('onset_threshold_uA'), DEFAULT_THRESHOLD_UA) * 1e-6
        esa_lo = _num(cfg.get('esa_lo'), ESA_LO)
        esa_hi = _num(cfg.get('esa_hi'), ESA_HI)
        dl_lo = _num(cfg.get('dl_lo'), DL_LO)
        dl_hi = _num(cfg.get('dl_hi'), DL_HI)
        i_min = _num(cfg.get('i_min_uA'), I_MIN * 1e6) * 1e-6
        i_step = _num(cfg.get('i_step_uA'), I_STEP * 1e6) * 1e-6

        # 1) 读文件
        for key in ('n2_blank', 'n2_02', 'n2_05',
                    'o2_fast', 'o2_slow', 'o2_still', 'meoh'):
            path = echem.resolve_file(data_dir, cfg.get('file_' + key))
            if path is None:
                self.warnings.append('找不到数据文件：%s（在 %s 下）'
                                     % (cfg.get('file_' + key), data_dir))
                continue
            try:
                self.files[key] = echem.load_cv(path)
            except (OSError, ValueError, IndexError) as exc:
                self.warnings.append('读取 %s 失败：%s' % (path, exc))
        if 'n2_blank' not in self.files:
            self.warnings.append('缺少空白 CV（N₂ 饱和硫酸，0.1 V·s⁻¹），无法扣空白')
            return self

        blank = self.files['n2_blank']
        v_blank = blank.v

        # 2) 表1：含氧物种脱附峰（负扫 S5，CHI 峰分析给出的相对基线峰高）
        for rate_label, key in echem.SCAN_RATES:
            f = self.files.get(key)
            if f is None:
                continue
            pk = self._oxide_peak(f)
            self.table1.append(dict(v=f.v, label=rate_label, **(pk or {})))
        self.table1.sort(key=lambda r: r['v'])

        # 3) 铂电化学活性面积（0.1 V·s⁻¹，S6 正扫氢脱附峰）
        s6 = blank.seg(6)
        base_cfg = cfg.get('esa_baseline_uA')
        baseline = (_num(base_cfg, None) * 1e-6 if base_cfg not in (None, '')
                    else echem.auto_dl_baseline(s6, dl_lo, dl_hi))
        A = echem.integrate_peak(s6[:, 0], s6[:, 1], esa_lo, esa_hi, baseline)
        Q = A / v_blank if v_blank else float('nan')
        area_cm2 = Q / echem.Q_H_MLAYER if np.isfinite(Q) else float('nan')
        self.esa = dict(A=A, Q=Q, baseline=baseline, lo=esa_lo, hi=esa_hi,
                        area_cm2=area_cm2, area_mm2=area_cm2 * 1e2,
                        v=v_blank)

        # 4) O₂ 系列：还原支（S5）叠加 + ORR 起始电位
        b5 = blank.seg(5)
        b6 = blank.seg(6)
        self.o2 = {}
        for cond, key, label in echem.O2_CONDITIONS:
            f = self.files.get(key)
            if f is None:
                continue
            E5, d5, d5s = echem.diff_vs_blank(f.seg(5), b5, w)
            self.o2[cond] = dict(label=label, file=f.name, v=f.v,
                                 E5=E5, d5=d5, d5s=d5s,
                                 cycle=f.cycle())
        if 'slow' in self.o2:
            E5, d5s = self.o2['slow']['E5'], self.o2['slow']['d5s']
            e_red, _ = echem.first_crossing(E5, d5s, thr, 'above',
                                            e_lo=0.0, e_hi=1.05)
            # 氧化支（S6 正扫）上还原电流消失的电势：用同一条低速搅拌曲线
            E6, _d6, d6s = echem.diff_vs_blank(self.files['o2_slow'].seg(6),
                                               b6, w)
            e_ox, _ = echem.last_crossing(E6, d6s, thr, e_lo=0.0, e_hi=0.95)
            self.orr = dict(onset_red=e_red, onset_ox=e_ox, threshold=thr,
                            E5=E5, d5=d5s, d5_raw=d5, cycle=self.o2['slow']['cycle'])
        else:
            self.orr['onset_red'] = float('nan')
            self.warnings.append('缺少 O₂ 低速搅拌数据，无法确定 ORR 起始还原电位')

        # 5) 甲醇：氧化支（S6）MOR 起始电位
        me = self.files.get('meoh')
        if me is not None:
            E6m, d6m, d6ms = echem.diff_vs_blank(me.seg(6), b6, w)
            e_mor, _ = echem.first_crossing(E6m, d6ms, thr, 'below',
                                            e_lo=-0.10, e_hi=0.60)
            self.mor = dict(onset=e_mor, threshold=thr,
                            E6=E6m, d6=d6ms, d6_raw=d6m, cycle=me.cycle())
        else:
            self.mor['onset'] = float('nan')
            self.warnings.append('缺少甲醇 CV 数据，无法确定 MOR 起始氧化电位')

        # 6) DMFC：扣空白 ORR（还原支）与 MOR（氧化支）量值曲线 → 极化 + 功率
        if np.isfinite(self.orr.get('onset_red', float('nan'))) and \
           np.isfinite(self.mor.get('onset', float('nan'))):
            orr_E = self.orr['E5']
            orr_i = np.abs(self.orr['d5'])
            mor_E = self.mor['E6']
            mor_i = np.abs(self.mor['d6'])
            # 只保留各自起始电位以内的工作区，且沿扫描方向截到电流峰顶
            # （主峰之后的下降沿若混进插值，E_cell 会在假交点提前变负）
            orr_m = (orr_E <= self.orr['onset_red'] + 0.02) & (orr_E >= -0.26)
            mor_m = (mor_E >= self.mor['onset'] - 0.02) & (mor_E <= 0.60)
            orr_E, orr_i = echem.rising_segment(orr_E[orr_m], orr_i[orr_m],
                                                tol=0.05e-6)
            mor_E, mor_i = echem.rising_segment(mor_E[mor_m], mor_i[mor_m],
                                                tol=0.05e-6)
            # 电流网格下限取两支路的最小电流（低于它插值会钳位，
            # 在 P–E 图上画出一段竖直假线）
            i_lo = max(i_min, float(np.min(orr_i)), float(np.min(mor_i)))
            res = echem.dmfc_curves(orr_E, orr_i, mor_E, mor_i,
                                    i_min=i_lo, i_step=i_step)
            if res is None:
                self.warnings.append('DMFC 工作区为空：请检查起始电位判据与平滑窗口')
            else:
                self.dmfc = res
        else:
            self.warnings.append('ORR / MOR 起始电位不齐，跳过 DMFC 计算')

        return self

    # ------------------------------------------------------------ 辅助
    def _oxide_peak(self, f):
        """负扫段（S5）上含氧物种还原峰：取 CHI 峰分析里 Ep 最接近 0.45 V 的那个。"""
        for seg_no in (5, 3, 1):
            lst = f.peaks.get(seg_no) or []
            cand = [p for p in lst if 0.2 <= p['Ep'] <= 0.7]
            if cand:
                p = min(cand, key=lambda p: abs(p['Ep'] - 0.45))
                return dict(Ep=p['Ep'], ip=p['ip'], seg=seg_no)
        return dict(Ep=float('nan'), ip=float('nan'), seg=0)

    def _slow_seg6(self):
        f = self.files.get('o2_slow')
        return f.seg(6) if f else None

    # ------------------------------------------------------------ 便捷
    def file(self, key):
        return self.files.get(key)
