# -*- coding: utf-8 -*-
"""电导率实验的绘图（复刻 2025 参考报告里 Origin 图的样式）。

图2：κ校–c 三溶液折线（黑方 NaNO₃ / 红圆 HNO₃ / 蓝三角 HAc）
图3~5：强电解质 Λm–√c 拟合（黑点 + 红色拟合直线）
图6：HAc 的 (c/c°)Λm–1/Λm 拟合
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
plt.rcParams['agg.path.chunksize'] = 10000

C_NANO3 = '#3b3b3b'
C_HNO3 = '#d62728'
C_HAC = '#1f77b4'
C_FIT = 'red'
C_DATA = 'black'


def _style_axes(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    ax.tick_params(direction='in', length=3.5, width=0.9, labelsize=10,
                   top=True, right=True)
    ax.xaxis.label.set_size(11)
    ax.yaxis.label.set_size(11)


def _pad_lim(lo, hi, pad_frac=0.06):
    pad = (hi - lo) * pad_frac
    return lo - pad, hi + pad


# ---------------------------------------------------------------- 图2
def make_kappa_c_figure(an):
    """κ校–c 关系曲线（NaNO₃ / HNO₃ / HAc）。"""
    fig, ax = plt.subplots(figsize=(6.2, 4.4), dpi=DPI_PREVIEW)
    series = [
        ('NaNO3', C_NANO3, 's', 'NaNO$_3$'),
        ('HNO3', C_HNO3, 'o', 'HNO$_3$'),
        ('HAc', C_HAC, '^', 'HAc'),
    ]
    xs, ys = [], []
    for key, color, marker, label in series:
        rows = an.tables.get(key)
        if not rows:
            continue
        x = [r['c'] for r in rows]
        y = [r['kappa_corr'] for r in rows]
        ax.plot(x, y, color=color, marker=marker, markersize=4.5,
                linewidth=1.0, label=label)
        xs += x
        ys += y
    ax.set_xlabel(r'$c$ / mol·m$^{-3}$')
    ax.set_ylabel(r'$\kappa_{corrected}$ / S·m$^{-1}$')
    if xs:
        ax.set_xlim(*_pad_lim(-0.5, max(xs)))
        ax.set_ylim(*_pad_lim(min(0.0, min(ys)), max(ys)))
    ax.legend(frameon=False, fontsize=10, loc='upper left')
    _style_axes(ax)
    return fig


# ---------------------------------------------------------------- 图3~5
def make_kohlrausch_figure(an, key):
    """强电解质 Λm–√c 拟合直线。"""
    fit = an.fits.get(key)
    if not fit:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, 'no data', ha='center', va='center')
        return fig
    x = np.array(fit['x'], float)
    y = np.array(fit['y'], float)
    fig, ax = plt.subplots(figsize=(5.6, 4.2), dpi=DPI_PREVIEW)
    ax.plot(x, y, 'o', color=C_DATA, markersize=5, zorder=4)
    xlo, xhi = 0.0, float(x.max()) * 1.08
    xx = np.linspace(xlo, xhi, 50)
    y_line_lo = float(fit['k'] * xhi + fit['b'])
    y_line_hi = float(fit['b'])
    ax.plot(xx, fit['k'] * xx + fit['b'], color=C_FIT, linewidth=1.2, zorder=3)
    ax.set_xlabel(r'$c^{1/2}$ / mol$^{1/2}$·m$^{-3/2}$')
    ax.set_ylabel(r'$\Lambda_{m}$ / S·m$^{2}$·mol$^{-1}$')
    ax.set_xlim(xlo, xhi)
    lo = min(y.min(), y_line_lo, y_line_hi)
    hi = max(y.max(), y_line_lo, y_line_hi)
    ax.set_ylim(*_pad_lim(lo, hi, 0.12))
    _style_axes(ax)
    return fig


# ---------------------------------------------------------------- 图6
def make_kfit_figure(an):
    """HAc 的 (c/c°)Λm–1/Λm 拟合直线。"""
    fit = an.kfit
    if not fit:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, 'no data', ha='center', va='center')
        return fig
    x = np.array(fit['x'], float)
    y = np.array(fit['y'], float)
    fig, ax = plt.subplots(figsize=(5.6, 4.2), dpi=DPI_PREVIEW)
    ax.plot(x, y, 'o', color=C_DATA, markersize=5, zorder=4)
    xlo, xhi = float(x.min()) * 0.9, float(x.max()) * 1.1
    xx = np.linspace(xlo, xhi, 50)
    ax.plot(xx, fit['k'] * xx + fit['b'], color=C_FIT, linewidth=1.2, zorder=3)
    ax.set_xlabel(r'$1/\Lambda_{m}$ / mol·m$^{-2}$·S$^{-1}$')
    ax.set_ylabel(r'$(c/c^{\ominus})\Lambda_{m}$ / S·m$^{2}$·mol$^{-1}$')
    ax.set_xlim(xlo, xhi)
    ys = [y.min(), y.max(), float(fit['k'] * xlo + fit['b']),
          float(fit['k'] * xhi + fit['b'])]
    ax.set_ylim(*_pad_lim(min(ys), max(ys), 0.15))
    _style_axes(ax)
    return fig
