# -*- coding: utf-8 -*-
"""电解质溶液电导率的测定 —— 计算内核。

实验流程（讲义 实验七）：
    KCl 标准溶液标定电导池常数 → 测去离子水 κw →
    测 4 种溶液 5 个浓度的电导率 → κ 校正 / 摩尔电导率 →
    强电解质 Kohlrausch 拟合外推 Λm∞ → 离子独立运动定律得 Λm∞(HAc) →
    弱电解质两种方法求标准电离平衡常数 K°。

原始数据是手记读数（电导率仪无数据导出），存放在
``<数据目录>/电导率数据.json``；没有该文件时用内置的 2025 参照数据。
电导率一律以 S·m⁻¹ 存储（字符串保留原始读数的有效位数——末位不确定度
规则「最后一位的 2」依赖小数位数）。
"""
from __future__ import annotations

import json
import os

import numpy as np

# ---------------------------------------------------------------- 常数
KCL_THEORY_US = 1415.0        # 0.01 mol·dm⁻³ KCl 的验收标准值 μS·cm⁻¹（参考报告口径）
KCL_TOLERANCE = 5.0
C_STD = 1000.0                # 标准浓度 c° / mol·m⁻³

# 25 ℃ 离子极限摩尔电导率（CRC Handbook，S·m²·mol⁻¹；参考报告引用值）
LAMBDA_ION = {
    'H': 0.034965,
    'Na': 0.005008,
    'Ac': 0.00409,
    'NO3': 0.007142,
}
# 由离子值加和的理论 Λm∞（S·m²·mol⁻¹）
LAMBDA_THEO = {
    'NaNO3': LAMBDA_ION['Na'] + LAMBDA_ION['NO3'],
    'NaAc': LAMBDA_ION['Na'] + LAMBDA_ION['Ac'],
    'HNO3': LAMBDA_ION['H'] + LAMBDA_ION['NO3'],
    'HAc': LAMBDA_ION['H'] + LAMBDA_ION['Ac'],
}
PKA_HAC = 4.756               # CRC，25 ℃
KA_HAC = 10 ** (-PKA_HAC)     # = 1.754×10⁻⁵

SPECIES_LABEL = {'NaNO3': 'NaNO₃', 'NaAc': 'NaAc', 'HNO3': 'HNO₃', 'HAc': 'HAc'}
# 普通文本里的化学式（真下标写法）
CHEM_MARK = {'NaNO3': 'NaNO_{3}', 'NaAc': 'NaAc', 'HNO3': 'HNO_{3}', 'HAc': 'HAc'}

# ---------------------------------------------------------------- 默认数据
DEFAULT_DATA = {
    'temp_c': 21.3,
    'kcl_label_uS': 1401.0,
    'kcl_theory_uS': KCL_THEORY_US,
    'cell_constant_label': 0.970,
    'cell_constant': 0.979,
    'kcl_after_uS': 1415.0,
    'kappa_w_uS': 6.25,
    'compensation': 2.00,       # 仪器温度补偿系数 %/℃
    'solutions': {
        'NaNO3': {'conc': ['25.00', '10.00', '5.000', '2.500', '1.250'],
                  'kappa': ['0.2770', '0.1139', '0.0574', '0.0300', '0.01575']},
        'NaAc': {'conc': ['25.00', '10.00', '5.000', '2.500', '1.250'],
                 'kappa': ['0.1959', '0.0827', '0.0426', '0.0223', '0.01178']},
        'HNO3': {'conc': ['10.00', '5.000', '2.500', '1.000', '0.5000'],
                 'kappa': ['0.4400', '0.2210', '0.1115', '0.0443', '0.0218']},
        'HAc': {'conc': ['25.00', '10.00', '5.000', '2.500', '1.250'],
                'kappa': ['0.0258', '0.01592', '0.01113', '0.00766', '0.00525']},
    },
    # 离子独立运动定律的组合：Λm∞(HAc) = 加项 − 减项
    'combo': {'add': ['NaAc', 'HNO3'], 'sub': ['NaNO3']},
}

DATA_FILENAME = '电导率数据.json'


def load_data(data_dir):
    """读数据 JSON；不存在时先落一份默认数据再返回（便于用户在文件里改）。"""
    path = os.path.join(data_dir, DATA_FILENAME) if data_dir else None
    if path and os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            return _merge(_deep_default(), data), path
        except (OSError, ValueError):
            pass
    data = _deep_default()
    if path:
        try:
            os.makedirs(data_dir, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except OSError:
            path = None
    return data, path


def save_data(data_dir, data):
    path = os.path.join(data_dir, DATA_FILENAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path


def _deep_default():
    return json.loads(json.dumps(DEFAULT_DATA, ensure_ascii=False))


def _merge(base, patch):
    """浅层合并 + solutions 逐键合并，容忍 JSON 里少写字段。"""
    out = _deep_default()
    for k, v in base.items():
        out[k] = v
    for k, v in (patch or {}).items():
        if k == 'solutions' and isinstance(v, dict):
            for sk, sv in v.items():
                if isinstance(sv, dict):
                    out['solutions'].setdefault(sk, {}).update(sv)
                else:
                    out['solutions'][sk] = sv
        elif k == 'combo' and isinstance(v, dict):
            out['combo'].update(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- 基础计算
def _decimals(s):
    """字符串读数的小数位数（'0.01575' → 5）。"""
    s = str(s).strip()
    if '.' in s:
        return len(s.split('.')[-1].rstrip())
    return 0


def sigma_kappa(reading):
    """仪器读数末位不确定度：最后一位取 2（参考报告口径）。"""
    d = _decimals(reading)
    return 2.0 * 10.0 ** (-d)


def to_float(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return float('nan')


def line_fit(x, y):
    """加权?不加权 OLS 直线拟合，返回 k, b, σk, σb, r, n。"""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    n = len(x)
    if n < 3:
        return dict(k=float('nan'), b=float('nan'),
                    sigma_k=float('nan'), sigma_b=float('nan'),
                    r=float('nan'), n=n)
    k, b = np.polyfit(x, y, 1)
    yhat = k * x + b
    resid = y - yhat
    sse = float(np.sum(resid ** 2))
    sxx = float(np.sum((x - x.mean()) ** 2))
    if n > 2 and sxx > 0:
        s = np.sqrt(sse / (n - 2))
        sigma_k = s / np.sqrt(sxx)
        sigma_b = s * np.sqrt(1.0 / n + x.mean() ** 2 / sxx)
    else:
        sigma_k = sigma_b = float('nan')
    sst = float(np.sum((y - y.mean()) ** 2))
    r = float(np.corrcoef(x, y)[0, 1]) if sst > 0 else float('nan')
    return dict(k=float(k), b=float(b), sigma_k=float(sigma_k),
                sigma_b=float(sigma_b), r=r, n=n)


def solution_table(sol, kappa_w):
    """一种溶液的基本处理：c、κ测、κ校、Λm（含读数末位不确定度）。

    kappa_w 是去离子水电导率（S·m⁻¹）。
    """
    conc = [to_float(v) for v in sol['conc']]
    kappa = [to_float(v) for v in sol['kappa']]
    sigma = [sigma_kappa(v) for v in sol['kappa']]
    rows = []
    for c, km, sk in zip(conc, kappa, sigma):
        kc = km - kappa_w
        lam = kc / c if c else float('nan')
        rows.append(dict(c=c, kappa=km, sigma_kappa=sk, kappa_corr=kc, lam=lam))
    return rows


def prepare(data):
    """把数据 JSON 转成计算所需的上下文。返回 dict。"""
    kw_us = to_float(data.get('kappa_w_uS'))
    ctx = dict(
        kappa_w_us=kw_us,
        kappa_w=kw_us * 1e-4,          # μS·cm⁻¹ → S·m⁻¹
        kcl_label=to_float(data.get('kcl_label_uS')),
        kcl_theory=to_float(data.get('kcl_theory_uS')) or KCL_THEORY_US,
        kcl_after=to_float(data.get('kcl_after_uS')),
        cell_label=to_float(data.get('cell_constant_label')),
        cell=to_float(data.get('cell_constant')),
        temp=to_float(data.get('temp_c')),
        compensation=to_float(data.get('compensation')),
    )
    return ctx


# ---------------------------------------------------------------- 强电解质
def kohlrausch(rows):
    """Λm = Λm∞ − B√c 拟合。返回 dict（含 Λm∞ 与其标准误）。"""
    x = [np.sqrt(r['c']) for r in rows]
    y = [r['lam'] for r in rows]
    fit = line_fit(x, y)
    fit['lam_inf'] = fit['b']
    fit['sigma_inf'] = fit['sigma_b']
    fit['x'] = x
    fit['y'] = y
    return fit


def combo_lambda_inf(fits, combo):
    """Λm∞(HAc) = Σ加项 − Σ减项；σ 方和根。"""
    val = 0.0
    var = 0.0
    for key in combo.get('add', []):
        val += fits[key]['lam_inf']
        var += fits[key]['sigma_inf'] ** 2
    for key in combo.get('sub', []):
        val -= fits[key]['lam_inf']
        var += fits[key]['sigma_inf'] ** 2
    return val, float(np.sqrt(var))


def er_percent(exp, theo):
    return (exp - theo) / theo * 100.0


# ---------------------------------------------------------------- 弱电解质
def k_bottle(c, kappa_corr, lam_inf):
    """单个浓度瓶的 α 与 K°。"""
    lam = kappa_corr / c
    alpha = lam / lam_inf
    k = (c / C_STD) * alpha ** 2 / (1.0 - alpha)
    return dict(lam=lam, alpha=alpha, k=k)


def sigma_k_bottle(c, kappa_corr, lam_inf, sigma_kappa, sigma_lam_inf):
    """K° 的不确定度（对 κ校 与 Λm∞ 的偏导，参考报告式）。"""
    den = c * lam_inf ** 2 - kappa_corr * lam_inf
    if den == 0:
        return float('nan')
    d_kappa = kappa_corr * lam_inf * (2 * c * lam_inf - kappa_corr) / den ** 2 / C_STD
    d_lam = -kappa_corr ** 2 * (2 * c * lam_inf - kappa_corr) / den ** 2 / C_STD
    return float(np.sqrt((d_kappa * sigma_kappa) ** 2 + (d_lam * sigma_lam_inf) ** 2))


def k_from_mean(rows, lam_inf, sigma_lam_inf):
    """求平均法：各瓶 K°、σ、平均与合成 σ。"""
    out = []
    for r in rows:
        b = k_bottle(r['c'], r['kappa_corr'], lam_inf)
        b['sigma_kappa'] = r['sigma_kappa']
        b['sigma_k'] = sigma_k_bottle(r['c'], r['kappa_corr'], lam_inf,
                                      r['sigma_kappa'], sigma_lam_inf)
        out.append(b)
    ks = np.array([b['k'] for b in out])
    sigmas = np.array([b['sigma_k'] for b in out])
    mean = float(ks.mean())
    sigma = float(np.sqrt(np.sum(sigmas ** 2)) / len(sigmas))
    return dict(bottles=out, mean=mean, sigma=sigma)


def k_from_fit(rows, lam_inf, sigma_lam_inf):
    """拟合直线法：(c/c°)Λm = (Λm∞)²K°·(1/Λm) − Λm∞K°。"""
    x = [1.0 / r['lam'] for r in rows]
    y = [(r['c'] / C_STD) * r['lam'] for r in rows]
    fit = line_fit(x, y)
    k_val = fit['k'] / lam_inf ** 2
    if np.isfinite(fit['sigma_k']):
        sigma = float(np.sqrt((fit['sigma_k'] / lam_inf ** 2) ** 2
                              + (2 * fit['k'] * sigma_lam_inf / lam_inf ** 3) ** 2))
    else:
        sigma = float('nan')
    fit['K'] = float(k_val)
    fit['sigma_K'] = sigma
    fit['x'] = x
    fit['y'] = y
    return fit
