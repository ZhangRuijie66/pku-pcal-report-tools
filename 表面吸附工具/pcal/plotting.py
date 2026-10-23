# -*- coding: utf-8 -*-
"""溶液表面吸附实验的绘图。"""
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
plt.rcParams['path.simplify'] = True

C_DATA = '#222222'
C_FIT = '#d62728'
C_BLUE = '#1f77b4'
C_ORANGE = '#ff7f0e'


def _style_axes(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    ax.tick_params(direction='in', length=3.5, width=0.9, labelsize=10,
                   top=True, right=True)
    ax.xaxis.label.set_size(11)
    ax.yaxis.label.set_size(11)


def _xcol(method, axis):
    return [np.log10(r['c']) if axis == 'lg' else np.log(r['c'])
            for r in method['rows']]


def _xlabel(axis):
    return r'$\lg(c/\mathrm{mol\cdot dm^{-3}})$' if axis == 'lg' \
        else r'$\ln(c/\mathrm{mol\cdot dm^{-3}})$'


def _smooth(x, y):
    """按 B 样条连接数据点；点太少时退回折线。"""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    order = np.argsort(x)
    x, y = x[order], y[order]
    if x.size < 4:
        return x, y
    try:
        k = min(3, x.size - 1)
        spl = make_interp_spline(x, y, k=k)
        xx = np.linspace(x.min(), x.max(), 240)
        return xx, spl(xx)
    except Exception:                      # noqa: BLE001
        return x, y


def make_curve_figure(method):
    """γ–lg c（或 γ–ln c）曲线：全部点 + 误差棒 + B 样条。"""
    fig, ax = plt.subplots(figsize=(7.2, 4.4), dpi=120)
    x = _xcol(method, method['axis'])
    y = [r['gamma'] for r in method['rows']]
    e = [r['sigma_gamma'] for r in method['rows']]
    fit = [r['fit'] for r in method['rows']]

    xx, yy = _smooth(x, y)
    ax.plot(xx, yy, color=C_BLUE, linewidth=1.0, zorder=2,
            label='B-spline')
    xf = [xi for xi, f in zip(x, fit) if f]
    yf = [yi for yi, f in zip(y, fit) if f]
    ef = [ei for ei, f in zip(e, fit) if f]
    xn = [xi for xi, f in zip(x, fit) if not f]
    yn = [yi for yi, f in zip(y, fit) if not f]
    en = [ei for ei, f in zip(e, fit) if not f]
    if xf:
        ax.errorbar(xf, yf, yerr=ef, fmt='s', color=C_FIT, markersize=4.8,
                    capsize=2.5, linewidth=0.9, zorder=4,
                    label='线性区选点')
    if xn:
        ax.errorbar(xn, yn, yerr=en, fmt='o', mfc='white', mec=C_DATA,
                    ecolor=C_DATA, markersize=4.4, capsize=2.5,
                    linewidth=0.8, zorder=3, label='其余点')
    ax.set_xlabel(_xlabel(method['axis']))
    ax.set_ylabel(r'$\gamma$ / (mN$\cdot$m$^{-1}$)')
    ax.legend(fontsize=9, loc='upper right')
    _style_axes(ax)
    fig.tight_layout()
    return fig


def make_fit_figure(method):
    """线性区拟合：散点 + 拟合直线 + 方程/Γ∞ 注记。"""
    fig, ax = plt.subplots(figsize=(6.8, 4.4), dpi=120)
    rows = method['fit_rows']
    if not rows:
        ax.text(0.5, 0.5, 'no fit points', ha='center', va='center')
        ax.axis('off')
        return fig
    axis = method['axis']
    x = np.array([np.log10(r['c']) if axis == 'lg' else np.log(r['c'])
                  for r in rows], float)
    y = np.array([r['gamma'] for r in rows], float)
    e = np.array([r['sigma_gamma'] for r in rows], float)
    fit = method['fit']
    ax.errorbar(x, y, yerr=e, fmt='s', color=C_DATA, markersize=5,
                capsize=3, linewidth=0.9, zorder=3, label='实验点')
    lo, hi = x.min(), x.max()
    pad = max(0.12, (hi - lo) * 0.12)
    xx = np.linspace(lo - pad, hi + pad, 80)
    # fit['slope'] 的单位是 J·m⁻²；图上 γ 用 mN·m⁻¹，所以乘 1e3
    ax.plot(xx, (fit['slope'] * xx + fit['intercept']) * 1e3,
            color=C_FIT, linewidth=1.2, zorder=2, label='线性拟合')
    ax.set_xlabel(_xlabel(axis))
    ax.set_ylabel(r'$\gamma$ / (mN$\cdot$m$^{-1}$)')
    ax.legend(fontsize=9, loc='upper right')
    fn = r'\lg' if axis == 'lg' else r'\ln'
    ax.text(0.04, 0.21,
            r'$\gamma=(%.4f\pm%.4f)%s\,c+(%.4f\pm%.4f)$'
            % (fit['slope'] * 1e3, fit['sigma_slope'] * 1e3, fn,
               fit['intercept'] * 1e3, fit['sigma_intercept'] * 1e3),
            transform=ax.transAxes, fontsize=9.5, va='bottom')
    ax.text(0.04, 0.115, r'$R^{2}=%.4f$' % fit['r2'],
            transform=ax.transAxes, fontsize=9.5, va='bottom')
    ax.text(0.04, 0.03,
            r'$\Gamma_{\infty}=%.3f\times10^{-6}\ \mathrm{mol\cdot m^{-2}}$'
            % (method['gamma_inf'] * 1e6),
            transform=ax.transAxes, fontsize=9.5, va='bottom')
    _style_axes(ax)
    fig.tight_layout()
    return fig


def make_qc_figure(result):
    """两种方法的 q_c–c 对比图。"""
    fig, ax = plt.subplots(figsize=(7.0, 4.4), dpi=120)
    any_data = False
    for m, color, marker in ((result['bubble'], C_BLUE, 's'),
                             (result['plate'], C_ORANGE, 'o')):
        rows = [r for r in m['qc_rows'] if np.isfinite(r['qc'])]
        if not rows:
            continue
        any_data = True
        c = [r['c'] for r in rows]
        qc = [r['qc'] for r in rows]
        e = [r['sigma'] for r in rows]
        ax.errorbar(c, qc, yerr=e, fmt=marker, color=color, markersize=5,
                    capsize=2.5, linewidth=0.9, label=m['label'])
        if np.isfinite(m['q']):
            ax.axhline(m['q'], color=color, linestyle='--', linewidth=0.8,
                       alpha=0.75)
    if not any_data:
        ax.text(0.5, 0.5, 'no data', ha='center', va='center')
        ax.axis('off')
        return fig
    ax.set_xlabel(r'$c$ / (mol$\cdot$dm$^{-3}$)')
    ax.set_ylabel(r'$q_c$ / nm$^{2}$')
    ax.legend(fontsize=9)
    _style_axes(ax)
    fig.tight_layout()
    return fig
