# -*- coding: utf-8 -*-
"""循环伏安法解析电极极化 —— CHI 电化学工作站数据读取与计算内核。

数据来源：CHI600B 工作站 File → Convert to Text 导出的 .txt
（同目录的 .csv / _red.csv 是降采样副本，一律不用，以 .txt 为准）。

txt 结构：
    头部参数（Init E / High E / Low E / Scan Rate / Segment / Sensitivity）
    峰分析表（每个奇数 Segment 列出 Ep / ip / Ah，ip 是相对基线的峰高）
    数据区「Potential/V, Current/A, Charge/C」+ Segment 1..6
电流符号是 CHI 的美国约定：阴极（还原）电流为正、阳极（氧化）电流为负。

段结构（Init P/N = N，6 段 = 起始半扫 + 2.5 圈）：
    S1: Init E → Low E（起始半扫）   S2: Low E → High E
    S3: High E → Low E               S4: Low E → High E
    S5: High E → Low E（负扫，还原支） S6: Low E → High E（正扫，氧化支）
参考报告取 S5+S6（第三圈），本内核默认同此。
"""
from __future__ import annotations

import os
import re

import numpy as np

# ---------------------------------------------------------------- 常量
Q_H_MLAYER = 2.1e-4        # Pt 表面满单层氢脱附电量 C·cm⁻²（讲义：0.21 mC·cm⁻²）

# 默认数据文件（相对数据目录；2025 参照数据的命名）
DEFAULT_FILES = {
    'n2_blank': 'N2_1.txt',      # 0.1 V·s⁻¹，既作扫速系列一员也作空白
    'n2_02': 'N2_2.txt',         # 0.2 V·s⁻¹
    'n2_05': 'N2_5.txt',         # 0.5 V·s⁻¹
    'o2_fast': 'O2_fast.txt',    # O₂ 快速搅拌（通气 + 搅拌）
    'o2_slow': 'O2_slow.txt',    # O₂ 低速搅拌（仅通气）
    'o2_still': 'O2_still.txt',  # O₂ 电解质静止（不通气不搅拌）
    'meoh': 'MeOH.txt',          # N₂ 饱和甲醇 + 硫酸
}

SCAN_RATES = [('0.1', 'n2_blank'), ('0.2', 'n2_02'), ('0.5', 'n2_05')]
O2_CONDITIONS = [('fast', 'o2_fast', '快速搅拌'), ('slow', 'o2_slow', '低速搅拌'),
                 ('still', 'o2_still', '电解质静止')]


# ---------------------------------------------------------------- 解析
_HDR_PAT = {
    'init_e': r'Init E \(V\) = ([-+0-9.eE]+)',
    'high_e': r'High E \(V\) = ([-+0-9.eE]+)',
    'low_e': r'Low E \(V\) = ([-+0-9.eE]+)',
    'scan_rate': r'Scan Rate \(V/s\) = ([-+0-9.eE]+)',
    'sensitivity': r'Sensitivity \(A/V\) = ([-+0-9.eE]+)',
    'segments': r'Segment = (\d+)',
    'quiet_time': r'Quiet Time \(sec\) = ([-+0-9.eE]+)',
}


class CvFile:
    """一份 CHI 导出的 CV 数据：头部参数 + 峰分析表 + 各段数据。"""

    def __init__(self, path):
        self.path = path
        self.name = os.path.basename(path)
        with open(path, 'rb') as fh:
            raw = fh.read()
        txt = None
        for enc in ('gbk', 'utf-8', 'latin-1'):
            try:
                txt = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        self.header_text = txt

        self.params = {}
        for key, pat in _HDR_PAT.items():
            m = re.search(pat, txt)
            self.params[key] = float(m.group(1)) if m else float('nan')
        m = re.search(r'Init P/N = (\w)', txt)
        self.init_scan = (m.group(1) if m else 'N')
        m = re.search(r'^([A-Z][a-z]{2}\. \d+, \d{4})', txt)
        self.date = m.group(1) if m else ''

        # 峰分析表：Segment N: 之后 Ep/ip/Ah 三行一组（奇数段才有峰）
        # 注意 CHI 导出的 txt 是 CRLF 行尾，用 \s 容忍 \r
        self.peaks = {}          # segment(1-based) -> [{'Ep':V,'ip':A,'Ah':C}, …]
        head = txt.split('Potential/V, Current/A, Charge/C')[0]
        for m in re.finditer(r'Segment (\d+):((?:[^\n]*\n)*?)(?=Segment \d+:|\Z)',
                             head):
            seg_no = int(m.group(1))
            lst = []
            for block in re.findall(
                    r'Ep\s*=\s*([-+0-9.eE]+)\s*V\s*\n\s*ip\s*=\s*([-+0-9.eE]+)\s*A'
                    r'(?:\s*\n\s*A[hH]\s*=\s*([-+0-9.eE]+)\s*C)?', m.group(2)):
                lst.append({'Ep': float(block[0]), 'ip': float(block[1]),
                            'Ah': float(block[2]) if block[2] else float('nan')})
            if lst:
                self.peaks[seg_no] = lst

        # 数据区：Segment 1..6
        body = txt.split('Potential/V, Current/A, Charge/C')[1]
        self.segments = []
        for chunk in re.split(r'Segment \d+:', body)[1:]:
            pts = []
            for line in chunk.splitlines():
                line = line.strip()
                if not re.match(r'^[-+]?[0-9.]', line):
                    continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 2:
                    try:
                        pts.append((float(parts[0]), float(parts[1])))
                    except ValueError:
                        continue
            self.segments.append(np.array(pts) if pts else np.zeros((0, 2)))

    @property
    def v(self):
        return self.params.get('scan_rate', float('nan'))

    def seg(self, no):
        """1-based 段号（与 CHI 界面一致）。"""
        return self.segments[no - 1]

    def cycle(self, neg_seg=5, pos_seg=6):
        """负扫段在前、正扫段在后拼成完整一圈（图上从 High E 出发）。"""
        a = self.seg(neg_seg)
        b = self.seg(pos_seg)
        return np.vstack([a, b])


def load_cv(path):
    return CvFile(path)


# ---------------------------------------------------------------- 数据处理
def moving_average(y, window):
    """滑动平均平滑（反射填充，避免两端假性跌落）。window=1 不平滑。"""
    w = int(window)
    if w <= 1:
        return np.asarray(y, float)
    if w % 2 == 0:
        w += 1
    y = np.asarray(y, float)
    pad = w // 2
    yp = np.pad(y, pad, mode='reflect')
    return np.convolve(yp, np.ones(w) / w, mode='same')[pad:-pad]


def diff_vs_blank(seg, blank_seg, window=9):
    """按电势对齐后取差值（两段网格一致时直接相减，不一致时插值）。"""
    E, I = seg[:, 0], seg[:, 1]
    Eb, Ib = blank_seg[:, 0], blank_seg[:, 1]
    if len(E) == len(Eb) and np.allclose(E, Eb, atol=1e-6):
        d = I - Ib
    else:
        d = I - np.interp(E, Eb, Ib)
    return E, d, moving_average(d, window)


def first_crossing(E, d_smooth, threshold, direction='below', e_lo=None, e_hi=None):
    """沿扫描顺序找第一个 |信号| 越过阈值的电势。

    direction='below'：信号 < −threshold（阳极过剩，如甲醇氧化）
    direction='above'：信号 > +threshold（阴极过剩，如氧还原）
    e_lo/e_hi 限定电势窗口。E 必须按扫描顺序排列。
    返回 (电势, 数组下标)；找不到返回 (nan, -1)。
    """
    m = np.ones(len(E), bool)
    if e_lo is not None:
        m &= (E >= e_lo)
    if e_hi is not None:
        m &= (E <= e_hi)
    if direction == 'above':
        m &= (d_smooth > threshold)
    else:
        m &= (d_smooth < -threshold)
    idx = int(np.argmax(m))
    if not m.any():
        return float('nan'), -1
    return float(E[idx]), idx


def last_crossing(E, d_smooth, threshold, e_lo=None, e_hi=None):
    """找信号仍 > +threshold 的最高电势（正扫还原支的「合拢点」）。"""
    m = np.ones(len(E), bool)
    if e_lo is not None:
        m &= (E >= e_lo)
    if e_hi is not None:
        m &= (E <= e_hi)
    m &= (d_smooth > threshold)
    if not m.any():
        return float('nan'), -1
    idx = int(np.max(np.nonzero(m)[0]))
    return float(E[idx]), idx


def integrate_peak(E, I, e_lo, e_hi, baseline):
    """∫(I − baseline)dE，返回面积的绝对值（A·V）。"""
    m = (E >= e_lo) & (E <= e_hi)
    if m.sum() < 3:
        return float('nan')
    return abs(float(np.trapezoid(I[m] - baseline, E[m])))


def auto_dl_baseline(seg, e_lo=0.10, e_hi=0.20):
    """双电层基线：正扫段在给定窗口内的平均电流（氢区之后的「上基线」）。"""
    E, I = seg[:, 0], seg[:, 1]
    m = (E >= e_lo) & (E <= e_hi)
    if not m.any():
        return float(I.mean())
    return float(I[m].mean())


def rising_segment(E, i, tol=0.0):
    """沿扫描方向取电流上升段（到第一个显著峰顶为止）。

    ORR 还原支（E 递减、电流递增）与 MOR 氧化支（E 递增、电流递增）
    都可用：从头开始保留电流不低于「至今最大值 − tol」的点，
    遇到显著回落即停，主峰之后的下降沿不进入插值。
    """
    E = np.asarray(E, float)
    i = np.asarray(i, float)
    if len(E) < 3:
        return E, i
    run_max = -np.inf
    cut = len(E)
    for k in range(len(E)):
        v = i[k]
        if v < run_max - tol:
            cut = k
            break
        if v > run_max:
            run_max = v
    return E[:cut], i[:cut]


def find_monotone_branch(E, i, e_lo, e_hi, rising_with='falling_E'):
    """截取电流单调的一段曲线（DMFC 取支用）。

    rising_with='falling_E'：E 下降电流上升（ORR 还原支）
    rising_with='rising_E' ：E 上升电流上升（MOR 氧化支）
    返回 (E, i) 并按电流升序排序，供 np.interp 使用。
    """
    m = (E >= e_lo) & (E <= e_hi) & np.isfinite(i)
    Ew, iw = E[m], i[m]
    if len(Ew) < 3:
        return Ew, iw
    # 局部非单调（噪声抖动）不影响插值；只在窗口两端各留最小间隔
    order = np.argsort(iw)
    return Ew[order], iw[order]


def dmfc_curves(orr_E, orr_i, mor_E, mor_i, i_min=3e-8, i_step=5e-8,
                i_max_cap=float('inf')):
    """由 ORR / MOR 两条扣空白曲线（电流量值）插值出 DMFC 极化与功率曲线。

    orr_i / mor_i 都是正的量值。电流网格从 i_min 到两条支都能提供的最大电流
    （不超过 i_max_cap），步长 i_step；工作区只保留 E_cell > 0 的部分，
    即到两支曲线的交点为止。返回 dict：
        i_grid, E_orr, E_mor, E_cell, P, P_max, E_at_Pmax, I_max,
        I_intersect, E_intersect
    """
    io_E, io_i = find_monotone_branch(orr_E, orr_i, -1e9, 1e9)
    mo_E, mo_i = find_monotone_branch(mor_E, mor_i, -1e9, 1e9)
    if len(io_i) < 3 or len(mo_i) < 3:
        return None
    i_top = min(io_i.max(), mo_i.max(), i_max_cap)
    if not np.isfinite(i_top) or i_top <= i_min:
        return None
    grid = np.arange(i_min, i_top, i_step)
    if len(grid) < 3:
        return None
    E_orr = np.interp(grid, io_i, io_E)
    E_mor = np.interp(grid, mo_i, mo_E)
    E_cell = E_orr - E_mor
    # 工作区：到交点为止（交点之后 E_ORR < E_MOR，电池不能工作）
    neg = np.nonzero(E_cell <= 0)[0]
    if len(neg):
        k0 = int(neg[0])
        grid, E_orr, E_mor, E_cell = (a[:k0] for a in
                                      (grid, E_orr, E_mor, E_cell))
    if len(grid) < 3:
        return None
    P = grid * E_cell
    k = int(np.argmax(P))
    return dict(i_grid=grid, E_orr=E_orr, E_mor=E_mor, E_cell=E_cell, P=P,
                P_max=float(P[k]), E_at_Pmax=float(E_cell[k]),
                I_at_Pmax=float(grid[k]), I_max=float(grid[-1]),
                I_intersect=float(grid[-1]), E_intersect=float(E_orr[-1]),
                E_orr_raw=(orr_E, orr_i), E_mor_raw=(mor_E, mor_i))


def scan_directory(data_dir):
    """列出数据目录里的 .txt 文件（相对路径），供界面选择。"""
    if not data_dir or not os.path.isdir(data_dir):
        return []
    out = []
    for root, _dirs, files in os.walk(data_dir):
        for f in files:
            if f.lower().endswith('.txt'):
                p = os.path.join(root, f)
                out.append(os.path.relpath(p, data_dir).replace('\\', '/'))
    return sorted(out)


def resolve_file(data_dir, name):
    """数据目录下找文件；找不到再按文件名全目录搜一层。"""
    if not name:
        return None
    p = os.path.join(data_dir, name)
    if os.path.isfile(p):
        return p
    base = os.path.basename(name)
    for root, _dirs, files in os.walk(data_dir):
        if base in files:
            return os.path.join(root, base)
    return None
