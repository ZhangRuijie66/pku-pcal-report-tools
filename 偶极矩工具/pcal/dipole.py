# -*- coding: utf-8 -*-
"""稀溶液法测定极性分子的偶极矩 —— 数据读取 + 计算内核。

体系：正丁醇（极性，溶质）+ 环己烷（非极性，溶剂），5 个浓度点。

处理链与课程数据处理表（数据处理2.xlsx）及 2025 年参考报告一致：
  1) x   = (m₁/M₂) / [(m₁/M₂) + (m₂−m₁)/M₁]
  2) ε_环 = 2.023 − 0.0016·(T/K − 293)（环己烷 25 ℃ 附近的手册线性式）
     C₀   = (C′_环 − C′_空)/(ε_环 − 1)，C_分 = C′_空 − C₀
     ε    = (C′_样 − C_分)/C₀
  3) ε = a·x + ε₁，ρ = b·x + ρ₁ 两条线性拟合（OLS 参数标准误）
  4) 比重瓶：ρ_B = (m_B − m₀)/(m_w − m₀)·ρ_w(T)
  5) A = (ε₁−1)/(ε₁+2)/ρ₁，B = M₁/ρ₁，C = 3M₁/((ε₁+2)²ρ₁)
     P̄₂^∞ = A·(M₂ − bB) + aC（Hedestrand 外推，cm³·mol⁻¹）
  6) R = (n²−1)/(n²+2)·M₂/ρ₂（摩尔折射度，作电子极化度）
  7) μ/D = 12.81·sqrt[(P̄₂^∞ − R)·T]（P、R 以 m³·mol⁻¹ 计）
所有不确定度按 §3.10 口径给 2 位有效数字、末位对齐（格式化在 report.py）。
"""
from __future__ import annotations

import json
import math

import numpy as np

# μ(D) = 12.81·sqrt(P·T)：由 μ = sqrt(9ε₀kT·P/N_A) 换算到 Debye 的常数
MU_CONST = 12.81

# 环己烷介电常数的温度线性式（讲义/手册口径）：ε = A − B·(T/K − 293)
EPS_CYC_A = 2.023
EPS_CYC_B = 0.0016
EPS_CYC_T0 = 293.0

# 摩尔原子极化度约占总摩尔极化度的比例（参考报告 4.1.3 引教材）
P_ATOM_FRAC = 0.01

# 正丁醇偶极矩文献值 / D（CRC，参考报告[2]口径）
LIT_MU = 1.66

# 水的密度多项式（0~40 ℃，g·cm⁻³），比重瓶计算用
WATER_RHO_COEF = (0.999841, 6.7940e-5, -9.0953e-6, 1.0017e-7,
                  -1.1201e-9, 6.5363e-12)


def water_density(t_c):
    t = float(t_c)
    p = WATER_RHO_COEF
    return (p[0] + p[1] * t + p[2] * t ** 2 + p[3] * t ** 3
            + p[4] * t ** 4 + p[5] * t ** 5)


def _mean(vals):
    vals = [float(v) for v in (vals or []) if v not in (None, '')]
    return float(np.mean(vals)) if vals else None


def _ols(x, y):
    """y = m·x + b 的最小二乘，参数标准误按 (n−2) 估计。"""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    n = x.size
    xm, ym = x.mean(), y.mean()
    sxx = float(((x - xm) ** 2).sum())
    sxy = float(((x - xm) * (y - ym)).sum())
    m = sxy / sxx
    b = ym - m * xm
    resid = y - (m * x + b)
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - ym) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float('nan')
    s2 = ss_res / (n - 2)
    return {'slope': m, 'intercept': b,
            'sigma_slope': math.sqrt(s2 / sxx),
            'sigma_intercept': math.sqrt(s2 * (1.0 / n + xm * xm / sxx)),
            'r2': r2, 'n': int(n), 'sxx': sxx}


# ---------------------------------------------------------------- 示例数据
def sample_data():
    """示例数据：与 数据处理2.xlsx（参考报告同批）逐位一致。"""
    return {
        'T': 20.7,
        'c_empty': [4.05, 4.05],
        'cyclo': {'c_sample': [6.51, 6.51], 'rho': 0.77845},
        'solutions': [
            {'m1': 0.496, 'm2': 11.488, 'c_sample': [6.70, 6.70],
             'rho': 0.77875},
            {'m1': 0.804, 'm2': 11.501, 'c_sample': [6.87, 6.87],
             'rho': 0.77920},
            {'m1': 1.018, 'm2': 11.508, 'c_sample': [7.00, 7.00],
             'rho': 0.77953},
            {'m1': 1.225, 'm2': 11.507, 'c_sample': [7.14, 7.14],
             'rho': 0.77987},
            {'m1': 1.534, 'm2': 11.526, 'c_sample': [7.36, 7.36],
             'rho': 0.78042},
        ],
        'butanol': {'rho_de45': 0.80955, 'n': 1.3988},
        'pycno': {'m0': 20.486, 'mw': [25.555, 25.555], 'mB': 24.598},
    }


def normalize_data(data):
    """界面/JSON 数据整理成内核格式（缺的字段用示例数据补齐）。"""
    base = sample_data()
    out = {}
    if not isinstance(data, dict):
        return base
    try:
        out['T'] = float(data.get('T'))
    except (TypeError, ValueError):
        out['T'] = base['T']

    def floats(vals):
        out_v = []
        for v in vals or []:
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(v):
                out_v.append(v)
        return out_v

    out['c_empty'] = floats(data.get('c_empty')) or base['c_empty']
    cyc = data.get('cyclo') or {}
    out['cyclo'] = {'c_sample': floats(cyc.get('c_sample')) or base['cyclo']['c_sample'],
                    'rho': float(cyc.get('rho') or base['cyclo']['rho'])}
    sols = []
    for i, s in enumerate(data.get('solutions') or base['solutions']):
        s = s or {}
        ref = base['solutions'][i] if i < len(base['solutions']) else {}
        sols.append({'m1': float(s.get('m1') or ref.get('m1') or 0) or None,
                     'm2': float(s.get('m2') or ref.get('m2') or 0) or None,
                     'c_sample': floats(s.get('c_sample')) or None,
                     'rho': float(s.get('rho') or ref.get('rho') or 0) or None})
    out['solutions'] = [s for s in sols if s['m1'] and s['m2'] and s['c_sample']
                        and s['rho']]
    but = data.get('butanol') or {}
    out['butanol'] = {'rho_de45': float(but.get('rho_de45')
                                        or base['butanol']['rho_de45']),
                      'n': float(but.get('n') or base['butanol']['n'])}
    py = data.get('pycno') or base['pycno']
    out['pycno'] = {'m0': float(py.get('m0') or base['pycno']['m0']),
                    'mw': floats(py.get('mw')) or base['pycno']['mw'],
                    'mB': float(py.get('mB') or base['pycno']['mB'])}
    return out


# ---------------------------------------------------------------- 数据解析
def parse_numeric_rows(text):
    """从粘贴的文本里读数值行：逗号/制表符/空白分隔都认。"""
    import re
    rows = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r'[,;\t]| {2,}| ', line)
        vals = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            try:
                vals.append(float(p))
            except ValueError:
                break
        if vals and all(math.isfinite(v) for v in vals):
            rows.append(vals)
    return rows


# ---------------------------------------------------------------- 内核
def _sigma_A(eps1, rho1, s_eps1, s_rho1):
    t1 = (3.0 * s_eps1 / (eps1 + 2.0) ** 2) / rho1
    t2 = ((eps1 - 1.0) / (eps1 + 2.0)) * s_rho1 / rho1 ** 2
    return math.sqrt(t1 ** 2 + t2 ** 2)


def _sigma_C(eps1, rho1, M1, s_eps1, s_rho1):
    t1 = (2.0 * s_eps1 / (eps1 + 2.0) ** 3) / rho1
    t2 = s_rho1 / ((eps1 + 2.0) ** 2 * rho1 ** 2)
    return 3.0 * M1 * math.sqrt(t1 ** 2 + t2 ** 2)


def _sigma_P(A, B, C, a, b, M2, s_A, s_B, s_C, s_a, s_b):
    """P̄₂^∞ = A(M₂ − bB) + aC 的不确定度（cm³·mol⁻¹）。"""
    terms = [((M2 - b * B) * s_A) ** 2,
             (A * B * s_b) ** 2,
             (A * b * s_B) ** 2,
             (C * s_a) ** 2,
             (a * s_C) ** 2]
    return math.sqrt(sum(terms)), terms


def analyze(data, cfg=None):
    cfg = cfg or {}
    data = normalize_data(data)
    M1 = float(cfg.get('M1') or 84.159)
    M2 = float(cfg.get('M2') or 74.121)
    s_n = float(cfg.get('sigma_n') or 0.0002)
    s_rho2 = float(cfg.get('sigma_rho2') or 0.00002)
    s_c_hyp = float(cfg.get('sigma_c_check') or 0.01)
    s_T_hyp = float(cfg.get('sigma_T_check') or 1.0)
    lit_mu = float(cfg.get('lit_mu') or LIT_MU)
    p_atom_frac = float(cfg.get('P_atom_frac') or P_ATOM_FRAC)
    warnings = []

    T_c = data['T']
    T_K = T_c + 273.15
    eps_cyc = EPS_CYC_A - EPS_CYC_B * (T_K - EPS_CYC_T0)

    c_empty = _mean(data['c_empty'])
    c_cyc = _mean(data['cyclo']['c_sample'])
    C0 = (c_cyc - c_empty) / (eps_cyc - 1.0)
    C_dist = c_empty - C0

    sols = []
    xs, epss, rhos = [], [], []
    for i, s in enumerate(data['solutions'], 1):
        c_mean = _mean(s['c_sample'])
        x = (s['m1'] / M2) / ((s['m1'] / M2) + (s['m2'] - s['m1']) / M1)
        eps = (c_mean - C_dist) / C0
        sols.append({'no': i, 'm1': s['m1'], 'm2': s['m2'], 'x': x,
                     'c_mean': c_mean, 'rho': s['rho'], 'eps': eps})
        xs.append(x)
        epss.append(eps)
        rhos.append(s['rho'])

    eps_fit = _ols(xs, epss)
    rho_fit = _ols(xs, rhos)
    a, s_a = eps_fit['slope'], eps_fit['sigma_slope']
    eps1, s_eps1 = eps_fit['intercept'], eps_fit['sigma_intercept']
    b, s_b = rho_fit['slope'], rho_fit['sigma_slope']
    rho1, s_rho1 = rho_fit['intercept'], rho_fit['sigma_intercept']

    # ---- 比重瓶
    py = data['pycno']
    rho_w = water_density(T_c)
    mB, m0 = py['mB'], py['m0']
    mw = _mean(py['mw'])
    rhoB_pyc = (mB - m0) / (mw - m0) * rho_w
    rhoB_de45 = data['butanol']['rho_de45']
    E_r_pyc = (rhoB_pyc - rhoB_de45) / rhoB_de45 * 100.0

    # ---- A、B、C 与 P̄₂^∞
    A = (eps1 - 1.0) / (eps1 + 2.0) / rho1
    s_A = _sigma_A(eps1, rho1, s_eps1, s_rho1)
    B = M1 / rho1
    s_B = M1 * s_rho1 / rho1 ** 2
    C = 3.0 * M1 / ((eps1 + 2.0) ** 2 * rho1)
    s_C = _sigma_C(eps1, rho1, M1, s_eps1, s_rho1)
    P_inf = A * (M2 - b * B) + a * C
    s_P, terms_P = _sigma_P(A, B, C, a, b, M2, s_A, s_B, s_C, s_a, s_b)

    # ---- 表 6：把每个拟合参数的不确定度置零后的 σ_P（找主要贡献者）
    zeroed = {}
    for name in ('a', 'eps1', 'b', 'rho1'):
        sa = 0.0 if name == 'a' else s_a
        se = 0.0 if name == 'eps1' else s_eps1
        sb = 0.0 if name == 'b' else s_b
        sr = 0.0 if name == 'rho1' else s_rho1
        sA0 = _sigma_A(eps1, rho1, se, sr)
        sC0 = _sigma_C(eps1, rho1, M1, se, sr)
        sB0 = M1 * sr / rho1 ** 2
        zeroed[name] = _sigma_P(A, B, C, a, b, M2, sA0, sB0, sC0, sa, sb)[0]

    # ---- 摩尔折射度 R
    n_d = data['butanol']['n']
    R_molar = (n_d ** 2 - 1.0) / (n_d ** 2 + 2.0) * M2 / rhoB_de45
    s_R = M2 * math.sqrt(
        (6.0 * n_d * s_n / ((n_d ** 2 + 2.0) ** 2) / rhoB_de45) ** 2
        + (((n_d ** 2 - 1.0) / (n_d ** 2 + 2.0)) * s_rho2 / rhoB_de45 ** 2) ** 2)

    # ---- 偶极矩
    P_m3 = P_inf * 1.0e-6           # cm³ → m³
    s_P_m3 = s_P * 1.0e-6
    R_m3 = R_molar * 1.0e-6
    s_R_m3 = s_R * 1.0e-6
    dP = P_m3 - R_m3
    mu = MU_CONST * math.sqrt(dP * T_K)
    s_mu = MU_CONST * math.sqrt(T_K) * math.sqrt(s_P_m3 ** 2 + s_R_m3 ** 2) \
        / (2.0 * math.sqrt(dP))

    # ---- 4.1.1 末尾：假设每个电容读数有 σ_C′ 的误差
    inv = 1.0 / (eps_cyc - 1.0)
    s_Cdist_h = s_c_hyp * math.sqrt((1.0 + inv) ** 2 + inv ** 2)
    s_C0_h = s_c_hyp * math.sqrt(2.0 * inv ** 2)
    c1 = sols[0]['c_mean'] if sols else c_cyc
    s_eps_h = math.sqrt((s_c_hyp / C0) ** 2 + (s_Cdist_h / C0) ** 2
                        + ((c1 - C_dist) * s_C0_h / C0 ** 2) ** 2)
    s_a_h = s_eps_h / math.sqrt(eps_fit['sxx'])
    s_P_h = _sigma_P(A, B, C, a, b, M2, s_A, s_B, s_C, s_a_h, s_b)[0]
    s_mu_h = MU_CONST * math.sqrt(T_K) \
        * math.sqrt((s_P_h * 1e-6) ** 2 + s_R_m3 ** 2) / (2.0 * math.sqrt(dP))

    # ---- 4.1.2 假设温度有 σ_T 的波动
    s_T_K = s_T_hyp
    s_mu_T = MU_CONST * 0.5 * math.sqrt(
        T_K / dP * (s_P_m3 ** 2 + s_R_m3 ** 2) + dP / T_K * s_T_K ** 2)

    # ---- 4.1.3 摩尔原子极化度的影响
    s_P_atom = p_atom_frac * P_inf
    s_P_corr = math.sqrt(s_P ** 2 + s_P_atom ** 2)
    s_mu_atom = MU_CONST * math.sqrt(T_K) \
        * math.sqrt((s_P_corr * 1e-6) ** 2 + s_R_m3 ** 2) / (2.0 * math.sqrt(dP))

    if len(sols) < 3:
        warnings.append('溶液数据不足 3 组，无法拟合')
    if eps_fit['r2'] < 0.99:
        warnings.append('ε–x 拟合 R² = %.4f 偏低，请检查数据' % eps_fit['r2'])
    if rho_fit['r2'] < 0.99:
        warnings.append('ρ–x 拟合 R² = %.4f 偏低，请检查数据' % rho_fit['r2'])

    return {
        'T_c': T_c, 'T_K': T_K, 'M1': M1, 'M2': M2,
        'eps_cyc': eps_cyc,
        'c_empty': c_empty, 'c_cyc': c_cyc,
        'rho_cyc_measured': data['cyclo']['rho'],
        'C0': C0, 'C_dist': C_dist,
        'solutions': sols,
        'eps_fit': eps_fit, 'rho_fit': rho_fit,
        'a': a, 's_a': s_a, 'eps1': eps1, 's_eps1': s_eps1,
        'b': b, 's_b': s_b, 'rho1': rho1, 's_rho1': s_rho1,
        'rho_w': rho_w, 'rhoB_pyc': rhoB_pyc, 'rhoB_de45': rhoB_de45,
        'E_r_pyc': E_r_pyc, 'pycno': py,
        'A': A, 's_A': s_A, 'B': B, 's_B': s_B, 'C': C, 's_C': s_C,
        'P_inf': P_inf, 's_P': s_P, 'terms_P': terms_P,
        'contrib': zeroed,
        'n_d': n_d, 's_n': s_n, 's_rho2': s_rho2,
        'R_molar': R_molar, 's_R': s_R,
        'mu': mu, 's_mu': s_mu, 'lit_mu': lit_mu,
        'c_check': {'sigma_c': s_c_hyp, 's_Cdist': s_Cdist_h, 's_C0': s_C0_h,
                    's_eps': s_eps_h, 's_a': s_a_h, 's_P': s_P_h,
                    's_mu': s_mu_h},
        'T_check': {'sigma_T': s_T_hyp, 's_mu': s_mu_T},
        'P_atom': {'frac': p_atom_frac, 's_add': s_P_atom,
                   's_P_corr': s_P_corr, 's_mu': s_mu_atom},
        'warnings': warnings,
    }


# ---------------------------------------------------------------- JSON 桥
def data_to_json(data):
    return json.dumps(normalize_data(data), ensure_ascii=False)


def data_from_json(text):
    return normalize_data(json.loads(text))
