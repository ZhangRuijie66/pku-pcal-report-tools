# -*- coding: utf-8 -*-
"""偶极矩实验的绘图（复刻课程软件样式）。"""
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

C_DATA = '#696969'      # dimgray，课程软件的散点色
C_FIT = '#ff8c00'       # darkorange，拟合直线


def _style_axes(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    ax.tick_params(direction='in', length=3.5, width=0.9, labelsize=10,
                   top=True, right=True)
    ax.xaxis.label.set_size(11)
    ax.yaxis.label.set_size(11)


def _fit_figure(xs, ys, fit, xlabel, ylabel, eq_text, name):
    fig, ax = plt.subplots(figsize=(6.2, 4.2), dpi=120)
    x = np.asarray(xs, float)
    y = np.asarray(ys, float)
    ax.plot(x, y, 'o', color=C_DATA, markersize=5.5, zorder=3, label='实验点')
    pad_x = max(0.004, (x.max() - x.min()) * 0.08)
    pad_y = max(0.01, (y.max() - y.min()) * 0.10)
    xx = np.linspace(x.min() - pad_x, x.max() + pad_x, 80)
    ax.plot(xx, fit['slope'] * xx + fit['intercept'], color=C_FIT,
            linewidth=1.2, zorder=2, label='线性拟合')
    lo = min(y.min(), (fit['slope'] * xx + fit['intercept']).min())
    hi = max(y.max(), (fit['slope'] * xx + fit['intercept']).max())
    ax.set_ylim(lo - pad_y, hi + pad_y)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.legend(fontsize=9, loc='upper left')
    ax.text(0.05, 0.16, eq_text, transform=ax.transAxes, fontsize=9.5,
            va='bottom')
    ax.text(0.05, 0.06, r'$R^{2}=%.4f$' % fit['r2'],
            transform=ax.transAxes, fontsize=9.5, va='bottom')
    _style_axes(ax)
    fig.tight_layout()
    return fig


def make_eps_figure(r):
    fit = r['eps_fit']
    eq = (r'$\varepsilon=(%.3f\pm%.3f)\,x+(%.3f\pm%.3f)$'
          % (fit['slope'], fit['sigma_slope'],
             fit['intercept'], fit['sigma_intercept']))
    return _fit_figure([s['x'] for s in r['solutions']],
                       [s['eps'] for s in r['solutions']],
                       fit, r'$x$', r'$\varepsilon$', eq, 'eps')


def make_rho_figure(r):
    fit = r['rho_fit']
    eq = (r'$\rho=(%.4f\pm%.4f)\,x+(%.5f\pm%.5f)$'
          % (fit['slope'], fit['sigma_slope'],
             fit['intercept'], fit['sigma_intercept']))
    return _fit_figure([s['x'] for s in r['solutions']],
                       [s['rho'] for s in r['solutions']],
                       fit, r'$x$', r'$\rho$ / (g$\cdot$cm$^{-3}$)',
                       eq, 'rho')
