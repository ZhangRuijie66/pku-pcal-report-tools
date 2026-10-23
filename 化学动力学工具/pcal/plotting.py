# -*- coding: utf-8 -*-
"""化学反应动力学实验的绘图。"""
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
PALETTE = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
           '#8c564b', '#e377c2', '#7f7f7f']


def _style(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    ax.tick_params(direction='in', length=3.5, width=0.9, labelsize=10,
                   top=True, right=True)
    ax.xaxis.label.set_size(11)
    ax.yaxis.label.set_size(11)


def make_calibration_figure(cal):
    """α–c 标定：全部点 + 95% 置信带 + 拟合直线。"""
    fig, ax = plt.subplots(figsize=(6.6, 4.4), dpi=120)
    pts = cal['points']
    inc = [p for p in pts if not p['exclude']]
    exc = [p for p in pts if p['exclude']]
    if inc:
        ax.plot([p['c'] for p in inc], [p['alpha'] for p in inc], 's',
                color=C_DATA, markersize=5, label='included')
    if exc:
        ax.plot([p['c'] for p in exc], [p['alpha'] for p in exc], 'o',
                mfc='white', mec=C_DATA, markersize=5.5, label='excluded')
    fit = cal['fit']
    if fit:
        x = np.array([p['c'] for p in pts], float)
        xx = np.linspace(0, float(x.max()) * 1.06, 100)
        ax.plot(xx, fit['slope'] * xx + fit['intercept'], color=C_FIT,
                linewidth=1.2, label='fit')
        ci = fit.get('ci')
        if ci:
            ax.fill_between(ci['x'], ci['lo'], ci['hi'], color=C_FIT,
                            alpha=0.12, linewidth=0)
        ax.text(0.04, 0.96,
                r'$\alpha=(%.2f\pm%.2f)c+(%.3f\pm%.3f)$'
                % (fit['slope'], fit['sigma_slope'], fit['intercept'],
                   fit['sigma_intercept']),
                transform=ax.transAxes, fontsize=9.5, va='top')
        ax.text(0.04, 0.86, r'$R^{2}=%.5f$' % fit['r2'],
                transform=ax.transAxes, fontsize=9.5, va='top')
    ax.set_xlabel(r'$c$ / (g$\cdot$mL$^{-1}$)')
    ax.set_ylabel(r'$\alpha$ / ($^\circ$)')
    ax.legend(fontsize=9, loc='lower right')
    _style(ax)
    fig.tight_layout()
    return fig


def make_alpha_t_figure(groups):
    """不同酸浓度下的 α–t 曲线。"""
    fig, ax = plt.subplots(figsize=(8.2, 4.6), dpi=120)
    for i, g in enumerate(groups):
        color = PALETTE[i % len(PALETTE)]
        data = np.asarray(g.get('all_data') or [], float)
        if data.size:
            ax.plot(data[:, 0], data[:, 1], '-o', color=color, markersize=3.0,
                    linewidth=0.7, label='%s M' % g['label'].replace('M', ''))
        ex = set(g.get('exclude') or [])
        if ex and data.size:
            pts = [data[j] for j in sorted(ex) if j < len(data)]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], 'x',
                    color=color, markersize=5, markeredgewidth=1.0)
    ax.set_xlabel(r'$t$ / s')
    ax.set_ylabel(r'$\alpha$ / ($^\circ$)')
    ax.legend(fontsize=9)
    _style(ax)
    fig.tight_layout()
    return fig


def _order_y(alpha, alpha_inf, order):
    a = np.asarray(alpha, float)
    if order == 0:
        return a
    d = a - float(alpha_inf)
    if order == 1:
        y = np.full_like(d, np.nan)
        ok = d > 0
        y[ok] = np.log(d[ok])
        return y
    y = np.full_like(d, np.nan)
    ok = d != 0
    y[ok] = 1.0 / d[ok]
    return y


def make_order_figure(group):
    """零级 / 一级 / 二级的线性化尝试（三联图）。"""
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.5), dpi=120)
    titles = ['Zero order', 'First order', 'Second order']
    ylabels = [r'$\alpha$ / ($^\circ$)', r'$\ln(\alpha-\alpha_\infty)$',
               r'$1/(\alpha-\alpha_\infty)$ / $^\circ{}^{-1}$']
    for order in (0, 1, 2):
        ax = axes[order]
        fit = group['fits'].get(str(order))
        if not fit:
            ax.text(0.5, 0.5, 'no data', ha='center', va='center')
            ax.axis('off')
            continue
        ax.plot(fit['x'], fit['y'], 'o', color=C_DATA, markersize=3.2)
        xx = np.array(fit['x'], float)
        lo, hi = float(xx.min()), float(xx.max())
        pad = max(10.0, (hi - lo) * 0.04)
        grid = np.linspace(lo - pad, hi + pad, 50)
        ax.plot(grid, fit['slope'] * grid + fit['intercept'],
                color=C_FIT, linewidth=1.1)
        ax.set_title(titles[order], fontsize=10.5)
        ax.set_xlabel(r'$t$ / s')
        ax.set_ylabel(ylabels[order])
        ax.text(0.05, 0.94, r'$R^{2}=%.5f$' % fit['r2'],
                transform=ax.transAxes, fontsize=9, va='top')
        _style(ax)
    fig.tight_layout()
    return fig


def make_first_order_figure(groups):
    """各酸浓度的一级拟合 ln(α−α∞)–t。"""
    fig, ax = plt.subplots(figsize=(7.4, 4.8), dpi=120)
    for i, g in enumerate(groups):
        fit = g['fits'].get('1')
        if not fit:
            continue
        color = PALETTE[i % len(PALETTE)]
        ax.plot(fit['x'], fit['y'], 'o', color=color, markersize=3.0)
        xx = np.array(fit['x'], float)
        grid = np.linspace(float(xx.min()), float(xx.max()), 50)
        ax.plot(grid, fit['slope'] * grid + fit['intercept'],
                color=color, linewidth=1.0,
                label='%s M  ($R^2$=%.4f)'
                % (g['label'].replace('M', ''), fit['r2']))
    ax.set_xlabel(r'$t$ / s')
    ax.set_ylabel(r'$\ln(\alpha-\alpha_\infty)$')
    ax.legend(fontsize=8.5)
    _style(ax)
    fig.tight_layout()
    return fig


def make_rate_law_figure(rl):
    """k1–c(H+) 非线性拟合。"""
    fig, ax = plt.subplots(figsize=(6.6, 4.4), dpi=120)
    cH = np.array(rl['cH'], float)
    k = np.array(rl['k'], float) * 1e3
    ax.plot(cH, k, 's', color=C_DATA, markersize=5.5, label='data')
    xx = np.linspace(0, float(cH.max()) * 1.06, 120)
    yy = (rl['k0'] + rl['k_h'] * np.power(xx, rl['n'])) * 1e3
    ax.plot(xx, yy, color=C_FIT, linewidth=1.2, label='fit')
    ax.text(0.04, 0.96,
            r'$k_1=%.3f\times10^{-4}+%.3f\times10^{-4}c^{\,%.2f}$'
            % (rl['k0'] * 1e4, rl['k_h'] * 1e4, rl['n']),
            transform=ax.transAxes, fontsize=9.2, va='top')
    ax.text(0.04, 0.86, r'$n=%.2f\pm%.2f,\quad R^{2}=%.4f$'
            % (rl['n'], rl['sigma_n'], rl['r2']),
            transform=ax.transAxes, fontsize=9.2, va='top')
    ax.set_xlabel(r'$c(\mathrm{H}^{+})$ / (mol$\cdot$L$^{-1}$)')
    ax.set_ylabel(r'$k_1$ / ($10^{-3}$ s$^{-1}$)')
    ax.legend(fontsize=9, loc='lower right')
    _style(ax)
    fig.tight_layout()
    return fig


def make_loglog_figure(ll):
    """lg(k1−k0)–lg c(H+) 线性验证。"""
    fig, ax = plt.subplots(figsize=(6.4, 4.4), dpi=120)
    ax.plot(ll['x'], ll['y'], 's', color=C_DATA, markersize=5.5, label='data')
    xx = np.array(ll['x'], float)
    grid = np.linspace(float(xx.min()), float(xx.max()), 50)
    ax.plot(grid, ll['slope'] * grid + ll['intercept'],
            color=C_FIT, linewidth=1.2, label='fit')
    ax.text(0.04, 0.96, r'$n=%.2f\pm%.2f$' % (ll['slope'], ll['sigma_slope']),
            transform=ax.transAxes, fontsize=9.5, va='top')
    ax.text(0.04, 0.86, r'$R^{2}=%.4f$' % ll['r2'],
            transform=ax.transAxes, fontsize=9.5, va='top')
    ax.set_xlabel(r'$\lg[c(\mathrm{H}^{+})]$')
    ax.set_ylabel(r'$\lg(k_1-k_0)$')
    ax.legend(fontsize=9)
    _style(ax)
    fig.tight_layout()
    return fig
