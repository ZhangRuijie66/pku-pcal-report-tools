# -*- coding: utf-8 -*-
"""液体饱和蒸气压实验的绘图（复刻课程软件样式）。"""
from __future__ import annotations

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import make_interp_spline

DPI = 600
DPI_PREVIEW = 150

plt.rcParams['font.family'] = ['Times New Roman', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['mathtext.fontset'] = 'stix'

C_DATA = '#696969'      # dimgray，课程软件的散点色
C_CURVE = '#1f77b4'     # 光滑曲线
C_FIT = '#ff8c00'       # darkorange，拟合直线


def _style_axes(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    ax.tick_params(direction='in', length=3.5, width=0.9, labelsize=10,
                   top=True, right=True)
    ax.xaxis.label.set_size(11)
    ax.yaxis.label.set_size(11)


def make_curve_figure(m):
    """蒸气压–温度光滑曲线：全部数据点 + B 样条。"""
    fig, ax = plt.subplots(figsize=(6.6, 4.4), dpi=120)
    pts = sorted(m['fit']['points'], key=lambda r: r['T'])
    x = np.array([r['T'] for r in pts])
    y = np.array([r['p'] for r in pts])
    if x.size >= 4:
        try:
            k = min(3, x.size - 1)
            spl = make_interp_spline(x, y, k=k)
            xx = np.linspace(x.min(), x.max(), 240)
            ax.plot(xx, spl(xx), color=C_CURVE, linewidth=1.2, zorder=2,
                    label='B-spline')
        except Exception:                  # noqa: BLE001
            pass
    ax.plot(x, y, 'o', color=C_DATA, markersize=5, zorder=3, label='实验点')
    ax.set_xlabel(r'$T$ / K')
    ax.set_ylabel(r'$p$ / kPa')
    ax.legend(fontsize=9)
    _style_axes(ax)
    fig.tight_layout()
    return fig


def make_fit_figure(m):
    """ln(p/p⊖)–1/T 拟合直线：散点 + 拟合线 + 方程/R² 注记。"""
    fig, ax = plt.subplots(figsize=(6.6, 4.4), dpi=120)
    fit = m['fit']
    pts = fit['points']
    x = np.array([r['x'] for r in pts])          # 1/T，K⁻¹
    y = np.array([r['lnp'] for r in pts])
    x_ms = x * 1.0e3                             # 图上用 10⁻³ K⁻¹
    ax.plot(x_ms, y, 'o', color=C_DATA, markersize=5, zorder=3, label='实验点')
    pad = max(0.02, (x_ms.max() - x_ms.min()) * 0.08)
    xx_ms = np.linspace(x_ms.min() - pad, x_ms.max() + pad, 80)
    ax.plot(xx_ms, -fit['A'] * (xx_ms / 1.0e3) + fit['B'], color=C_FIT,
            linewidth=1.2, zorder=2, label='线性拟合')
    ax.set_xlabel(r'$1/T\,/\,(10^{-3}\,\mathrm{K}^{-1})$')
    ax.set_ylabel(r'$\ln(p/p^{\ominus})$')
    ax.legend(fontsize=9, loc='lower right')
    ax.text(0.04, 0.16,
            r'$\ln\frac{p}{p^{\ominus}}=-(%.3f\pm%.3f)\times10^{3}\times\frac{1}{T}'
            r'+(%.2f\pm%.2f)$'
            % (fit['A'] / 1e3, fit['sigma_A'] / 1e3,
               fit['B'], fit['sigma_B']),
            transform=ax.transAxes, fontsize=9.5, va='bottom')
    ax.text(0.04, 0.06, r'$R^{2}=%.5f$' % fit['r2'],
            transform=ax.transAxes, fontsize=9.5, va='bottom')
    _style_axes(ax)
    fig.tight_layout()
    return fig
