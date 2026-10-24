# -*- coding: utf-8 -*-
"""双液系实验的绘图（工作曲线、沸点-成分相图）。"""
from __future__ import annotations

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

DPI = 600
DPI_PREVIEW = 150

plt.rcParams['font.family'] = ['Times New Roman', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['mathtext.fontset'] = 'stix'
plt.rcParams['path.simplify'] = True

C_DATA = '#222222'
C_FIT = '#d62728'
C_LIQ = '#1f77b4'
C_VAP = '#d62728'


def _style(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    ax.tick_params(direction='in', length=3.5, width=0.9, labelsize=10,
                   top=True, right=True)
    ax.xaxis.label.set_size(11)
    ax.yaxis.label.set_size(11)


def _x_label(mode):
    return '质量比 m(乙醇)/m(环己烷)' if mode == 'ratio' else '乙醇质量分数'


def _poly_label(fit):
    return '$n=%.5f\\,x^2%+.5f\\,x%+.5f$' % (fit['A'], fit['B'], fit['C'])


def make_curve_figure(curve, which='fit'):
    """标准工作曲线：全部点 + 二次拟合（which='fit_all' 为剔除前的拟合）。"""
    fit = curve[which]
    fig, ax = plt.subplots(figsize=(6.6, 4.4), dpi=120)
    inc = [p for p in curve['points'] if p['in_fit']]
    exc = [p for p in curve['points'] if not p['in_fit']]
    ax.plot([p['x'] for p in inc], [p['n'] for p in inc], 's', color=C_DATA,
            markersize=5, label='数据点')
    if exc:
        ax.plot([p['x'] for p in exc], [p['n'] for p in exc], 'o', mfc='white',
                mec=C_DATA, markersize=5.5, label='剔除点')
    xx = np.linspace(0.0, 1.0, 200)
    yy = fit['A'] * xx ** 2 + fit['B'] * xx + fit['C']
    ax.plot(xx, yy, color=C_FIT, linewidth=1.2, label='二次拟合')
    ax.text(0.04, 0.96, _poly_label(fit), transform=ax.transAxes,
            fontsize=9.5, va='top')
    ax.text(0.04, 0.86, '$R^2=%.5f$' % fit['r2'], transform=ax.transAxes,
            fontsize=9.5, va='top')
    ax.set_xlabel(_x_label(curve['mode']))
    ax.set_ylabel('折射率 n')
    ax.legend(fontsize=9, loc='lower left')
    _style(ax)
    fig.tight_layout()
    return fig


def make_phase_figure(rows, azeo, mode):
    """沸点-成分相图：气相线、液相线与最低恒沸点。"""
    fig, ax = plt.subplots(figsize=(7.0, 5.0), dpi=120)
    T = [r['T_K'] for r in rows]
    if azeo.get('ok'):
        vc, lc = azeo['vapor_curve'], azeo['liquid_curve']
        ax.plot(lc[:, 0], lc[:, 1], '-', color=C_LIQ, linewidth=1.3, label='液相线')
        ax.plot(vc[:, 0], vc[:, 1], '-', color=C_VAP, linewidth=1.3, label='气相线')
        ax.plot([r['wl'] for r in rows], T, 'o', color=C_LIQ, markersize=4.5)
        ax.plot([r['wg'] for r in rows], T, '^', color=C_VAP, markersize=4.5)
        ax.plot([azeo['w']], [azeo['T_K']], '*', color='black', markersize=13)
        ax.annotate('最低恒沸点\n%.2f K, %.3f' % (azeo['T_K'], azeo['w']),
                    xy=(azeo['w'], azeo['T_K']), xytext=(0.72, 0.14),
                    textcoords='axes fraction', fontsize=9.5,
                    arrowprops=dict(arrowstyle='->', linewidth=0.8, color='0.3'))
        ax.axhline(azeo['T_K'], color='0.6', linewidth=0.6, linestyle=':')
    else:
        ax.plot([r['wl'] for r in rows], T, 'o-', color=C_LIQ, markersize=4.5,
                label='液相线')
        ax.plot([r['wg'] for r in rows], T, '^-', color=C_VAP, markersize=4.5,
                label='气相线')
    ax.set_xlabel(_x_label(mode))
    ax.set_ylabel('$T$ / K')
    ax.legend(fontsize=9, loc='upper center')
    _style(ax)
    fig.tight_layout()
    return fig
