# -*- coding: utf-8 -*-
"""循环伏安法实验的绘图（复刻 2025 参考报告里 Origin 图的样式）。

样式约定（与参考报告逐图对齐）：
    · CV 曲线图纵轴一律倒置（阴极电流向下、阳极电流向上），与 CHI/Origin 显示一致
    · 图2 三个扫速：0.5 黑 / 0.2 红 / 0.1 蓝；图4：N₂ 黑、静止 红、低速 蓝、快速 绿
    · 图5/图7 叠加图：待测曲线深红、空白浅粉
    · 图8 扣空白曲线按电流量值画（普通轴向，峰朝上）
"""
from __future__ import annotations

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

DPI = 600
DPI_PREVIEW = 130

plt.rcParams['font.family'] = ['Times New Roman', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['mathtext.fontset'] = 'stix'
plt.rcParams['path.simplify'] = True
plt.rcParams['path.simplify_threshold'] = 0.5
plt.rcParams['agg.path.chunksize'] = 10000

C_N2 = 'black'
C_STILL = '#d62728'      # 红
C_SLOW = '#1f77b4'       # 蓝
C_FAST = '#2ca02c'       # 绿
C_MAIN = '#c00000'       # 叠加图里的待测曲线（深红）
C_BLANK = '#e8a8b0'      # 空白（浅粉）
C_ORR = 'black'
C_MOR = '#d62728'

E_LABEL = r'$E$(vs. SCE) / V'
I_LABEL = r'$i$ / $10^{-6}$A'

XLIM = (-0.4, 1.2)


def _style_axes(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    ax.tick_params(direction='in', length=3.5, width=0.9, labelsize=10,
                   top=True, right=True)
    ax.xaxis.label.set_size(11)
    ax.yaxis.label.set_size(11)


def _cv_axes(ax, y_ua=None, invert=True, xlim=XLIM):
    """CV 图的公共轴样式：倒置纵轴、电势窗口。"""
    ax.set_xlabel(E_LABEL)
    ax.set_ylabel(I_LABEL)
    ax.set_xlim(*xlim)
    if y_ua is not None and len(y_ua):
        lo, hi = float(np.min(y_ua)), float(np.max(y_ua))
        pad = max(0.08 * (hi - lo), 0.3)
        ax.set_ylim(lo - pad, hi + pad)
    if invert:
        ax.invert_yaxis()
    _style_axes(ax)


def _smooth(y, w):
    w = int(w)
    if w <= 1:
        return np.asarray(y, float)
    if w % 2 == 0:
        w += 1
    # 反射填充后再卷积：'same' 模式的零填充会让曲线两端假性跌落
    y = np.asarray(y, float)
    pad = w // 2
    yp = np.pad(y, pad, mode='reflect')
    return np.convolve(yp, np.ones(w) / w, mode='same')[pad:-pad]


# ---------------------------------------------------------------- 图2 三扫速
def make_n2_series_figure(an):
    """N₂ 饱和硫酸溶液三个扫速的整圈 CV 叠加（图2）。"""
    fig, ax = plt.subplots(figsize=(6.2, 4.6), dpi=DPI_PREVIEW)
    colors = {'0.5': 'black', '0.2': '#d62728', '0.1': '#1f77b4'}
    ys = []
    for rate_label, key in (('0.5', 'n2_05'), ('0.2', 'n2_02'),
                            ('0.1', 'n2_blank')):
        f = an.file(key)
        if f is None:
            continue
        cyc = f.cycle()
        E, I = cyc[:, 0], cyc[:, 1] * 1e6
        ax.plot(E, _smooth(I, an.cfg.get('smooth_window', 9)),
                color=colors[rate_label], linewidth=1.0,
                label='%s V·s⁻¹' % rate_label)
        ys.append(I)
    ax.legend(frameon=False, fontsize=10, loc='lower right')
    _cv_axes(ax, np.concatenate(ys) if ys else None)
    return fig


# ---------------------------------------------------------------- 图3 ESA
def make_esa_figure(an):
    """0.1 V·s⁻¹ 的 CV 与氢脱附峰积分区域（图3，阴影 = 扣基线后的积分区）。"""
    esa = an.esa
    f = an.file('n2_blank')
    cyc = f.cycle()
    E, I = cyc[:, 0], cyc[:, 1] * 1e6
    w = an.cfg.get('smooth_window', 9)
    Is = _smooth(I, w)
    base = esa['baseline'] * 1e6

    fig, ax = plt.subplots(figsize=(6.2, 4.6), dpi=DPI_PREVIEW)
    ax.plot(E, Is, color='black', linewidth=1.0)
    ax.axhline(base, color='gray', linewidth=0.8, linestyle='--')
    # 阴影只取 S6 正扫段的氢区（脱附峰为阳极、电流为负），
    # 不能用整圈数组——S5 负扫段的尾巴（氢吸附峰）也落在同一电势窗口里
    s6 = f.seg(6)
    E6, I6 = s6[:, 0], _smooth(s6[:, 1], w) * 1e6
    m = (E6 >= esa['lo']) & (E6 <= esa['hi'])
    ax.fill_between(E6[m], base, I6[m],
                    color='gray', alpha=0.25, linewidth=0)
    _cv_axes(ax, I)
    return fig


# ---------------------------------------------------------------- 图4 O₂ 搅拌系列
def make_o2_series_figure(an):
    """不同搅拌条件还原支（S5）与 N₂ 空白叠加（图4）。"""
    fig, ax = plt.subplots(figsize=(6.2, 4.6), dpi=DPI_PREVIEW)
    ys = []
    b = an.file('n2_blank')
    if b is not None:
        s5 = b.seg(5)
        E, I = s5[:, 0], _smooth(s5[:, 1], an.cfg.get('smooth_window', 9)) * 1e6
        ax.plot(E, I, color=C_N2, linewidth=1.0, label='N₂')
        ys.append(I)
    for cond, color in (('still', C_STILL), ('slow', C_SLOW), ('fast', C_FAST)):
        it = an.o2.get(cond)
        if not it:
            continue
        f = an.file('o2_' + cond)
        s5 = f.seg(5)
        E, I = s5[:, 0], _smooth(s5[:, 1], an.cfg.get('smooth_window', 9)) * 1e6
        ax.plot(E, I, color=color, linewidth=1.0, label='O₂-' + it['label'])
        ys.append(I)
    ax.legend(frameon=False, fontsize=10, loc='lower right')
    _cv_axes(ax, np.concatenate(ys) if ys else None)
    return fig


# ---------------------------------------------------------------- 图5 N₂/O₂ 对比
def make_orr_overlay_figure(an):
    """O₂ 低速搅拌与 N₂ 空白的整圈 CV 叠加（图5）。"""
    fig, ax = plt.subplots(figsize=(6.2, 4.6), dpi=DPI_PREVIEW)
    ys = []
    b = an.file('n2_blank')
    if b is not None:
        cyc = b.cycle()
        E, I = cyc[:, 0], _smooth(cyc[:, 1], an.cfg.get('smooth_window', 9)) * 1e6
        ax.plot(E, I, color=C_BLANK, linewidth=1.1, label='N₂饱和')
        ys.append(I)
    o = an.file('o2_slow')
    if o is not None:
        cyc = o.cycle()
        E, I = cyc[:, 0], _smooth(cyc[:, 1], an.cfg.get('smooth_window', 9)) * 1e6
        ax.plot(E, I, color=C_MAIN, linewidth=1.1, label='O₂饱和')
        ys.append(I)
    ax.legend(frameon=False, fontsize=10, loc='lower right')
    _cv_axes(ax, np.concatenate(ys) if ys else None)
    return fig


# ---------------------------------------------------------------- 图6 甲醇 CV
def make_meoh_figure(an):
    """N₂ 饱和甲醇 + 硫酸的整圈 CV（图6）。"""
    f = an.file('meoh')
    if f is None:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, 'no methanol data', ha='center', va='center')
        return fig
    cyc = f.cycle()
    E, I = cyc[:, 0], _smooth(cyc[:, 1], an.cfg.get('smooth_window', 9)) * 1e6
    fig, ax = plt.subplots(figsize=(6.2, 4.6), dpi=DPI_PREVIEW)
    ax.plot(E, I, color=C_MAIN, linewidth=1.1)
    _cv_axes(ax, I)
    return fig


# ---------------------------------------------------------------- 图7 甲醇/空白
def make_mor_overlay_figure(an):
    """甲醇与空白溶液整圈 CV 叠加（图7）。"""
    fig, ax = plt.subplots(figsize=(6.2, 4.6), dpi=DPI_PREVIEW)
    ys = []
    b = an.file('n2_blank')
    if b is not None:
        cyc = b.cycle()
        E, I = cyc[:, 0], _smooth(cyc[:, 1], an.cfg.get('smooth_window', 9)) * 1e6
        ax.plot(E, I, color=C_BLANK, linewidth=1.1, label='空白')
        ys.append(I)
    f = an.file('meoh')
    if f is not None:
        cyc = f.cycle()
        E, I = cyc[:, 0], _smooth(cyc[:, 1], an.cfg.get('smooth_window', 9)) * 1e6
        ax.plot(E, I, color=C_MAIN, linewidth=1.1, label='甲醇')
        ys.append(I)
    ax.legend(frameon=False, fontsize=10, loc='upper right')
    _cv_axes(ax, np.concatenate(ys) if ys else None)
    return fig


# ---------------------------------------------------------------- 图8 ORR/MOR
def make_orr_mor_figure(an):
    """扣空白后的 ORR（还原支）与 MOR（氧化支）电流量值曲线（图8）。"""
    fig, ax = plt.subplots(figsize=(6.8, 4.4), dpi=DPI_PREVIEW)
    ys = []
    if an.orr.get('E5') is not None:
        i = np.abs(an.orr['d5']) * 1e6
        ax.plot(an.orr['E5'], i, color=C_ORR, linewidth=1.1, label='ORR')
        ys.append(i)
    if an.mor.get('E6') is not None:
        i = np.abs(an.mor['d6']) * 1e6
        ax.plot(an.mor['E6'], i, color=C_MOR, linewidth=1.1, label='MOR')
        ys.append(i)
    ax.axhline(0, color='gray', linewidth=0.7)
    if ys:
        top = max(float(np.max(y)) for y in ys)
        ax.set_ylim(-0.6, top * 1.12)
    ax.set_xlabel(E_LABEL)
    ax.set_ylabel(I_LABEL)
    ax.set_xlim(*XLIM)
    ax.legend(frameon=False, fontsize=10, loc='upper left')
    _style_axes(ax)
    return fig


# ---------------------------------------------------------------- 图9 极化曲线
def make_dmfc_polarization_figure(an):
    """DMFC 极化曲线（图9）：横轴电流画成负值，纵轴电势。"""
    d = an.dmfc
    if not d:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, 'no DMFC data', ha='center', va='center')
        return fig
    fig, ax = plt.subplots(figsize=(6.4, 4.4), dpi=DPI_PREVIEW)
    i = d['i_grid'] * 1e6
    ax.plot(-i, d['E_orr'], color=C_ORR, linewidth=1.1, label='ORR')
    ax.plot(-i, d['E_mor'], color=C_MOR, linewidth=1.1, label='MOR')
    ax.set_xlabel(r'$i$ / $10^{-6}$A')
    ax.set_ylabel(r'$E$(vs. SCE) / V')
    ax.set_xlim(0, -float(np.max(i)) * 1.06)
    ax.set_ylim(0, 0.7)
    ax.legend(frameon=False, fontsize=10, loc='center right')
    _style_axes(ax)
    return fig


# ---------------------------------------------------------------- 图10 功率曲线
def make_dmfc_power_figure(an):
    """DMFC 输出电压-输出功率曲线（图10）。"""
    d = an.dmfc
    if not d:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, 'no DMFC data', ha='center', va='center')
        return fig
    fig, ax = plt.subplots(figsize=(6.4, 4.4), dpi=DPI_PREVIEW)
    E_cell, P = d['E_cell'], d['P'] * 1e9   # nW
    ax.plot(E_cell, P, color='black', linewidth=1.1)
    k = int(np.argmax(P))
    ax.plot([E_cell[k]], [P[k]], 'o', color='black', markersize=4)
    ax.annotate('%.2f nW' % P[k], (E_cell[k], P[k]),
                textcoords='offset points', xytext=(8, 2), fontsize=9)
    ax.set_xlabel(r'$E_{cell}$ / V')
    ax.set_ylabel(r'$P$ / $10^{-9}$W')
    ax.set_xlim(0, max(0.6, float(np.max(E_cell)) * 1.05))
    ax.set_ylim(bottom=min(0, float(np.min(P))))
    _style_axes(ax)
    return fig
