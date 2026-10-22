# -*- coding: utf-8 -*-
"""紫外可见吸收光谱仪搭建实验 —— 数据读取与计算内核。

数据来源
--------
课程光谱仪软件导出的 txt，四列制表符分隔：

    index    original    background    difference

· ``original``   —— CCD 原始计数（含暗电流）
· ``background`` —— 软件当前使用的暗背景（可能与本次积分的暗背景不一致）
· ``difference`` —— ``original - background``；本工具一律用它当光强信号

仪器参数（自建光谱仪，元件参数见讲义附录 1）：

· CCD 3648 像素，波长范围随 CCD 位置改变；
· 光栅 600  groove/mm，闪耀波长 500 nm；
· 氘灯 DD2.5A 特征谱线 238.30 / 485.82 / 581.39 / 656.06 nm（用于标定）。

计算链
------
    标定（氘灯三条线 → λ = a·pixel + b）
      → A(λ) = lg(I0/I)（I0 为同条件乙醇空白）
      → 平滑（移动平均）
      → 线性基线（在吸收带两侧取两个锚点）
      → Voigt 分峰拟合（1~2 个组元 + 线性基线）→ 总峰位置 λmax 与吸光度 A
      → ε = A/(c·b)
      → Beer-Lambert 线性拟合（只取线性区，图上仍画出全部数据点）
      → 一维势箱模型验证
"""
from __future__ import annotations

import os
import re

import numpy as np

# 氘灯（DD2.5A）的特征谱线；汞灯备用（讲义里也给了）
DEUTERIUM_LINES = (485.82, 581.39, 656.06)
DEUTERIUM_LINES_ALL = (238.30, 485.82, 581.39, 656.06)
MERCURY_LINES = (253.7, 404.7, 435.8, 546.1, 577.0, 579.0)

# 一维势箱：λ(nm) = K·L(nm)²/(2n+1)，K = 8·m_e·c/h
BOX_K = 3297.8

DEFAULT_SMOOTH = 9          # 移动平均窗口（数据点）
DEFAULT_STRAY = 0.0         # 杂散光占入射光强的比例（0 = 不校正）
PATH_LENGTH_CM = 1.00       # 比色皿光程

# 分子登记表
#   conc  —— 该分子在「其余分子吸收光谱」表里使用的浓度（μmol·L⁻¹）
#   i     —— 一维势箱模型里 C-C=C 基团的个数（A 组 1~4；B 组给的是范围）
#   band  —— 主吸收带所在波长范围（nm），用于基线锚点与寻峰
MOLECULES = {
    'A1': dict(name='3,3′-二乙基硫菁碘盐', short='硫菁', conc=10.0, group='A', i=1,
               band=(380, 520), structure='结构A1.png', source='氘灯'),
    'A2': dict(name='3,3′-二乙基噻碳菁碘化物', short='噻碳菁', conc=5.0, group='A', i=2,
               band=(480, 650), structure='结构A2.png', source='卤钨灯'),
    'A3': dict(name='3,3′-二乙基硫二羰花青碘', short='二羰花青', conc=5.0, group='A', i=3,
               band=(540, 740), structure='结构A3.png', source='卤钨灯'),
    'A4': dict(name='3,3′-二乙基硫杂三羰花青碘化物', short='三羰花青', conc=3.0, group='A', i=4,
               band=(620, 860), structure='结构A4.png', source='卤钨灯'),
    'B1': dict(name='β-胡萝卜素', short='β-胡萝卜素', conc=10.0, group='B', i=(10, 11),
               band=(380, 540), structure='结构B1.png', source='氘灯'),
    'B2': dict(name='2,6-二甲基-2,4,6-辛三烯', short='辛三烯', conc=30.0, group='B', i=(2, 3),
               band=(250, 360), structure='结构B2.png', source='氘灯'),
}

# 三次标定：每次的默认线性系数来自操作者 Origin 工程里保存的拟合结果，
# 作为「先验」；工具会在先验附近重新找峰并重算，偏差过大时退回先验。
CALIBRATIONS = [
    dict(key='d1_long', label='长波范围（第一周 10-14）', day=1, short='第一周长波',
         file='2026-10-14 & 17-01-51-氘灯.txt',
         prior=(0.12586983766424498, 421.9949599219326)),
    dict(key='d2_long', label='长波范围（第二周 10-21）', day=2, short='第二周长波',
         file='2026-10-21 & 13-36-23-1到3的校准.txt',
         prior=(0.12568477103070347, 422.34476038618209)),
    dict(key='d2_short', label='短波范围（第二周 10-21）', day=2, short='第二周短波',
         file='4\\2026-10-21 & 13-44-43-4的校准.txt',
         prior=(0.12758568846992188, 258.30852586769021)),
]

# 测量登记表。key 唯一；mol 指向 MOLECULES；series 标记用途。
#   sample / blank 均为相对于数据目录的路径
A3_OFF = '2\\2026-10-21 & 12-56-02-A3-0.txt'      # A3 浓度系列的空白（乙醇）
SAMPLES = [
    # ---- 第一周：A4
    dict(key='A4', mol='A4', kind='molecule', day=1, cal='d1_long', conc=3.0,
         sample='2026-10-14 & 17-05-15-A4-3.txt',
         blank='2026-10-14 & 17-11-53-A4-乙醇.txt', source='卤钨灯'),
    # ---- 第二周：A3 浓度系列（文件夹 2，长积分）
    dict(key='A3c0.5', mol='A3', kind='conc', day=2, cal='d2_long', conc=0.5,
         sample='2\\2026-10-21 & 12-29-42-A3-0.5.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c1', mol='A3', kind='conc', day=2, cal='d2_long', conc=1.0,
         sample='2\\2026-10-21 & 12-33-43-A3-1.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c5', mol='A3', kind='conc', day=2, cal='d2_long', conc=5.0,
         sample='2\\2026-10-21 & 12-36-40-A3-5.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c10', mol='A3', kind='conc', day=2, cal='d2_long', conc=10.0,
         sample='2\\2026-10-21 & 12-40-17-A3-10.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c20', mol='A3', kind='conc', day=2, cal='d2_long', conc=20.0,
         sample='2\\2026-10-21 & 12-43-5-A3-20.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c20b', mol='A3', kind='conc_rep', day=2, cal='d2_long', conc=20.0,
         sample='2\\2026-10-21 & 12-45-38-A3-20-2.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c50', mol='A3', kind='conc', day=2, cal='d2_long', conc=50.0,
         sample='2\\2026-10-21 & 12-49-34-A3-50.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c50b', mol='A3', kind='conc_rep', day=2, cal='d2_long', conc=50.0,
         sample='2\\2026-10-21 & 12-51-12-A3-50-2.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c5b', mol='A3', kind='conc_rep', day=2, cal='d2_long', conc=5.0,
         sample='2\\2026-10-21 & 13-02-28-A3-5-2.txt', blank=A3_OFF, source='卤钨灯'),
    # ---- 第二周：A3 光源对比（卤钨 + 氘灯）
    dict(key='A3_DW', mol='A3', kind='source', day=2, cal='d2_long', conc=5.0,
         sample='3\\2026-10-21 & 13-06-53-A3-5-D+W.txt',
         blank='3\\2026-10-21 & 13-11-41-A3-0-D+W.txt', source='卤钨灯+氘灯'),
    # ---- 第二周：A2
    dict(key='A2', mol='A2', kind='molecule', day=2, cal='d2_long', conc=5.0,
         sample='3\\2026-10-21 & 13-21-06-A2-5.txt',
         blank='3\\2026-10-21 & 13-23-50-A2-0.txt', source='卤钨灯'),
    dict(key='A2b', mol='A2', kind='molecule_rep', day=2, cal='d2_long', conc=5.0,
         sample='3\\2026-10-21 & 13-31-52-A2-5-2.txt',
         blank='3\\2026-10-21 & 13-23-50-A2-0.txt', source='卤钨灯'),
    # ---- 第二周：短波段三种分子
    dict(key='A1', mol='A1', kind='molecule', day=2, cal='d2_short', conc=10.0,
         sample='4\\2026-10-21 & 13-49-27-A1.txt',
         blank='4\\2026-10-21 & 14-03-45-乙醇.txt', source='氘灯'),
    dict(key='B1', mol='B1', kind='molecule', day=2, cal='d2_short', conc=10.0,
         sample='4\\2026-10-21 & 13-54-44-B1.txt',
         blank='4\\2026-10-21 & 14-03-45-乙醇.txt', source='氘灯'),
    dict(key='B1b', mol='B1', kind='molecule_rep', day=2, cal='d2_short', conc=10.0,
         sample='4\\2026-10-21 & 13-56-47-B1-2.txt',
         blank='4\\2026-10-21 & 14-03-45-乙醇.txt', source='氘灯'),
    dict(key='B1c', mol='B1', kind='molecule_rep', day=2, cal='d2_short', conc=10.0,
         sample='4\\2026-10-21 & 14-14-51-B1-3.txt',
         blank='4\\2026-10-21 & 14-03-45-乙醇.txt', source='氘灯'),
    dict(key='B2', mol='B2', kind='molecule', day=2, cal='d2_short', conc=30.0,
         sample='4\\2026-10-21 & 14-01-40-B2.txt',
         blank='4\\2026-10-21 & 14-03-45-乙醇.txt', source='氘灯'),
]

# ---------------------------------------------------------------- 测量选择
# 同一个样品/浓度如果测了多次，用「选择模块」决定报告里用哪一条。
# 下面是每个槽位的候选测量；默认一律取候选里的**最后一次**（用户 2026-10-21 指定），
# 界面上可以逐项改成第一次/第二次。
CONC_VALUES = [0.5, 1.0, 5.0, 10.0, 20.0, 50.0]      # 浓度系列（μmol·L⁻¹）

CONC_CANDIDATES = {
    '0.5': ['A3c0.5'],
    '1': ['A3c1'],
    '5': ['A3c5', 'A3c5b'],
    '10': ['A3c10'],
    '20': ['A3c20', 'A3c20b'],
    '50': ['A3c50', 'A3c50b'],
}

MOLECULE_CANDIDATES = {
    'A1': ['A1'],
    'A2': ['A2', 'A2b'],
    'A3': ['A3c5', 'A3c5b'],
    'A4': ['A4'],
    'B1': ['B1', 'B1b', 'B1c'],
    'B2': ['B2'],
}

# 默认选择：每个槽位取候选里的最后一条
CONC_PICK_DEFAULT = {c: CONC_CANDIDATES[c][-1] for c in CONC_CANDIDATES}
MOLECULE_DEFAULT = {code: MOLECULE_CANDIDATES[code][-1] for code in MOLECULE_CANDIDATES}

# Beer-Lambert 拟合默认用哪几个浓度（线性区）
BEER_CONC_DEFAULT = [0.5, 1.0, 5.0, 10.0]

# 兼容旧接口
BEER_DEFAULT = [CONC_PICK_DEFAULT['%g' % c] for c in BEER_CONC_DEFAULT]
CONC_KEYS = [CONC_PICK_DEFAULT['%g' % c] for c in CONC_VALUES]


def conc_label(value):
    """浓度槽位的键：0.5 → '0.5'、5.0 → '5'。"""
    return '%g' % value


def pick_choices():
    """给界面用的候选清单：{槽位: [sample key, ...]}，按测量时间先后排好。"""
    return {
        'conc': {conc_label(c): list(CONC_CANDIDATES[conc_label(c)]) for c in CONC_VALUES},
        'mol': {code: list(MOLECULE_CANDIDATES[code]) for code in MOLECULE_CANDIDATES},
    }


# ---------------------------------------------------------------- 数据读取
def load_spectrum(path):
    """读一个软件导出的 txt，返回 dict（index / original / background / difference）。"""
    rows = []
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        text = fh.read()
    for ln in text.splitlines():
        parts = ln.split('\t')
        if len(parts) < 4:
            parts = ln.split()
        if len(parts) < 4:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])))
        except ValueError:
            continue
    if not rows:
        raise ValueError('无法识别的数据文件：%s' % path)
    a = np.array(rows, dtype=float)
    return dict(path=path, index=a[:, 0], original=a[:, 1],
                background=a[:, 2], difference=a[:, 3])


def spectrum_files(data_dir, recursive=True):
    """扫描数据目录里的 txt（按路径排序）。"""
    out = []

    def _walk(d):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return
        for n in names:
            p = os.path.join(d, n)
            if os.path.isdir(p):
                if recursive:
                    _walk(p)
            elif n.lower().endswith('.txt'):
                out.append(p)

    _walk(data_dir)
    return out


# ---------------------------------------------------------------- 标定
def _moving_average(y, window):
    """带镜像填充的移动平均，避免两端被零拉低。"""
    y = np.asarray(y, dtype=float)
    w = int(window)
    if w <= 1 or w > len(y):
        return y.copy()
    pad = w // 2
    yp = np.concatenate([y[pad:0:-1], y, y[-2:-pad - 2:-1]])
    k = np.ones(w) / w
    out = np.convolve(yp, k, mode='valid')
    if len(out) < len(y):
        out = np.concatenate([out, [out[-1]] * (len(y) - len(out))])
    return out[:len(y)]


def _parabolic_center(y, i, half=3):
    """在极值索引 i 附近用抛物线拟合求亚像素中心。"""
    n = len(y)
    lo, hi = max(0, i - half), min(n, i + half + 1)
    xs = np.arange(lo, hi, dtype=float)
    ys = y[lo:hi]
    if len(xs) < 3:
        return float(i)
    A = np.vstack([np.ones_like(xs), xs, xs ** 2]).T
    try:
        coef, *_ = np.linalg.lstsq(A, ys, rcond=None)
    except np.linalg.LinAlgError:
        return float(i)
    c = coef[2]
    if abs(c) < 1e-12:
        return float(i)
    x0 = -coef[1] / (2 * c)
    if not (lo - 1 <= x0 <= hi):
        return float(i)
    return float(x0)


def calibrate(spec, prior=None, lines=DEUTERIUM_LINES, search_px=45):
    """从氘灯（或汞灯）谱图找特征线，线性拟合 λ = a·pixel + b。

    prior=(a, b) 给出先验线性系数，用来把寻峰窗口限制在 ±search_px 像素内，
    避免在噪声里挑错峰。返回的 'ok'=False 时调用方应退回先验。
    """
    d = spec['difference'].astype(float)
    idx = spec['index'].astype(float)
    sm = _moving_average(d, 31)
    sm = sm - np.median(sm)
    pts = []
    if prior:
        a0, b0 = prior
        for lam in lines:
            px = (lam - b0) / a0
            w = int(search_px)
            lo = int(max(0, round(px) - w))
            hi = int(min(len(sm) - 1, round(px) + w))
            if hi <= lo + 2:
                continue
            seg = sm[lo:hi + 1]
            i = lo + int(np.argmax(seg))
            c = _parabolic_center(sm, i)
            pts.append((1.0 + c, lam))          # index 列从 1 开始
    else:
        # 没有先验：取全局最突出的三个峰，按候选组合拟合
        import itertools
        from scipy.signal import find_peaks
        pk, prop = find_peaks(sm, prominence=np.max(sm) * 0.03, distance=15)
        cand = sorted(pk.tolist(), key=lambda i: -sm[i])[:10]
        best = None
        for combo in itertools.combinations(cand, 3):
            xs = np.array([1.0 + c for c in combo])
            A = np.vstack([xs, np.ones(3)]).T
            coef, *_ = np.linalg.lstsq(A, np.asarray(lines), rcond=None)
            pred = A @ coef
            ss = np.sum((np.asarray(lines) - pred) ** 2)
            sst = np.sum((np.asarray(lines) - np.mean(lines)) ** 2)
            r2 = 1 - ss / sst
            if best is None or r2 > best[0]:
                best = (r2, coef, xs)
        if best:
            coef = best[1]
            pts = [(x, lam) for x, lam in zip(best[2], lines)]

    if len(pts) < 2:
        if prior:
            return dict(ok=False, a=prior[0], b=prior[1], sigma_a=0.0, sigma_b=0.0,
                        r2=0.0, points=[], n=0, fallback=True)
        raise ValueError('标定失败：找不到足够的特征峰')

    xs = np.array([p[0] for p in pts], dtype=float)
    ys = np.array([p[1] for p in pts], dtype=float)
    A = np.vstack([xs, np.ones_like(xs)]).T
    coef, res, *_ = np.linalg.lstsq(A, ys, rcond=None)
    pred = A @ coef
    n = len(xs)
    if n >= 3:
        s2 = np.sum((ys - pred) ** 2) / (n - 2)
        s = np.sqrt(max(s2, 0.0))
        sxx = np.sum((xs - xs.mean()) ** 2)
        sigma_a = s / np.sqrt(sxx) if sxx > 0 else 0.0
        sigma_b = s * np.sqrt(1.0 / n + xs.mean() ** 2 / sxx) if sxx > 0 else 0.0
        sst = np.sum((ys - ys.mean()) ** 2)
        r2 = 1 - np.sum((ys - pred) ** 2) / sst if sst > 0 else 1.0
    else:
        sigma_a = sigma_b = 0.0
        r2 = 1.0
    out = dict(ok=True, a=float(coef[0]), b=float(coef[1]),
               sigma_a=float(sigma_a), sigma_b=float(sigma_b), r2=float(r2),
               points=[(float(p[0]), float(p[1])) for p in pts], n=n,
               fallback=False)
    # 与先验偏差过大 → 认为寻峰失败
    if prior and out['ok']:
        da = abs(out['a'] - prior[0]) / abs(prior[0])
        db = abs(out['b'] - prior[1])
        if da > 0.03 or db > 15:
            out.update(ok=False, fallback=True, a=prior[0], b=prior[1])
    return out


def to_wavelength(cal, index=None, n=3648):
    idx = np.arange(1, n + 1, dtype=float) if index is None else np.asarray(index, float)
    return cal['a'] * idx + cal['b']


# ---------------------------------------------------------------- 吸光度
def absorbance_curve(sample, blank, cal, smooth_window=DEFAULT_SMOOTH,
                     stray=0.0, n=None):
    """A(λ) = lg(I0/I)；stray>0 时按「杂散光占入射光强的比例」扣底。

    返回 dict(lam, A_raw, A_smooth, A_raw_plain, A_smooth_plain, I, I0)：
    · ``*_plain`` 是完全不扣杂散光的原始吸光度（作图定性比较用）；
    · 不带 plain 的版本按 stray 扣底（定量计算用）。
    """
    I = sample['difference'].astype(float)
    I0 = blank['difference'].astype(float)
    m = min(len(I), len(I0))
    I, I0 = I[:m], I0[:m]
    lam = to_wavelength(cal, sample['index'][:m])
    with np.errstate(divide='ignore', invalid='ignore'):
        A_plain = np.log10(I0 / I)
        if stray and stray > 0:
            S = stray * I0
            A = np.log10((I0 - S) / (I - S))
        else:
            A = A_plain.copy()
    A = np.where(np.isfinite(A), A, np.nan)
    A_plain = np.where(np.isfinite(A_plain), A_plain, np.nan)
    A_sm = np.where(np.isfinite(A),
                    _moving_average(np.nan_to_num(A, nan=0.0), smooth_window), np.nan)
    A_sm0 = np.where(np.isfinite(A_plain),
                     _moving_average(np.nan_to_num(A_plain, nan=0.0), smooth_window), np.nan)
    return dict(lam=lam, A_raw=A, A_smooth=A_sm,
                A_raw_plain=A_plain, A_smooth_plain=A_sm0, I=I, I0=I0)


def baseline_line(lam, A, anchors):
    """在 anchors 两个窗口里各取中位 A，连成直线。

    anchors = ((lo1, hi1), (lo2, hi2))，单位 nm。
    返回 (k, b, A_corr)；A_corr = A - (k·λ + b)。
    """
    def _med(lo, hi):
        m = np.isfinite(A) & (lam >= lo) & (lam <= hi)
        if not np.any(m):
            return np.nan
        return float(np.median(A[m]))

    (lo1, hi1), (lo2, hi2) = anchors
    x1 = (lo1 + hi1) / 2.0
    x2 = (lo2 + hi2) / 2.0
    y1, y2 = _med(lo1, hi1), _med(lo2, hi2)
    if not (np.isfinite(y1) and np.isfinite(y2)) or x2 == x1:
        k, b = 0.0, 0.0
    else:
        k = (y2 - y1) / (x2 - x1)
        b = y1 - k * x1
    A_corr = A - (k * lam + b)
    return k, b, A_corr


def default_anchors(band, pad=80, width=25):
    """按吸收带自动给基线锚点：带外两侧各一个窗口。"""
    lo, hi = band
    lo1 = max(240.0, lo - pad)
    lo2 = max(240.0, lo - pad + width)
    hi1 = hi + pad - width
    hi2 = hi + pad
    return ((lo1, lo2), (hi1, hi2))


def find_peak(lam, A, band, half_px=2):
    """在 band 内找 A 的极大点；用抛物线插值给出亚像素 λmax。"""
    m = np.isfinite(A) & (lam >= band[0]) & (lam <= band[1])
    if not np.any(m):
        return nan_peak()
    idx = np.where(m)[0]
    j = idx[int(np.argmax(A[idx]))]
    i = int(j)
    lam_pk = float(lam[i])
    a_pk = float(A[i])
    if 1 <= i < len(A) - 1 and np.isfinite(A[i - 1]) and np.isfinite(A[i + 1]):
        y0, y1, y2 = A[i - 1], A[i], A[i + 1]
        denom = (y0 - 2 * y1 + y2)
        if abs(denom) > 1e-12:
            d = 0.5 * (y0 - y2) / denom
            if abs(d) <= 1.0:
                lam_pk = float(lam[i] + d * (lam[i + 1] - lam[i]))
                a_pk = float(y1 - 0.25 * (y0 - y2) * d)
    return dict(index=i, lam=lam_pk, A=a_pk)


def nan_peak():
    return dict(index=-1, lam=float('nan'), A=float('nan'))


# ---------------------------------------------------------------- Voigt 分峰
def _voigt_shape(x, amp, center, sigma, gamma):
    """峰高为 amp 的 Voigt 线形（面积归一的 voigt_profile 再按峰高归一）。"""
    from scipy.special import voigt_profile
    sigma = max(abs(float(sigma)), 1e-3)
    gamma = max(abs(float(gamma)), 1e-3)
    prof = voigt_profile(np.asarray(x, float) - center, sigma, gamma)
    peak = voigt_profile(0.0, sigma, gamma)
    return amp * prof / max(peak, 1e-30)


def voigt_fwhm(sigma, gamma):
    """Voigt 线形的半高全宽（近似公式，Olivero & Longbothum）。"""
    fg = 2.0 * sigma * np.sqrt(2 * np.log(2))
    fl = 2.0 * gamma
    return 0.5346 * fl + np.sqrt(0.2166 * fl ** 2 + fg ** 2)


def _half_width(x, y, i, base):
    amp = y[i] - base
    half = base + amp / 2.0
    left = i
    while left > 0 and y[left] > half:
        left -= 1
    right = i
    while right < len(y) - 1 and y[right] > half:
        right += 1
    return max(x[right] - x[left], 2.0)


def _voigt_model(xx, params, deg, n, x0):
    out = np.zeros_like(xx, dtype=float)
    for d in range(deg + 1):
        out = out + params[d] * ((xx - x0) / 200.0) ** d
    for k in range(n):
        off = deg + 1 + 4 * k
        out = out + _voigt_shape(xx, params[off], params[off + 1],
                                 params[off + 2], params[off + 3])
    return out


def _voigt_fit_n(x, y, band, n, deg):
    from scipy.optimize import curve_fit
    x0 = 0.5 * (band[0] + band[1])
    # 吸收带里有一千多个像素，拟合用 200 个左右的点就够，速度差一个量级
    step = max(1, len(x) // 200)
    xs, ys = x[::step], y[::step]
    i = int(np.argmax(ys))
    base = float(np.percentile(np.r_[ys[:4], ys[-4:]], 30))
    fw = _half_width(xs, ys, i, base)
    a0 = max(ys[i] - base, 1e-3)
    c0 = xs[i]
    best = None
    starts = (0.0,) if n == 1 else (-1.0, 1.0)
    for sh in starts:
        p0 = [base] + [0.0] * deg
        lo = [base - 0.6] + [-0.6] * deg
        hi = [base + 0.6] + [0.6] * deg
        for k in range(n):
            cc = c0 if k == 0 else c0 + sh * fw
            amp = a0 if k == 0 else 0.25 * a0
            p0 += [amp, cc, fw / 2.4, fw / 2.4]
            lo += [0.0, band[0] - 30.0, 0.3, 0.02]
            hi += [a0 * 4.0, band[1] + 30.0, 150.0, 150.0]
        try:
            popt, _ = curve_fit(lambda xx, *p: _voigt_model(xx, p, deg, n, x0),
                                xs, ys, p0=p0, bounds=(lo, hi), maxfev=20000)
        except Exception:      # noqa: BLE001  拟合不收敛就换初始值
            continue
        pred = _voigt_model(x, popt, deg, n, x0)
        sst = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - float(np.sum((y - pred) ** 2)) / sst if sst > 0 else 0.0
        if best is None or r2 > best['r2']:
            peaks = []
            for k in range(n):
                off = deg + 1 + 4 * k
                amp, cen, sig, gam = popt[off:off + 4]
                peaks.append(dict(amp=float(amp), center=float(cen),
                                  sigma=float(sig), gamma=float(gam),
                                  fwhm=float(voigt_fwhm(sig, gam))))
            peaks.sort(key=lambda p: -p['amp'])
            best = dict(r2=r2, popt=np.asarray(popt, float), peaks=peaks,
                        deg=deg, n=n, x0=x0)
    return best


def voigt_fit(lam, A, band, n_peaks='auto', deg=1):
    """Voigt 分峰拟合：A(λ) = Σ Voigt(λ) + 低阶基线。

    n_peaks = 1 / 2 / 'auto'：先拟合 1 个峰，若 R² 仍差且第二个组元明显，再试 2 个峰。
    返回的 ``lam_max``/``A_max`` 取自**总拟合曲线**的极大值（不是单个组元的峰高），
    这样它才与实测吸收峰的 λmax、A 对应。
    """
    lam = np.asarray(lam, float)
    A = np.asarray(A, float)
    m = np.isfinite(A) & (lam >= band[0]) & (lam <= band[1])
    x, y = lam[m], A[m]
    if len(x) < 30:
        return None
    # 扣杂散光后如果带内缺了一大片（NaN），拟合会在缺口之间“飞掉”，直接放弃
    span = (lam <= band[1]) & (lam >= band[0])
    if span.sum() and len(x) / float(span.sum()) < 0.75:
        return None
    if isinstance(n_peaks, str):
        auto = True
        n_try = [1, 2]
    else:
        auto = False
        n_try = [int(n_peaks)]
    best = None
    prev = None
    for n in n_try:
        if len(x) < 6 + 4 * n:
            break
        res = _voigt_fit_n(x, y, band, n, deg)
        if res is None:
            continue
        if prev is None:
            prev = res
            best = res
        if auto and n == 2 and prev is not None:
            prev_peak = max(p['amp'] for p in prev['peaks'])
            if (res['r2'] - prev['r2'] > 0.008
                    and res['peaks'][0]['amp'] > 0.05 * max(prev_peak, 1e-9)
                    and abs(res['peaks'][0]['center'] - res['peaks'][1]['center']) >= 8.0):
                best = res
            else:
                best = prev
    if best is None:
        return None

    grid = np.linspace(band[0], band[1], 800)
    total = _voigt_model(grid, best['popt'], best['deg'], best['n'], best['x0'])
    if not np.all(np.isfinite(total)):
        return None
    # 拟合曲线不能明显超出实测范围（防止拟合在数据缺口处发散）
    if total.max() > y.max() * 1.3 + 0.15 or total.min() < y.min() - 0.5:
        return None
    k = int(np.argmax(total))
    comps = []
    for kk in range(best['n']):
        off = best['deg'] + 1 + 4 * kk
        p = best['popt'][off:off + 4]
        comps.append(_voigt_shape(grid, *p))
    out = dict(
        lam=x, A=y, peaks=best['peaks'], r2=best['r2'], n=best['n'],
        deg=best['deg'], popt=best['popt'], x0=best['x0'],
        grid=grid, total=total, components=comps,
        lam_max=float(grid[k]), A_max=float(total[k]),
        baseline=_voigt_model(grid, np.r_[best['popt'][:best['deg'] + 1],
                                          np.zeros(4 * best['n'])],
                              best['deg'], 0, best['x0']),
    )
    return out


def voigt_eval(fit, x):
    """在任意 x 上计算分峰拟合的总曲线。"""
    if not fit:
        return np.zeros_like(np.asarray(x, float))
    return _voigt_model(np.asarray(x, float), fit['popt'], fit['deg'], fit['n'],
                        fit['x0'])


def molar_extinction(A, conc_umol, path_cm=PATH_LENGTH_CM):
    """ε = A/(c·b)，c 由 μmol·L⁻¹ 换成 mol·L⁻¹，返回 L·mol⁻¹·cm⁻¹。"""
    if not np.isfinite(A) or not conc_umol:
        return float('nan')
    return A / (conc_umol * 1e-6 * path_cm)


# ---------------------------------------------------------------- 线性拟合
def line_fit(x, y):
    """最小二乘 y = k x + b，返回斜率/截距及其标准误差与 R²。"""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n < 2:
        return dict(k=float('nan'), b=float('nan'), sigma_k=float('nan'),
                    sigma_b=float('nan'), r2=float('nan'), n=n)
    A = np.vstack([x, np.ones_like(x)]).T
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    pred = A @ coef
    ss = np.sum((y - pred) ** 2)
    sst = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss / sst if sst > 0 else 1.0
    if n > 2:
        s2 = ss / (n - 2)
        s = np.sqrt(max(s2, 0.0))
        sxx = np.sum((x - x.mean()) ** 2)
        sigma_k = s / np.sqrt(sxx) if sxx > 0 else float('nan')
        sigma_b = s * np.sqrt(1.0 / n + x.mean() ** 2 / sxx) if sxx > 0 else float('nan')
    else:
        sigma_k = sigma_b = float('nan')
    return dict(k=float(coef[0]), b=float(coef[1]), sigma_k=float(sigma_k),
                sigma_b=float(sigma_b), r2=float(r2), n=n)


# ---------------------------------------------------------------- 一维势箱
def particle_in_box(lambdas, a_values=(0, 2, 4, 6, 8, 10)):
    """A 组（Ai：i 个 C-C=C + 2 个芳香基团）的一维势箱拟合。

    L = i·x + 2y，N = 2i + 2a，λ_i = K·L²/(2i+2a+1)。
    用 A1 (i=1) 与 A4 (i=4) 解出 x、y，再预测 A2 (i=2)、A3 (i=3)。

    lambdas = {'A1': λ1, 'A4': λ4, ...}（nm）
    """
    l1 = lambdas.get('A1')
    l4 = lambdas.get('A4')
    rows = []
    for a in a_values:
        if not (l1 and l4 and np.isfinite(l1) and np.isfinite(l4)):
            rows.append(dict(a=a, x=float('nan'), y=float('nan'),
                             lam2=float('nan'), lam3=float('nan')))
            continue
        u = np.sqrt(l1 * (2 * a + 3) / BOX_K)      # x + 2y
        v = np.sqrt(l4 * (2 * a + 9) / BOX_K)      # 4x + 2y
        x = (v - u) / 3.0
        y = (u - x) / 2.0
        lam2 = BOX_K * (2 * x + 2 * y) ** 2 / (2 * a + 5)
        lam3 = BOX_K * (3 * x + 2 * y) ** 2 / (2 * a + 7)
        rows.append(dict(a=a, x=float(x), y=float(y),
                         lam2=float(lam2), lam3=float(lam3)))
    return rows


def box_length(x, i_units):
    """B 组：给定每个 C-C=C 的箱长贡献 x 与基团数（可给范围），返回 L 范围。"""
    lo, hi = (i_units if isinstance(i_units, (tuple, list)) else (i_units, i_units))
    return lo * x, hi * x


def box_lambda(L_nm, n_elec):
    """λ(nm) = K·L²/(2n+1)，n_elec 为 π 电子数。"""
    return BOX_K * L_nm ** 2 / (n_elec + 1)
