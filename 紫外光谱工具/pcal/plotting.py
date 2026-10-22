# -*- coding: utf-8 -*-
"""紫外可见吸收光谱实验的绘图（复刻参考报告里 Origin 图的样式）。"""
from __future__ import annotations

import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

DPI = 600
DPI_PREVIEW = 150
FIGSIZE = (9.0, 3.8)          # 单张图（报告里多为两联图）
FIGSIZE_TALL = (8.0, 5.2)

plt.rcParams['font.family'] = ['Times New Roman', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['mathtext.fontset'] = 'stix'
plt.rcParams['path.simplify'] = True
plt.rcParams['path.simplify_threshold'] = 0.5
plt.rcParams['agg.path.chunksize'] = 10000

C_CURVE = 'black'
C_FIT = 'red'
C_DATA = 'black'
PALETTE = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
           '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']


def _style_axes(ax):
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    ax.tick_params(direction='in', length=3.5, width=0.9, labelsize=10,
                   top=True, right=True)
    ax.xaxis.label.set_size(11)
    ax.yaxis.label.set_size(11)


# ---------------------------------------------------------------- 标定
def _fmt_pm(x, u, nd):
    return ('%.*f ± %.*f' % (nd, x, nd, u)) if np.isfinite(u) else ('%.*f' % (nd, x))


def make_calibration_figure(cal):
    """左：光源谱图 + 三条特征线；右：λ–pixel 线性拟合。"""
    spec = cal['spec']
    idx = spec['index'].astype(float)
    y = spec['difference'].astype(float)
    pts = cal['points']

    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.4), dpi=120,
                             gridspec_kw=dict(width_ratios=[1.45, 1]))
    ax = axes[0]
    ax.plot(idx, y, color=C_CURVE, linewidth=0.6)
    ys = np.interp([p[0] for p in pts], idx, y)
    ax.plot([p[0] for p in pts], ys, 'v', color=C_FIT, markersize=4.5, zorder=4)
    span = max(np.max(y) - np.min(y), 1)
    for (px, lam), yy in zip(pts, ys):
        ax.annotate('%.0f' % px, (px, yy), textcoords='offset points',
                    xytext=(0, 7), ha='center', fontsize=9, color=C_FIT)
    ax.set_xlabel('pixel')
    ax.set_ylabel('Intensity')
    ax.set_xlim(0, float(np.max(idx)))
    ax.set_ylim(min(0, np.min(y) - 0.05 * span), np.max(y) + 0.12 * span)
    _style_axes(ax)

    ax = axes[1]
    xs = np.array([p[0] for p in pts], float)
    ls = np.array([p[1] for p in pts], float)
    xlo, xhi = xs.min() * 0.94, xs.max() * 1.04
    xx = np.linspace(xlo, xhi, 50)
    ax.plot(xx, cal['a'] * xx + cal['b'], color=C_FIT, linewidth=1.1, zorder=3)
    ax.plot(xs, ls, 's', color=C_DATA, markersize=4.5, zorder=4)
    ax.set_xlabel('pixel')
    ax.set_ylabel(r'$\lambda$ / nm')
    ax.set_xlim(xlo, xhi)
    pad = (ls.max() - ls.min()) * 0.15 or 10
    ax.set_ylim(ls.min() - pad, ls.max() + pad)
    # 拟合式直接写成普通文本（mathtext 里 ± 的位置容易错乱）
    ax.text(0.03, 0.95,
            'λ = (%.5f ± %.5f)·pixel + (%.1f ± %.1f)'
            % (cal['a'], cal['sigma_a'], cal['b'], cal['sigma_b']),
            transform=ax.transAxes, fontsize=9.5, va='top')
    ax.text(0.03, 0.86, r'$R^{2}=%.5f$' % cal['r2'],
            transform=ax.transAxes, fontsize=9.5, va='top')
    _style_axes(ax)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------- 吸收光谱
def make_spectra_figure(items, labels=None, xlim=None, title=None,
                        corrected=True, marker_peaks=True):
    """多条 A–λ 曲线（items 为 Analysis.samples 里的条目）。"""
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=120)
    for i, it in enumerate(items):
        A = it['A_corr'] if corrected else it['A_smooth']
        lab = labels[i] if labels else _auto_label(it)
        color = PALETTE[i % len(PALETTE)]
        ax.plot(it['lam'], A, linewidth=0.8, color=color, label=lab)
        vf = it.get('voigt') if corrected else it.get('voigt_obs')
        if vf:
            # 同色虚线 = Voigt 分峰拟合的总曲线（图题里说明，不进图例）
            ax.plot(vf['grid'], vf['total'], linestyle=(0, (5, 2)),
                    linewidth=0.8, color=color, alpha=0.95)
        if marker_peaks and np.isfinite(it['peak']['lam']):
            ax.plot([it['peak']['lam']], [it['peak']['A']], 'v', markersize=4,
                    color=color)
    ax.set_xlabel(r'$\lambda$ / nm')
    ax.set_ylabel(r'$A$')
    if xlim:
        ax.set_xlim(*xlim)
    else:
        lo = min(np.nanmin(it['lam']) for it in items)
        hi = max(np.nanmax(it['lam']) for it in items)
        ax.set_xlim(max(240, lo), hi)
    ax.legend(fontsize=9)
    if title:
        ax.set_title(title, fontsize=10)
    _style_axes(ax)
    fig.tight_layout()
    return fig


def _auto_label(it):
    if it.get('kind', '').startswith('conc'):
        return r'$c$ = %g $\mu$mol·L$^{-1}$' % it['conc']
    return it.get('short') or it.get('mol_key') or it['key']


def make_concentration_figure(items):
    """A3 不同浓度的 A–λ 谱（只平滑、不做基线校正，用于定性比较）。"""
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=120)
    items = sorted(items, key=lambda p: p['conc'])
    for i, it in enumerate(items):
        ax.plot(it['lam'], it['A_smooth_plain'], linewidth=0.8,
                color=PALETTE[i % len(PALETTE)],
                label=r'$c$ = %g $\mu$mol·L$^{-1}$' % it['conc'])
    lo = min(s['band'][0] for s in items) - 60
    hi = max(s['band'][1] for s in items) + 30
    ax.set_xlim(lo, hi)
    ax.set_xlabel(r'$\lambda$ / nm')
    ax.set_ylabel(r'$A$')
    ax.legend(fontsize=9, ncol=2)
    _style_axes(ax)
    fig.tight_layout()
    return fig


def make_source_figure(item_w, item_dw):
    """同一浓度 A3 在「卤钨灯」与「卤钨灯 + 氘灯」下的吸收光谱对比。"""
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=120)
    for it, color, lab in ((item_w, 'black', '钨灯'),
                           (item_dw, '#d62728', '钨灯 + 氘灯')):
        ax.plot(it['lam'], it['A_smooth_plain'], linewidth=0.8, color=color, label=lab)
    lo = item_w['band'][0] - 80
    hi = item_w['band'][1] + 30
    ax.set_xlim(lo, hi)
    ax.set_xlabel(r'$\lambda$ / nm')
    ax.set_ylabel(r'$A$')
    ax.legend(fontsize=10)
    _style_axes(ax)
    fig.tight_layout()
    return fig


def make_beer_figure(beer, path_cm=1.0):
    """朗伯–比尔定律：**全部**浓度点都画出来，但直线只拟合线性区。

    实线 = 线性区拟合；虚线 = 它的延长线（一直画到超出坐标上限），
    这样高浓度点偏离线性区有多远一眼可见；图例放在右下角空白处，不压线。
    """
    fit = beer.get('fit')
    allp = beer.get('all') or beer.get('points') or []
    fig, ax = plt.subplots(figsize=(7.2, 4.4), dpi=120)

    lin = [p for p in allp if p.get('is_fit')]
    sat = [p for p in allp if not p.get('is_fit')]
    xs_all = [p['conc'] for p in allp] or [0, 1]
    ys_lin = [p.get('A_corr') if p.get('A_corr') is not None else p.get('A')
              for p in lin] or [0]
    ys_sat = [p.get('A_obs') if p.get('A_obs') is not None else p.get('A')
              for p in sat] or [0]
    x1 = max([p['conc'] for p in lin] or [0.0])
    x_max = max(xs_all) * 1.06
    y_top = max(ys_lin + ys_sat + [0.1]) * 1.16

    # 线性区浅色底，和图例呼应
    if lin:
        ax.axvspan(0, x1, color='#eef4ff', zorder=0)

    if lin:
        ax.plot([p['conc'] for p in lin], ys_lin, 's', color=C_DATA,
                markersize=5.5, zorder=5, label='线性区数据点（参与拟合）')
    if sat:
        ax.plot([p['conc'] for p in sat], ys_sat, 'o',
                markerfacecolor='none', markeredgecolor=C_FIT,
                markeredgewidth=1.2, markersize=7, zorder=5,
                label='饱和区数据点（实测，未参与拟合）')

    if fit and np.isfinite(fit['k']):
        kk, bb = fit['k'], fit['b']
        xx = np.linspace(0, x1, 60)
        ax.plot(xx, kk * xx + bb, color=C_FIT, linewidth=1.4, zorder=3,
                label='线性区拟合（0–%g μmol·L⁻¹）' % x1)
        xx2 = np.linspace(x1, x_max, 120)
        ax.plot(xx2, kk * xx2 + bb, color=C_FIT, linewidth=1.0, linestyle='--',
                alpha=0.85, zorder=3, label='拟合直线的延长线')
        ax.text(0.38, 0.97,
                'A = (%.4f ± %.4f)·c + (%.3f ± %.3f)\nR² = %.4f'
                % (kk, fit['sigma_k'] if np.isfinite(fit['sigma_k']) else 0,
                   bb, fit['sigma_b'] if np.isfinite(fit['sigma_b']) else 0,
                   fit['r2']),
                transform=ax.transAxes, fontsize=11, va='top')

    ax.set_xlabel(r'$c$ / ($\mu$mol·L$^{-1}$)')
    ax.set_ylabel(r'$A$')
    ax.set_xlim(0, x_max)
    ax.set_ylim(0, y_top)
    ax.legend(fontsize=10, loc='lower right', framealpha=0.95)
    _style_axes(ax)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


def make_voigt_figure(item):
    """一条吸收谱的 Voigt 分峰结果：实测、总拟合、各分峰组元。"""
    vf = item.get('voigt')
    if not vf:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 4.4), dpi=120)
    ax.plot(item['lam'], item['A_corr'], color='0.55', linewidth=0.7,
            label='实测 A(λ)')
    ax.plot(vf['grid'], vf['total'], color='black', linewidth=1.2,
            label='Voigt 总拟合')
    for i, comp in enumerate(vf['components']):
        ax.plot(vf['grid'], comp, linestyle='--', linewidth=0.9,
                color=PALETTE[i % len(PALETTE)],
                label='分峰 %d（%.1f nm）' % (i + 1, vf['peaks'][i]['center']))
    ax.plot(vf['grid'], vf['baseline'], linestyle=':', linewidth=0.9,
            color='0.4', label='基线')
    ax.plot([vf['lam_max']], [vf['A_max']], 'v', color='black', markersize=5,
            zorder=6)
    txt = ('$\\lambda_{max}$ = %.1f nm, $A$ = %.4f\n$R^2$ = %.4f'
           % (vf['lam_max'], vf['A_max'], vf['r2']))
    ax.text(0.03, 0.96, txt, transform=ax.transAxes, fontsize=9, va='top')
    ax.set_xlabel(r'$\lambda$ / nm')
    ax.set_ylabel(r'$A$')
    ax.set_xlim(item['band'][0] - 25, item['band'][1] + 25)
    lo = np.nanmin(item['A_corr'][np.isfinite(item['A_corr'])]) if np.any(
        np.isfinite(item['A_corr'])) else -0.05
    ax.set_ylim(min(-0.05, lo - 0.03), vf['A_max'] * 1.22 + 0.02)
    ax.legend(fontsize=8, loc='upper right')
    _style_axes(ax)
    fig.tight_layout()
    return fig


def make_box_figure(box):
    """一维势箱：A 组 λmax 实验值与预测值随 i 的变化。"""
    rows = [r for r in box['a_rows'] if np.isfinite(r['lam2'])]
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(6.2, 4.0), dpi=120)
    lam = box['lambdas']
    ii = [1, 2, 3, 4]
    exp = [lam.get('A%d' % i) for i in ii]
    ax.plot(ii, exp, 's-', color=C_DATA, markersize=5, linewidth=1.0,
            label='experimental')
    i2 = [2, 3]
    pred = [rows[0]['lam2'], rows[0]['lam3']]
    ax.plot(i2, pred, 'o--', color=C_FIT, markersize=5, linewidth=1.0,
            label='predicted (a = %d)' % box.get('a_used', 6))
    ax.set_xlabel(r'$i$（C–C=C 基团数）')
    ax.set_ylabel(r'$\lambda_{max}$ / nm')
    ax.set_xticks(ii)
    ax.legend(fontsize=8)
    _style_axes(ax)
    fig.tight_layout()
    return fig


def figure_png(fig, dpi=DPI_PREVIEW):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi)
    plt.close(fig)
    return buf.getvalue()
