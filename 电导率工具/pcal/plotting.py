# -*- coding: utf-8 -*-
"""电导率实验的绘图（样式取自 :mod:`pcal.plotstyle`，全报告统一）。

正文（图2~图6）：
    图2：校正电导率–c 三溶液折线（黑方 NaCl / 红圆 HCl / 蓝三角 HAc）
    图3~5：强电解质 Λm–√c 拟合（黑点 + 红色拟合直线）
    图6：HAc 的 (c/c°)Λm–1/Λm 拟合

附录（读入共享数据表后才有，图7~图9）：
    图7：各物种 Λm∞ 的组内散点（含 Grubbs 判出的离群点）
    图8：各成员校正电导率 相对组内均值的偏差
    图9：两种方法所得 K° 的配对连线

⚠ 两条硬约束（踩过，别重犯）：

1. **字号由 plotstyle 统一**，且画布宽度 == 插入宽度，缩放比恒为 1，
   这样 ``fontsize=9`` 就是印刷真字号。不要再单独传 ``fontsize=10/11``。
2. **标签只用纯 Unicode**，不要把中文放进 ``$...$``：mathtext 走 STIX
   字体，没有中文字形，整串会渲染成方框。

物种口径 2026-11-20 由 NaNO₃/HNO₃ 改为 NaCl/HCl（与 2026 秋讲义、
周三组共享数据表一致）；图例文字直接用 ``NaCl``/``HCl``。
"""
from __future__ import annotations

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from . import plotstyle as ps

ps.apply_style()

DPI = ps.DPI
DPI_PREVIEW = ps.DPI_PREVIEW

# 物种配色：全报告一致（正文与附录共用）
C_NACL = '#3b3b3b'
C_HCL = '#d62728'
C_HAC = '#1f77b4'
C_NAAC = '#e8801a'
C_FIT = 'red'
C_DATA = 'black'

#: 附录图里区分「本人 / 他人 / 组内统计量 / 离群 / 理论值」
C_ME = '#d62728'
C_OTHER = '#8c8c8c'
C_MEAN = '#111111'
C_BAND = '#4c72b0'
C_GRUB = '#e8801a'
C_THEO = '#2ca02c'

YLAB_LAM = 'Λₘ∞ / (S·m²·mol⁻¹)'
YLAB_LAM_REL = 'Λₘ∞ 相对 CRC 理论值偏差 / %'


def _style_axes(ax):
    return ps.style_axes(ax)


def _pad_lim(lo, hi, pad_frac=0.06):
    return ps.pad_lim(lo, hi, pad_frac)


def msz(factor):
    """按 MS_DATA 的倍数给标记尺寸（保持全报告同一基数）。"""
    return ps.MS_DATA * factor


def _layout(fig):
    """在实际图幅内收紧边距，保证轴标签不越出画布。

    ⚠ 为什么必须有这一步（2026-11-26 用户同学的图纵轴标签被裁掉）：
    matplotlib 默认左边距是 ``0.125 * figsize`` = 0.57 in ≈ 41 pt，
    而本模块的纵轴标签 ``Λₘ / S·m²·mol⁻¹`` 在 9 pt 下要占 ~44 pt，
    于是标签左半截直接落在画布外，**保存出来就少了一截**。
    实测该图 ylabel 的 ``x0 = -11.8 px``（100 dpi）。

    ⚠ 但**不能**用 ``savefig(bbox_inches='tight')`` 解决：
    那会改变输出图片的实际尺寸，画布宽就不再等于 Word 里的插入宽，
    ``fontsize=9`` 也就不再是印刷真字号（v1.4.1 定的那套规范会整体失效）。
    正确做法是在**固定画布**内部重排边距，尺寸不变、标签收进来。
    """
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------- 图2
def make_kappa_c_figure(an):
    """校正电导率–c 关系曲线（NaCl / HCl / HAc）。"""
    fig, ax = plt.subplots(figsize=(ps.FIG_W, ps.FIG_H))
    series = [
        ('NaCl', C_NACL, 's', 'NaCl'),
        ('HCl', C_HCL, 'o', 'HCl'),
        ('HAc', C_HAC, '^', 'HAc'),
    ]
    xs, ys = [], []
    for key, color, marker, label in series:
        rows = an.tables.get(key)
        if not rows:
            continue
        x = [r['c'] for r in rows]
        y = [r['kappa_corr'] for r in rows]
        ax.plot(x, y, color=color, marker=marker, markersize=ps.MS_DATA,
                linewidth=ps.LW_DATA, label=label)
        xs += x
        ys += y
    ax.set_xlabel(r'$c$ / mol·m$^{-3}$')
    ax.set_ylabel(r'$\kappa_{corrected}$ / S·m$^{-1}$')
    if xs:
        ax.set_xlim(*_pad_lim(-0.5, max(xs)))
        ax.set_ylim(*_pad_lim(min(0.0, min(ys)), max(ys)))
    ax.legend(frameon=False, loc='upper left')
    _style_axes(ax)
    return _layout(fig)


# ---------------------------------------------------------------- 图3~5
def make_kohlrausch_figure(an, key):
    """强电解质 Λm–√c 拟合直线。"""
    fit = an.fits.get(key)
    if not fit:
        fig, ax = plt.subplots(figsize=(ps.FIG_W, ps.FIG_H))
        ax.text(0.5, 0.5, '无数据', ha='center', va='center',
                transform=ax.transAxes)
        return _layout(fig)
    x = np.array(fit['x'], float)
    y = np.array(fit['y'], float)
    fig, ax = plt.subplots(figsize=(ps.FIG_W, ps.FIG_H))
    ax.plot(x, y, 'o', color=C_DATA, markersize=ps.MS_DATA, zorder=4)
    xlo, xhi = 0.0, float(x.max()) * 1.08
    xx = np.linspace(xlo, xhi, 50)
    y_line_lo = float(fit['k'] * xhi + fit['b'])
    y_line_hi = float(fit['b'])
    ax.plot(xx, fit['k'] * xx + fit['b'], color=C_FIT,
            linewidth=ps.LW_FIT, zorder=3)
    ax.set_xlabel(r'$c^{1/2}$ / mol$^{1/2}$·m$^{-3/2}$')
    ax.set_ylabel(r'$\Lambda_{m}$ / S·m$^{2}$·mol$^{-1}$')
    ax.set_xlim(xlo, xhi)
    lo = min(y.min(), y_line_lo, y_line_hi)
    hi = max(y.max(), y_line_lo, y_line_hi)
    ax.set_ylim(*_pad_lim(lo, hi, 0.12))
    _style_axes(ax)
    return _layout(fig)


# ---------------------------------------------------------------- 图6
def make_kfit_figure(an):
    """HAc 的 (c/c°)Λm–1/Λm 拟合直线。"""
    fit = an.kfit
    if not fit:
        fig, ax = plt.subplots(figsize=(ps.FIG_W, ps.FIG_H))
        ax.text(0.5, 0.5, '无数据', ha='center', va='center',
                transform=ax.transAxes)
        return _layout(fig)
    x = np.array(fit['x'], float)
    y = np.array(fit['y'], float)
    fig, ax = plt.subplots(figsize=(ps.FIG_W, ps.FIG_H))
    ax.plot(x, y, 'o', color=C_DATA, markersize=ps.MS_DATA, zorder=4)
    xlo, xhi = float(x.min()) * 0.9, float(x.max()) * 1.1
    xx = np.linspace(xlo, xhi, 50)
    ax.plot(xx, fit['k'] * xx + fit['b'], color=C_FIT,
            linewidth=ps.LW_FIT, zorder=3)
    ax.set_xlabel(r'$1/\Lambda_{m}$ / mol·m$^{-2}$·S$^{-1}$')
    ax.set_ylabel(r'$(c/c^{\ominus})\Lambda_{m}$ / S·m$^{2}$·mol$^{-1}$')
    ax.set_xlim(xlo, xhi)
    ys = [y.min(), y.max(), float(fit['k'] * xlo + fit['b']),
          float(fit['k'] * xhi + fit['b'])]
    ax.set_ylim(*_pad_lim(min(ys), max(ys), 0.15))
    _style_axes(ax)
    return _layout(fig)


# ================================================================ 附录图
def _nan(vals):
    return np.array([v if v is not None else np.nan for v in vals], float)


def _species_values(group, species):
    """某物种各成员的 Λm∞（按成员顺序）；HAc 用组合值。"""
    if species == 'HAc':
        return list(group['lam_hac']['values'])
    return list(group['species'][species]['values'])


def make_group_scatter_figure(shared, species=('NaCl', 'NaAc', 'HCl')):
    """图7：各物种 Λm∞ 的组内散点（一人一点）。

    横轴只用来把点错开（抖动），不承载信息，所以不画刻度。
    蓝带 = ±1s，黑实线 = 组内均值，绿虚线 = CRC 理论值。
    """
    from . import conduct
    group = shared['group']
    members = shared['members']
    names = [m['name'] for m in members]
    me = (shared.get('match') or {}).get('index')

    fig, axes = ps.subplots(ncols=len(species), height=ps.FIG_H_PANEL3)
    if len(species) == 1:
        axes = [axes]
    for ax, sp in zip(axes, species):
        v = _nan(_species_values(group, sp))
        ok = np.isfinite(v)
        mean = float(np.nanmean(v))
        sd = float(np.nanstd(v, ddof=1))
        rng = np.random.default_rng(0)
        idxs = np.where(ok)[0]
        xs = rng.normal(0, 0.045, len(idxs))
        ax.axhspan(mean - sd, mean + sd, color=C_BAND, alpha=0.13, lw=0)
        ax.axhline(mean, color=C_MEAN, lw=1.1, zorder=3)
        ax.axhline(conduct.LAMBDA_THEO[sp], color=C_THEO, lw=1.0, ls='--',
                   zorder=3)
        gb = group['species'][sp]['grubbs']
        for x, k in zip(xs, idxs):
            if me is not None and k == me:
                ax.plot(x, v[k], 'o', ms=msz(1.5), mfc=C_ME, mec=C_ME,
                        zorder=7)
            elif gb['is_outlier'] and gb['outlier_index'] == k:
                ax.plot(x, v[k], 'X', ms=msz(1.9), mfc='none', mec=C_GRUB,
                        mew=1.7, zorder=7)
            else:
                ax.plot(x, v[k], 'o', ms=ps.MS_DATA, mfc='none', mec=C_OTHER,
                        mew=1.3, zorder=5)
        if gb['is_outlier'] and gb['outlier_index'] is not None:
            oi = gb['outlier_index']
            # 三个 panel 并排时每个只有约 3.6 cm 宽，标注很容易被右边界吃掉。
            # 统一放在该点**上方、水平居中**（离群点通常在最低处，
            # 上方必有空白），文字两行、字号最小档。
            ax.annotate('%s\nG=%.2f' % (names[oi], gb['g']),
                        xy=(xs[idxs.tolist().index(oi)], v[oi]),
                        xytext=(0, 9), textcoords='offset points',
                        ha='center', va='bottom', fontsize=ps.FS_ANNOT - 0.5,
                        color=C_GRUB, linespacing=1.15,
                        arrowprops=dict(arrowstyle='-', lw=0.6, color=C_GRUB))
        ax.set_xticks([])
        ax.set_xlim(-0.42, 0.58)
        # 物种名 + RSD 用 set_title 之外的写法：panel 很窄，标题要小
        ax.set_title('%s\nRSD %.2f%%' % (conduct.SPECIES_LABEL[sp],
                                         sd / abs(mean) * 100),
                     fontsize=ps.FS_TICK, pad=4)
        _style_axes(ax)
    axes[0].set_ylabel(YLAB_LAM)
    fig.tight_layout()
    return fig


def make_group_kappa_figure(shared, species=('NaCl', 'NaAc', 'HCl')):
    """图8：各成员校正电导率 相对组内均值的偏差。

    ⚠ 为什么画**相对偏差**而不是原始 κ：κ 与 c 近似线性，7 个人的绝对
    曲线几乎完全重合（差别只有 1~3%），叠在一起什么也看不出——第一版
    就是这样，6 条灰线被红线完全盖住。换成相对偏差才摊得开。
    """
    from . import conduct
    group = shared['group']
    members = shared['members']
    me = (shared.get('match') or {}).get('index')

    fig, axes = ps.subplots(ncols=len(species), height=ps.FIG_H_PANEL3)
    if len(species) == 1:
        axes = [axes]
    for ax, sp in zip(axes, species):
        tabs = [m['analysis'].tables.get(sp) for m in members]
        if any(t is None for t in tabs):
            continue
        n = min(len(t) for t in tabs)
        c = np.array([tabs[0][i]['c'] for i in range(n)], float)
        order = np.argsort(c)
        mat = np.array([[tabs[k][i]['kappa_corr'] for i in range(n)]
                        for k in range(len(tabs))], float)
        base = np.nanmean(mat, axis=0)
        rel = (mat - base) / np.abs(base) * 100
        for k in range(len(tabs)):
            if me is not None and k == me:
                continue
            ax.plot(c[order], rel[k][order], color=C_OTHER, lw=0.8,
                    alpha=0.6, zorder=3)
        if me is not None:
            ax.plot(c[order], rel[me][order], color=C_ME, lw=1.8,
                    marker='o', ms=msz(0.7), zorder=6)
        ax.axhline(0, color=C_MEAN, lw=1.0, zorder=4)
        ax.set_xscale('log')
        ax.set_title(conduct.SPECIES_LABEL[sp], fontsize=ps.FS_TICK, pad=4)
        ax.set_xlabel('c / mol·m⁻³')
        _style_axes(ax)
    # 三个 panel 并排 + 长纵轴标签时，tight_layout 会把标签挤到画布外
    # （实测 ylabel 末尾的「%」被裁掉）。显式留出左边距。
    axes[0].set_ylabel('校正电导率 相对组内均值的偏差 / %')
    fig.tight_layout(rect=(0.055, 0, 1, 1))
    return fig


def make_kpair_figure(shared):
    """图9：两种方法所得 K° 的配对连线（一人一条）。

    配对的要点在图上就是「同一个人连一条线」：线的方向一致说明两法有
    系统性差异，方向杂乱说明只是随机散布。
    """
    from . import conduct
    group = shared['group']
    km = group.get('k_methods') or {}
    me = (shared.get('match') or {}).get('index')
    a = _nan(km.get('mean_values') or []) / 1e-5
    b = _nan(km.get('fit_values') or []) / 1e-5

    fig, ax = plt.subplots(figsize=(ps.FIG_W, ps.FIG_H_PANEL3))
    for k in range(len(a)):
        if not (np.isfinite(a[k]) and np.isfinite(b[k])):
            continue
        isme = (me is not None and k == me)
        ax.plot([0, 1], [a[k], b[k]],
                color=C_ME if isme else C_OTHER,
                lw=1.9 if isme else 0.8,
                alpha=1.0 if isme else 0.55,
                zorder=6 if isme else 3)
        for xx, yy in ((0, a[k]), (1, b[k])):
            ax.plot(xx, yy, 'o', ms=msz(1.3 if isme else 1.0),
                    mfc=C_ME if isme else 'none',
                    mec=C_ME if isme else C_OTHER, mew=1.3,
                    zorder=7 if isme else 4)
    ax.axhline(conduct.KA_HAC / 1e-5, color=C_THEO, lw=1.1, ls='--', zorder=2)
    # 文献值标注：放右侧端点外 + 略抬高 + 白底，避免与虚线/配对线叠字
    ax.text(1.06, conduct.KA_HAC / 1e-5, '文献 %.3f' % (conduct.KA_HAC / 1e-5),
            va='center', ha='left', fontsize=ps.FS_ANNOT, color=C_THEO,
            bbox=dict(fc='white', ec='none', pad=1.2), zorder=8)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(['求平均法', '拟合直线法'])
    ax.set_xlim(-0.25, 1.42)
    ax.set_ylabel('K⊖ / 10⁻⁵')
    _style_axes(ax)
    fig.tight_layout(rect=(0.05, 0, 1, 1))
    return fig
