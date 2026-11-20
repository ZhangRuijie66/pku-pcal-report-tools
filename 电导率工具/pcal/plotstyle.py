# -*- coding: utf-8 -*-
"""绘图样式规范 —— 全报告统一（用户 2026-11-20 要求「全文需要统一，包括字体、字号等」）。

## 为什么要有这个文件

matplotlib 的 ``fontsize=10`` 只是**画布上**的 10 pt。图片插进 Word 时会按
``width_cm`` 缩放，缩放比 = 插入宽度 ÷ 画布宽度。画布与插入宽度不一致时，
同一套 ``fontsize`` 在不同图里印出来会不一样——实测旧版：

    图2   画布 15.75 cm，插入 12.5 cm → 缩放 0.794 → 设 10 pt 实印 7.94 pt
    图3~6 画布 14.22 cm，插入 11.5 cm → 缩放 0.809 → 设 10 pt 实印 8.08 pt

同一份报告里图的字号差 1.8%，肉眼能看出「图2 的字比图3 小」。

## 规范（改绘图前先读这里）

1. **画布宽度 = 插入宽度**。``FIG_W` 定死为 11.5 cm（= 4.5276 in），
   报告里所有 ``rb.figure(..., width_cm=FIG_W_CM)`` 用同一个值，
   于是缩放比恒为 1.000，``fontsize`` 就是**印刷真字号**。
2. **字号一律 9 pt**（``FS_TICK``/``FS_LABEL``/``FS_LEGEND``/``FS_ANNOT``）。
   正文五号是 10.5 pt，图内文字小一号（9 pt）是期刊惯例，
   既比正文轻、又不至于小到看不清。图题由 docxkit 排五号，不归本文件管。
3. **字体** Times New Roman（西文/数字）+ 微软雅黑（中文兜底）；
   数学符号走 STIX（``mathtext.fontset='stix'``），与 Times 同族。
4. **线宽/标记** 轴框 1.0、刻度 0.9、拟合线 1.2、数据点 5.0。
5. **标签只用纯 Unicode，不要 `$...$` 混排中文**。mathtext 走 STIX，
   没有中文字形，会把「相对理论值偏差」整串渲染成方框（实测踩过）。
   要斜体就用 Unicode 斜体字符或单独 run，别把中文塞进 ``$ $``。
6. 图内**不放标题**（``title``）。图的内容由图题说明，这是学位论文/期刊的
   通行做法；正文已有「如图N所示」，图里再写一遍是重复。
"""
from __future__ import annotations

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ---------------------------------------------------------------- 尺寸
#: 画布宽度（英寸）。11.5 cm ÷ 2.54 = 4.5276 in。
#: 必须与 report.py 里 rb.figure(width_cm=...) 的取值一致，缩放比才是 1。
FIG_W_CM = 11.5
FIG_W = FIG_W_CM / 2.54

#: 画布高度（英寸）：4:3 略扁，与 A4 正文区协调
FIG_H = 3.55

#: 多 panel 横排时用的画布高度。三个 panel 并排、总宽仍是 11.5 cm 时，
#: 每个 panel 只有约 3.6 cm 宽，高度不能超过 3.2 in，否则图会瘦高难看。
FIG_H_PANEL3 = 2.95

#: 双栏图（并排 2~3 个 panel）用的画布宽度：仍是 11.5 cm 总宽
FIG_W_WIDE_CM = 11.5

# ---------------------------------------------------------------- 字号
#: 刻度数字
FS_TICK = 9
#: 轴标签
FS_LABEL = 9
#: 图例
FS_LEGEND = 9
#: 图内标注（离群点姓名、RSD 等）
FS_ANNOT = 8

# ---------------------------------------------------------------- 线宽
LW_AXES = 1.0
LW_TICK = 0.9
LW_FIT = 1.2
LW_DATA = 1.0
MS_DATA = 5.0

# ---------------------------------------------------------------- 导出
#: 报告里插入的图：600 dpi（印刷够用）
DPI = 600
#: 界面预览：130 dpi（快）
DPI_PREVIEW = 130


def apply_style():
    """设置全局 rcParams。每个绘图模块导入后调用一次（幂等）。"""
    plt.rcParams.update({
        'font.family': ['Times New Roman', 'Microsoft YaHei', 'DejaVu Sans'],
        'axes.unicode_minus': False,
        'mathtext.fontset': 'stix',
        'font.size': FS_TICK,
        'axes.labelsize': FS_LABEL,
        'axes.titlesize': FS_LABEL,
        'xtick.labelsize': FS_TICK,
        'ytick.labelsize': FS_TICK,
        'legend.fontsize': FS_LEGEND,
        'figure.titlesize': FS_LABEL,
        'path.simplify': True,
        'agg.path.chunksize': 10000,
        # 图内不放标题：统一由 Word 图题承担（见模块 docstring 第 6 条）
        'axes.titleweight': 'normal',
    })


def style_axes(ax, grid=False):
    """统一的坐标轴样式：四边框、刻度朝内、只在上下左右都出刻度。"""
    for spine in ax.spines.values():
        spine.set_linewidth(LW_AXES)
    ax.tick_params(direction='in', length=3.2, width=LW_TICK,
                   labelsize=FS_TICK, top=True, right=True)
    ax.xaxis.label.set_size(FS_LABEL)
    ax.yaxis.label.set_size(FS_LABEL)
    if grid:
        ax.grid(True, ls=':', lw=0.6, color='0.75', zorder=0)
    return ax


def pad_lim(lo, hi, pad_frac=0.06):
    pad = (hi - lo) * pad_frac
    return lo - pad, hi + pad


def subplots(ncols=1, nrows=1, height=None, **kw):
    """按统一宽度建画布。ncols>1 时总宽仍是 FIG_W，高度按比例放大一点。"""
    h = height if height is not None else FIG_H
    return plt.subplots(nrows, ncols, figsize=(FIG_W, h), **kw)
