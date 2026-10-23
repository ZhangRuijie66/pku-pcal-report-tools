# -*- coding: utf-8 -*-
"""溶液表面吸附的测定 —— 数据模型与计算内核。

两套方法共用同一套热力学处理：

    最大气泡压力法：  γ = γ_w · Δh / Δh_w
    吊片法：          γ 由表面张力仪直接读出

    γ–lg c（或 γ–ln c）线性区拟合 →
    Γ∞ = −(1/(2.303RT))·(dγ/dlg c)  或  −(1/(RT))·(dγ/dln c)
    q  = 1/(Γ∞ N_A)
    q_c = 10^18 / [Γ∞ N_A + 100 (c N_A)^(2/3)]      （c 以 mol·dm⁻³ 计）

单位约定
--------
· c：mol·dm⁻³
· Δh：cm
· γ：mN·m⁻¹（数值上等于 10⁻³ J·m⁻²）
· Γ：mol·m⁻²
· q、q_c：nm²
"""
from __future__ import annotations

import math
import re

import numpy as np
from scipy.stats import linregress

R = 8.314462618          # J·mol⁻¹·K⁻¹
N_A = 6.02214076e23      # mol⁻¹
LN10 = math.log(10.0)

# 纯水表面张力 / mN·m⁻¹（CRC Handbook，常用温度点）
GAMMA_WATER = {20.0: 72.75, 25.0: 71.99, 30.0: 71.19, 35.0: 70.42}

# 正丁醇饱和吸附时的分子截面积文献值（用于讨论，nm²）
Q_LITERATURE = 0.30


def gamma_water_default(temp_c):
    """按温度线性插值纯水表面张力；超出表范围时取最近端点。"""
    t = float(temp_c)
    keys = sorted(GAMMA_WATER)
    if t <= keys[0]:
        return GAMMA_WATER[keys[0]]
    if t >= keys[-1]:
        return GAMMA_WATER[keys[-1]]
    for a, b in zip(keys, keys[1:]):
        if a <= t <= b:
            f = (t - a) / (b - a)
            return GAMMA_WATER[a] + f * (GAMMA_WATER[b] - GAMMA_WATER[a])
    return GAMMA_WATER[30.0]


# ---------------------------------------------------------------- 示例数据
def sample_data():
    """2025 年同一课程实验的完整数据（正丁醇 / 最大气泡压力法 + 吊片法）。

    仅作为「载入示例」和自检用；报告封面会写使用者的姓名学号，
    真实实验时请在界面里替换成自己的数据。
    """
    return {
        'temperature_bubble': 30.0,
        'temperature_plate': 25.0,
        'gamma_water': 71.19,
        'sigma_read': 0.02,
        'sigma_plate': 0.01,
        'zero': {
            'left': [21.80, 21.80, 21.80],
            'right': [22.00, 22.00, 22.00],
        },
        'water_bubble': {
            'left': [17.66, 17.68, 17.67],
            'right': [26.36, 26.36, 26.36],
        },
        'bubble': [
            {'c': 0.0218, 'left': [17.88] * 3, 'right': [26.12] * 3, 'fit': False},
            {'c': 0.0547, 'left': [18.20] * 3, 'right': [25.81] * 3, 'fit': False},
            {'c': 0.1110, 'left': [18.68] * 3, 'right': [25.28] * 3, 'fit': False},
            {'c': 0.2200, 'left': [19.17] * 3, 'right': [24.79] * 3, 'fit': True},
            {'c': 0.3290, 'left': [19.53] * 3, 'right': [24.40] * 3, 'fit': True},
            {'c': 0.4390, 'left': [19.78] * 3, 'right': [24.17] * 3, 'fit': True},
            {'c': 0.5500, 'left': [19.99] * 3, 'right': [24.01] * 3, 'fit': True},
            {'c': 0.7400, 'left': [20.13] * 3, 'right': [23.61] * 3, 'fit': True},
        ],
        'water_plate': [72.50, 72.50, 72.50],
        # 旧报告表格单位是 10⁻² J·m⁻²（即 6.73 表示 67.3 mN·m⁻¹），这里换成 mN·m⁻¹
        'plate': [
            {'c': 0.0218, 'gamma': [66.93, 67.20, 67.62], 'fit': False},
            {'c': 0.0547, 'gamma': [60.38, 61.18, 61.72], 'fit': False},
            {'c': 0.1110, 'gamma': [54.95, 54.25, 54.40], 'fit': True},
            {'c': 0.2200, 'gamma': [47.01, 47.20, 47.35], 'fit': True},
            {'c': 0.3290, 'gamma': [42.37, 40.74, 41.80], 'fit': True},
            {'c': 0.4390, 'gamma': [37.40, 36.71, 36.01], 'fit': False},
            {'c': 0.5500, 'gamma': [35.77, 36.04, 36.35], 'fit': True},
            {'c': 0.7400, 'gamma': [32.69, 33.50, 35.05], 'fit': True},
        ],
    }


# ---------------------------------------------------------------- 文本/CSV
def parse_numeric_rows(text):
    """把 CSV / TSV / 空格分隔的表格解析成 float 行；自动跳过表头和空行。"""
    rows = []
    for line in str(text or '').replace('\r', '').split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [p for p in re.split(r'[,;\t ]+', line) if p]
        vals = []
        ok = True
        for p in parts:
            try:
                vals.append(float(p))
            except ValueError:
                ok = False
                break
        if ok and vals:
            rows.append(vals)
    return rows


def rows_to_bubble(rows):
    """CSV → 最大气泡压力法数据行：c, l1,l2,l3, r1,r2,r3（允许 4 列：c,l,r）。"""
    out = []
    for r in rows:
        if len(r) >= 7:
            out.append({'c': r[0], 'left': r[1:4], 'right': r[4:7], 'fit': False})
        elif len(r) == 3:
            out.append({'c': r[0], 'left': [r[1]], 'right': [r[2]], 'fit': False})
        elif len(r) == 4:
            out.append({'c': r[0], 'left': [r[1]], 'right': [r[2]], 'fit': True})
    return out


def rows_to_plate(rows):
    """CSV → 吊片法数据行：c, γ1,γ2,γ3（允许 2 列：c,γ）。"""
    out = []
    for r in rows:
        if len(r) >= 4:
            out.append({'c': r[0], 'gamma': r[1:4], 'fit': False})
        elif len(r) == 3:
            out.append({'c': r[0], 'gamma': r[1:3], 'fit': False})
        elif len(r) == 2:
            out.append({'c': r[0], 'gamma': [r[1]], 'fit': False})
    return out


# ---------------------------------------------------------------- 统计
def _stats(values, sigma_read):
    vals = np.asarray([float(v) for v in values if v not in (None, '')], dtype=float)
    if vals.size == 0:
        return dict(n=0, mean=float('nan'), sigma=float('nan'),
                    sem=float('nan'), std=float('nan'), values=vals)
    mean = float(vals.mean())
    std = float(vals.std(ddof=1)) if vals.size > 1 else 0.0
    sem = std / math.sqrt(vals.size) if vals.size > 1 else 0.0
    sigma = math.sqrt(sem ** 2 + max(0.0, float(sigma_read)) ** 2)
    return dict(n=int(vals.size), mean=mean, sigma=sigma, sem=sem, std=std,
                values=vals)


def _line_fit(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 2:
        return None
    res = linregress(x, y)
    return dict(slope=float(res.slope), intercept=float(res.intercept),
                sigma_slope=float(res.stderr or 0.0),
                sigma_intercept=float(res.intercept_stderr or 0.0),
                r2=float(res.rvalue ** 2), n=int(x.size),
                x=list(map(float, x)), y=list(map(float, y)))


def _axis_x(c, axis):
    c = np.asarray(c, dtype=float)
    return np.log10(c) if axis == 'lg' else np.log(c)


def _gamma_from_fit(slope, temperature, axis):
    if slope is None or not np.isfinite(slope):
        return float('nan'), float('nan')
    temp = float(temperature) + 273.15
    denom = (LN10 if axis == 'lg' else 1.0) * R * temp
    gamma_inf = -slope / denom
    return gamma_inf, denom


def _qc_row(c, gamma_inf, sigma_gamma):
    """浓度修正后的分子面积 q_c（nm²）及其不确定度。"""
    if not np.isfinite(gamma_inf) or gamma_inf <= 0:
        return dict(c=c, qc=float('nan'), sigma=float('nan'), rel=float('nan'))
    denom = gamma_inf * N_A + 100.0 * (float(c) * N_A) ** (2.0 / 3.0)
    qc = 1e18 / denom
    sigma = 1e18 * N_A * sigma_gamma / (denom ** 2)
    return dict(c=c, qc=qc, sigma=sigma)


# ---------------------------------------------------------------- 单方法分析
def _analyze_bubble(data, cfg):
    axis = 'lg' if cfg.get('conc_axis') == 'lg' else 'ln'
    T = float(data.get('temperature_bubble', 30.0))
    gw = float(data.get('gamma_water') or gamma_water_default(T))
    sigma_read = float(data.get('sigma_read', 0.02))
    zero_corr = bool(cfg.get('zero_correction', True))

    zero = data.get('zero') or {}
    zl = _stats(zero.get('left') or [], sigma_read)
    zr = _stats(zero.get('right') or [], sigma_read)
    dh0 = zr['mean'] - zl['mean']
    sigma_dh0 = math.sqrt(zl['sigma'] ** 2 + zr['sigma'] ** 2)

    water = data.get('water_bubble') or {}
    wl = _stats(water.get('left') or [], sigma_read)
    wr = _stats(water.get('right') or [], sigma_read)
    dhw = (wr['mean'] - wl['mean']) - (dh0 if zero_corr else 0.0)
    sigma_dhw = math.sqrt(wl['sigma'] ** 2 + wr['sigma'] ** 2 +
                          (sigma_dh0 ** 2 if zero_corr else 0.0))

    rows = []
    for it in data.get('bubble') or []:
        c = float(it.get('c') or 0.0)
        sl = _stats(it.get('left') or [], sigma_read)
        sr = _stats(it.get('right') or [], sigma_read)
        dh = (sr['mean'] - sl['mean']) - (dh0 if zero_corr else 0.0)
        sigma_dh = math.sqrt(sl['sigma'] ** 2 + sr['sigma'] ** 2 +
                             (sigma_dh0 ** 2 if zero_corr else 0.0))
        gamma = gw * dh / dhw if dhw else float('nan')
        sigma_gamma = (abs(gamma) * math.sqrt((sigma_dh / dh) ** 2 +
                                              (sigma_dhw / dhw) ** 2)
                       if dh and dhw else float('nan'))
        rows.append(dict(c=c, left=sl, right=sr, dh=dh, sigma_dh=sigma_dh,
                         gamma=gamma, sigma_gamma=sigma_gamma,
                         fit=bool(it.get('fit', False))))

    fit_rows = [r for r in rows if r['fit'] and r['c'] > 0 and np.isfinite(r['gamma'])]
    fit = None
    gamma_inf = sigma_gamma_inf = q = sigma_q = float('nan')
    qc_rows = []
    if len(fit_rows) >= 2:
        x = _axis_x([r['c'] for r in fit_rows], axis)
        y = [r['gamma'] * 1e-3 for r in fit_rows]
        fit = _line_fit(x, y)
        gamma_inf, denom = _gamma_from_fit(fit['slope'], T, axis)
        sigma_gamma_inf = fit['sigma_slope'] / denom
        if np.isfinite(gamma_inf) and gamma_inf > 0:
            q = 1e18 / (gamma_inf * N_A)
            sigma_q = q * sigma_gamma_inf / gamma_inf
            qc_rows = [_qc_row(r['c'], gamma_inf, sigma_gamma_inf)
                       for r in fit_rows]
            for row in qc_rows:
                row['rel'] = ((row['qc'] - q) / q * 100.0
                              if q else float('nan'))

    return dict(method='bubble', label='最大气泡压力法', axis=axis,
                temperature=T, gamma_water=gw, zero_correction=zero_corr,
                sigma_read=sigma_read,
                zero=dict(left=zl, right=zr, dh=dh0, sigma_dh=sigma_dh0),
                water=dict(left=wl, right=wr, dh=dhw, sigma_dh=sigma_dhw),
                rows=rows, fit_rows=fit_rows, fit=fit,
                gamma_inf=gamma_inf, sigma_gamma_inf=sigma_gamma_inf,
                q=q, sigma_q=sigma_q, qc_rows=qc_rows)


def _analyze_plate(data, cfg):
    axis = 'lg' if cfg.get('conc_axis') == 'lg' else 'ln'
    T = float(data.get('temperature_plate', 25.0))
    sigma_inst = float(data.get('sigma_plate', 0.01))

    water = _stats(data.get('water_plate') or [], sigma_inst)
    rows = []
    for it in data.get('plate') or []:
        c = float(it.get('c') or 0.0)
        st = _stats(it.get('gamma') or [], sigma_inst)
        rows.append(dict(c=c, gamma=st['mean'], sigma_gamma=st['sigma'],
                         stats=st, fit=bool(it.get('fit', False))))

    fit_rows = [r for r in rows if r['fit'] and r['c'] > 0 and np.isfinite(r['gamma'])]
    fit = None
    gamma_inf = sigma_gamma_inf = q = sigma_q = float('nan')
    qc_rows = []
    if len(fit_rows) >= 2:
        x = _axis_x([r['c'] for r in fit_rows], axis)
        y = [r['gamma'] * 1e-3 for r in fit_rows]
        fit = _line_fit(x, y)
        gamma_inf, denom = _gamma_from_fit(fit['slope'], T, axis)
        sigma_gamma_inf = fit['sigma_slope'] / denom
        if np.isfinite(gamma_inf) and gamma_inf > 0:
            q = 1e18 / (gamma_inf * N_A)
            sigma_q = q * sigma_gamma_inf / gamma_inf
            qc_rows = [_qc_row(r['c'], gamma_inf, sigma_gamma_inf)
                       for r in fit_rows]
            for row in qc_rows:
                row['rel'] = ((row['qc'] - q) / q * 100.0
                              if q else float('nan'))

    return dict(method='plate', label='吊片法', axis=axis,
                temperature=T, sigma_inst=sigma_inst, water=water,
                rows=rows, fit_rows=fit_rows, fit=fit,
                gamma_inf=gamma_inf, sigma_gamma_inf=sigma_gamma_inf,
                q=q, sigma_q=sigma_q, qc_rows=qc_rows)


def analyze(data, cfg=None):
    """完整分析；返回可直接给绘图、报告、网页用的字典。"""
    cfg = dict(cfg or {})
    data = dict(data or {})
    warnings = []

    bubble = _analyze_bubble(data, cfg)
    plate = _analyze_plate(data, cfg)

    for m in (bubble, plate):
        for r in m['rows']:
            if not np.isfinite(r.get('gamma', np.nan)):
                warnings.append('%s：c = %g mol·dm⁻³ 的表面张力算不出来（检查高度差/读数）'
                                % (m['label'], r['c']))
        if len(m['fit_rows']) < 2:
            warnings.append('%s：线性区选点少于 2 个，无法拟合' % m['label'])
        elif m['fit'] and m['fit']['r2'] < 0.98:
            warnings.append('%s：线性区拟合 R² = %.4f，偏低；建议检查离群点或调整选点'
                            % (m['label'], m['fit']['r2']))
        if np.isfinite(m['gamma_inf']) and m['gamma_inf'] <= 0:
            warnings.append('%s：拟合斜率为正，Γ∞ 为负；检查数据或选点' % m['label'])
    if bubble['water']['dh'] <= 0:
        warnings.append('最大气泡压力法：纯水高度差 ≤ 0，检查零点与液柱读数')
    if abs(bubble['zero']['dh']) > 0.5:
        warnings.append('压力计零点差 %.2f cm 偏大，确认零点读数是否正确'
                        % bubble['zero']['dh'])

    comparison = {}
    if (np.isfinite(bubble['gamma_inf']) and np.isfinite(plate['gamma_inf'])
            and bubble['gamma_inf'] != 0):
        comparison = dict(
            d_gamma=plate['gamma_inf'] - bubble['gamma_inf'],
            rel_gamma=(plate['gamma_inf'] - bubble['gamma_inf'])
            / bubble['gamma_inf'] * 100.0,
            d_q=plate['q'] - bubble['q'],
            rel_q=(plate['q'] - bubble['q']) / bubble['q'] * 100.0
            if bubble['q'] else float('nan'))

    return dict(bubble=bubble, plate=plate, comparison=comparison,
                warnings=warnings, q_literature=Q_LITERATURE,
                axis=bubble['axis'],
                config=dict(cfg))
