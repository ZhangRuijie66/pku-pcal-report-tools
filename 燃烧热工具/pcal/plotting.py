# -*- coding: utf-8 -*-
"""雷诺校正图的绘制（复刻课程软件 Dissolution_Combustion 的绘图样式）。"""
from __future__ import annotations

import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

DPI = 600          # 导出到报告时使用的分辨率
DPI_PREVIEW = 150  # 界面预览 / 自检时使用的分辨率
FIGSIZE = (10, 6)

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Source Han Sans CN', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['path.simplify'] = True
plt.rcParams['path.simplify_threshold'] = 0.5
plt.rcParams['agg.path.chunksize'] = 10000


def make_figure(data, fit1, fit2, reyn, show_legend=True):
    """
    返回 matplotlib Figure。样式与课程软件一致：
    实测散点(dimgray, s=5)、平滑曲线(#1F77B4)、两条拟合虚线(darkorange / limegreen)、
    拟合区间端点(橙色 / 绿色圆点)、雷诺辅助竖线(红色虚线)、等面积区域(灰色填充)。
    """
    t = data.t
    y = data.y
    x_smooth = reyn['x_smooth']
    smooth_y = reyn['smooth'](x_smooth)
    x0 = reyn['x0']

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=120)
    ax.scatter(t, y, s=5, color='dimgray', label=r'$\Delta T$ - $t$ data', zorder=3)
    ax.plot(x_smooth, smooth_y, linewidth=1, color='#1F77B4', label=r'$\Delta T$ - $t$ curve', zorder=4)
    ax.plot(x_smooth, reyn['k1'] * x_smooth + reyn['b1'], ls='--', linewidth=1,
            color='darkorange', label='linear fit 1', zorder=5)
    ax.plot(x_smooth, reyn['k2'] * x_smooth + reyn['b2'], ls='--', linewidth=1,
            color='limegreen', label='linear fit 2', zorder=5)

    # 拟合区间端点
    for key, color, label in ((fit1, 'darkorange', 'linear fit 1 endpoints'),
                              (fit2, 'limegreen', 'linear fit 2 endpoints')):
        idx = [key['start'], key['end']]
        ax.scatter(t[idx], y[idx], s=15, color=color, label=label, zorder=6)

    # 等面积填充
    xs_l = np.arange(t[fit1['end']], x0, 0.1)
    xs_r = np.arange(x0, t[fit2['start']], 0.1)
    if len(xs_l) > 1:
        ax.fill_between(xs_l, reyn['k1'] * xs_l + reyn['b1'], reyn['smooth'](xs_l),
                        color='dimgray', alpha=0.2, zorder=2)
    if len(xs_r) > 1:
        ax.fill_between(xs_r, reyn['k2'] * xs_r + reyn['b2'], reyn['smooth'](xs_r),
                        color='dimgray', alpha=0.2, zorder=2)

    # 雷诺辅助竖线
    t_small, t_big = sorted((reyn['T_left'], reyn['T_right']))
    dt = t_big - t_small
    yy = np.arange(t_small - dt * 0.1, t_big + dt * 0.1, 0.1)
    ax.plot(np.full(len(yy), x0), yy, ls='--', color='red', linewidth=1, zorder=7)

    ax.set_xlabel(r'$t$ (s)')
    ax.set_ylabel(r'$\Delta T$ (K)')
    if show_legend:
        ax.legend()
    fig.tight_layout()
    return fig


def figure_png(fig, dpi=DPI_PREVIEW):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi)
    plt.close(fig)
    return buf.getvalue()
