# -*- coding: utf-8 -*-
"""磁化率测定 —— 绘图模块。

三张图都用横向散点（样品名在纵轴、数值在横轴），不再用柱状图。
样式与其它实验模块一致：Times New Roman + 微软雅黑、内向刻度、细边框。
"""
from __future__ import annotations

import os

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

C_POS = '#1f77b4'
C_NEG = '#9aa4b2'
C_MU = '#d62728'
C_N = '#2ca02c'
C_ZERO = '#6b7280'


def _style_axes(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    ax.tick_params(direction='in', length=3.5, width=0.9, labelsize=10,
                   top=True, right=True)
    ax.xaxis.label.set_size(11)
    ax.yaxis.label.set_size(11)


def _dot_plot(names, values, xlabel, save_path, dpi=DPI, colors=None,
              fmt='{:.2f}', zero_line=False, hollow=None, zero_label=None):
    """横向散点图：一个样品一个点；hollow 的点用空心圆表示。"""
    if not names:
        return
    hollow = hollow or [False] * len(values)
    y = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(7.0, 3.6), dpi=120)
    if colors is None:
        colors = [C_POS] * len(values)
    solid = [i for i, flag in enumerate(hollow) if not flag]
    empty = [i for i, flag in enumerate(hollow) if flag]
    if solid:
        ax.scatter([values[i] for i in solid], [y[i] for i in solid],
                   s=42, c=[colors[i] for i in solid], edgecolor='white',
                   linewidth=0.8, zorder=3)
    if empty:
        ax.scatter([values[i] for i in empty], [y[i] for i in empty],
                   s=42, facecolors='white', edgecolors=C_NEG,
                   linewidth=0.9, zorder=3,
                   label=zero_label or '记作 0')
    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_ylim(len(names) - 0.4, -0.6)
    ax.tick_params(axis='y', length=0)
    ax.set_xlabel(xlabel)
    if zero_line:
        ax.axvline(0, color=C_ZERO, linewidth=0.8, zorder=1)

    lo = min(0.0, min(values))
    hi = max(0.0, max(values))
    span = hi - lo
    pad = span * 0.18 if span else 1.0
    left = lo - (pad if lo < 0 else 0.0)
    if empty:
        left = min(left, -pad * 0.25)
    ax.set_xlim(left, hi + pad)

    for xi, yi, value, flag in zip(values, y, values, hollow):
        label = '0' if flag else fmt.format(value)
        ax.annotate(label, (xi, yi), xytext=(6, 0),
                    textcoords='offset points', va='center', fontsize=9,
                    color='#333333')
    if empty:
        ax.legend(fontsize=9, loc='lower right', frameon=False)

    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(save_path, dpi=dpi, bbox_inches='tight')
    plt.close(fig)


def plot_molar_susceptibility(chart_data, save_path, title=None, dpi=DPI):
    """各样品摩尔磁化率横向散点图（χ_m 为负的点用灰色）。"""
    rows = [d for d in chart_data if d.get('chi_m') is not None]
    if not rows:
        return
    names = [d['name'] for d in rows]
    values = [d['chi_m'] * 1e6 for d in rows]
    colors = [C_POS if v >= 0 else C_NEG for v in values]
    _dot_plot(names, values,
              r'$\chi_m\ /\ (10^{-6}\ \mathrm{m^3\cdot mol^{-1}})$',
              save_path, dpi=dpi, colors=colors, fmt='{:.3f}',
              zero_line=True)


def plot_magnetic_moment(chart_data, save_path, title=None, dpi=DPI):
    """各样品分子磁矩横向散点图；反磁性样品记作 0（空心点）。"""
    names, values, hollow = [], [], []
    for d in chart_data:
        if d.get('mu') is not None:
            names.append(d['name'])
            values.append(d['mu'])
            hollow.append(False)
        elif d.get('chi_m') is not None and d['chi_m'] < 0:
            names.append(d['name'])
            values.append(0.0)
            hollow.append(True)
    if not names:
        return
    _dot_plot(names, values, r'$\mu$ / $\mu_{\mathrm{B}}$',
              save_path, dpi=dpi,
              colors=[C_NEG if h else C_MU for h in hollow],
              fmt='{:.3f}', hollow=hollow,
              zero_label='反磁性样品（μ=0）')


def plot_unpaired_electrons(chart_data, save_path, title=None, dpi=DPI):
    """各样品未成对电子数横向散点图；反磁性样品记作 0（空心点）。"""
    names, values, hollow = [], [], []
    for d in chart_data:
        if d.get('n') is not None:
            names.append(d['name'])
            values.append(d['n'])
            hollow.append(False)
        elif d.get('chi_m') is not None and d['chi_m'] < 0:
            names.append(d['name'])
            values.append(0.0)
            hollow.append(True)
    if not names:
        return
    _dot_plot(names, values, '未成对电子数 n',
              save_path, dpi=dpi,
              colors=[C_NEG if h else C_N for h in hollow],
              fmt='{:.2f}', hollow=hollow,
              zero_label='反磁性样品（n=0）')


def generate_all_plots(chart_data, save_dir):
    """生成全部图表（报告用 600 dpi）。"""
    os.makedirs(save_dir, exist_ok=True)
    paths = {}
    paths['chi_m'] = os.path.join(save_dir, 'chi_m_comparison.png')
    plot_molar_susceptibility(chart_data, paths['chi_m'], dpi=DPI)
    paths['mu'] = os.path.join(save_dir, 'magnetic_moment.png')
    plot_magnetic_moment(chart_data, paths['mu'], dpi=DPI)
    paths['n'] = os.path.join(save_dir, 'unpaired_electrons.png')
    plot_unpaired_electrons(chart_data, paths['n'], dpi=DPI)
    return paths
