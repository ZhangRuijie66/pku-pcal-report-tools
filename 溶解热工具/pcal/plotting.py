# -*- coding: utf-8 -*-
"""溶解热实验的绘图（复刻课程软件 Dissolution_Combustion 的样式）。"""
from __future__ import annotations

import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

DPI = 600          # 导出到报告时使用的分辨率
DPI_PREVIEW = 150  # 界面预览 / 自检时使用的分辨率
FIGSIZE = (10, 6)

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Source Han Sans CN',
                                   'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['path.simplify'] = True
plt.rcParams['path.simplify_threshold'] = 0.5
plt.rcParams['agg.path.chunksize'] = 10000

C_FIT1 = 'darkorange'
C_FIT2 = 'limegreen'
C_FIT3 = 'dimgray'
C_CURVE = '#1F77B4'
C_REYN = 'red'


def _area(ax, x_from, x_to, reyn_a, reyn_b):
    """把平滑曲线与某条拟合直线之间所夹的面积涂灰（等面积校正的可视化）。"""
    if x_to <= x_from:
        return
    xs = np.arange(x_from, x_to, 0.1)
    if len(xs) < 2:
        return
    lin = reyn_a['k1'] * xs + reyn_a['b1']
    curve = reyn_a['smooth'](xs)
    ax.fill_between(xs, lin, curve, color='dimgray', alpha=0.2, zorder=2)


def make_figure(data, reyn_diss, reyn_heat, fit1, fit2, fit3):
    """
    一轮数据的 ΔT–t 曲线 + 两次等面积雷诺校正：

      · 溶解降温段 —— 用平台1（拟合1，橙）与低温平台（拟合2，绿）外延；
      · 通电升温段 —— 用低温平台（拟合2，绿）与终末平台（拟合3，灰）外延。

    样式与课程软件一致：实测散点 dimgray、B 样条平滑曲线 #1F77B4、
    拟合直线虚线、雷诺校正竖线红色虚线、等面积区域灰色半透明。
    """
    t, y = data.t, data.y
    x1, x2 = reyn_diss['x0'], reyn_heat['x0']

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=120)
    ax.scatter(t, y, s=4, color='dimgray', label=r'$\Delta T$ - $t$ data', zorder=3)

    xd = reyn_diss['x_smooth']
    ax.plot(xd, reyn_diss['smooth'](xd), linewidth=1, color=C_CURVE,
            label=r'$\Delta T$ - $t$ curve', zorder=4)
    xh = reyn_heat['x_smooth']
    ax.plot(xh, reyn_heat['smooth'](xh), linewidth=1, color=C_CURVE, zorder=4)

    lo = min(xd.min(), xh.min())
    hi = max(xd.max(), xh.max())
    for fit, color, label in ((fit1, C_FIT1, 'linear fit 1'),
                              (fit2, C_FIT2, 'linear fit 2'),
                              (fit3, C_FIT3, 'linear fit 3')):
        xx = np.array([lo, hi])
        ax.plot(xx, fit['k'] * xx + fit['b'], ls='--', linewidth=1, color=color,
                label=label, zorder=5)

    for fit, color, label in ((fit1, C_FIT1, 'linear fit 1 endpoints'),
                              (fit2, C_FIT2, 'linear fit 2 endpoints'),
                              (fit3, C_FIT3, 'linear fit 3 endpoints')):
        idx = [fit['start'], fit['end']]
        ax.scatter(t[idx], y[idx], s=16, color=color, label=label, zorder=6)

    _area(ax, t[fit1['end']], x1, reyn_diss, None)
    _area(ax, x1, t[fit2['start']], reyn_diss, None)
    _area(ax, t[fit2['end']], x2, reyn_heat, None)
    _area(ax, x2, t[fit3['start']], reyn_heat, None)

    for reyn, tag in ((reyn_diss, r'$t_{1}$'), (reyn_heat, r'$t_{2}$')):
        a, b = sorted((reyn['T_left'], reyn['T_right']))
        d = (b - a) * 0.12 or 0.05
        ax.axvline(reyn['x0'], ls='--', color=C_REYN, linewidth=1, zorder=7,
                   label='Reynolds line' if tag == r'$t_{1}$' else None)

    ax.set_xlabel(r'$t$ (s)')
    ax.set_ylabel(r'$\Delta T$ (K)')
    ax.legend(fontsize=8, loc='best')
    fig.tight_layout()
    return fig


def make_fit_figure(fit, diff, marks=(200, 150, 100, 80, 50)):
    """积分溶解热 Qs 对 n0 的实验点、经验方程拟合曲线与 n0=200…50 的位置。"""
    n0, Qs = fit['n0'], fit['Qs']
    Qs0, a = fit['Qs0'], fit['a']

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=120)
    n_plot = np.linspace(0, max(np.max(n0) * 1.15, 10.0), 800)
    ax.plot(n_plot, (Qs0 * a * n_plot) / (1 + a * n_plot), color=C_CURVE,
            linewidth=1.4, label=r'$Q_s=Q_s^0 a n_0/(1+a n_0)$', zorder=4)
    ax.scatter(n0, Qs, s=45, marker='+', color='dimgray', linewidths=1.4,
               label=r'$Q_s$-$n_0$ data points', zorder=5)

    marks = np.asarray(marks, dtype=float)
    ax.scatter(marks, diff['Qs'], s=28, marker='o', facecolors='none',
               edgecolors=C_FIT1, linewidths=1.1, label=r'$n_0=200,150,100,80,50$',
               zorder=6)
    for n in marks:
        ax.annotate('%.0f' % n, (n, (Qs0 * a * n) / (1 + a * n)),
                    textcoords='offset points', xytext=(0, -14), fontsize=8,
                    color=C_FIT1, ha='center')

    ax.axhline(Qs0, ls=':', color=C_FIT3, linewidth=1)
    ax.annotate(r'$Q_s^0=%.2f$ kJ·mol$^{-1}$' % Qs0, (max(n_plot) * 0.02, Qs0),
                textcoords='offset points', xytext=(0, 4), fontsize=9, color=C_FIT3)
    ax.set_xlabel(r'$n_0$')
    ax.set_ylabel(r'$Q_s$ (kJ·mol$^{-1}$)')
    # 纵轴取数据附近的区间：实验点都落在饱和段，若从 0 起画会把它们挤成一条线
    lo = float(min(np.min(Qs), np.min(diff['Qs']))) - 0.8
    ax.set_ylim(max(0.0, lo), Qs0 * 1.03)
    ax.legend(fontsize=9, loc='lower right')
    fig.tight_layout()
    return fig


def make_params_figure(it, software_Q_kJ=None):
    """
    复刻课程软件「溶解热」模式参数面板的示意图（本报告 图2）。

    左栏是六个取点序号（Start 1/End 1 … Start 3/End 3），
    右栏是温度、水体积、水密度、水热容、溶质质量、溶质式量、加热前后电阻、
    加热起止时刻、电流与算出的溶解热 —— 与软件界面一一对应，
    便于读者核对取点与参数。
    """
    pairs = [(it['points'][0], it['points'][1]),
             (it['points'][2], it['points'][3]),
             (it['points'][4], it['points'][5])]
    rows_right = [
        ('温度(K)', '%.2f' % it['temperature']),
        ('水体积(mL)', '%.1f' % it['water_volume']),
        ('水密度(g/mL)', '%.7f' % it['water_density']),
        ('水热容(J/gK)', '%.4f' % it['water_capacity']),
        ('溶质质量(g)', '%.4f' % it['solute_mass']),
        ('溶质式量', '%.3f' % it['Mr']),
        ('加热前电阻(Ω)', '%.2f' % it['R1']),
        ('加热后电阻(Ω)', '%.2f' % it['R2']),
        ('加热开始时间(s)', '%.3f' % it['t1']),
        ('加热结束时间(s)', '%.3f' % it['t2']),
        ('电流(A)', '%.2f' % it['current']),
        ('溶解热(kJ)', '%.4f' % ((software_Q_kJ if software_Q_kJ is not None
                                  else it['Q'] / 1000))),
    ]

    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=120)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 46)
    ax.axis('off')

    def box(x, y, w, h, label, value, fs=9.5):
        ax.add_patch(plt.Rectangle((x, y), w, h, fill=False, edgecolor='#666666',
                                   linewidth=0.8))
        ax.text(x + 1.2, y + h / 2, label, fontsize=fs, va='center', ha='left')
        ax.text(x + w - 1.2, y + h / 2, value, fontsize=fs, va='center', ha='right',
                family=['Times New Roman', 'DejaVu Sans'])

    # 左栏：三对取点
    for i, (s, e) in enumerate(pairs):
        y = 34 - i * 9
        box(1, y, 9.5, 7, 'Start %d' % (i + 1), '%d' % s)
        box(11.5, y, 9.5, 7, 'End %d' % (i + 1), '%d' % e)
    ax.text(11, 9.5, '（数据点下标）', fontsize=9, color='#5b6472', ha='center')
    ax.text(11, 4.5, '取点：三段平台各取线性最强、',
            fontsize=9, color='#5b6472', ha='center')
    ax.text(11, 1.0, '范围尽可能大的一段', fontsize=9, color='#5b6472', ha='center')

    # 右栏：两列参数
    half = (len(rows_right) + 1) // 2
    for i, (lab, val) in enumerate(rows_right):
        col, k = divmod(i, half)
        x = 24 + col * 38
        y = 39 - k * 6.4
        box(x, y, 35, 5.4, lab, val)

    fig.tight_layout()
    return fig


def figure_png(fig, dpi=DPI_PREVIEW):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi)
    plt.close(fig)
    return buf.getvalue()
