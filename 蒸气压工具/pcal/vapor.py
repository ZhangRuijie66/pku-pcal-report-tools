# -*- coding: utf-8 -*-
"""液体饱和蒸气压的测定 —— 数据读取 + 计算内核。

实验分两支：
  动态法（水）  ：改变外压测沸点，p 从约 50 kPa 升到大气压；
  静态法（环己烷）：平衡管等压计，p 从大气压降到约 50 kPa。

处理口径与课程数据的处理表（蒸发热数据处理.xlsx）及 2025 年参考报告一致：
  T/K = t/℃ + 273.15
  y = ln(p/p⊖)（p⊖ = 100 kPa，只为消除量纲）
  y = -A/T + B   →   Δ_vap H_m = A·R，T_b = A/(B - ln(p1/p⊖))，
  Δ_vap S_m = Δ_vap H_m / T_b，不确定度用最小二乘参数标准误传播。
"""
from __future__ import annotations

import io
import json
import math
import re

import numpy as np

R_GAS = 8.314            # J·mol⁻¹·K⁻¹
P_STD = 100.0            # p⊖ / kPa，ln(p/p⊖) 的基准
P_NORM = 101.3           # 常压沸点定义压强 / kPa
ATM_NEAR = 1.5           # 与分支最高压强相差多少 kPa 以内算「大气压沸点」
SPLIT_DROP = 10.0        # 温度骤降超过这么多 ℃ 视为换了一种液体

LIQUIDS = (
    {'key': 'water', 'name': '水', 'method': '动态法',
     'section': '动态法测定水的蒸气压'},
    {'key': 'cyclo', 'name': '环己烷', 'method': '静态法',
     'section': '静态法测定环己烷的蒸气压'},
)

# 默认文献值（参考报告口径）：水 ΔvapH 取 CRC 82~100 ℃ 平均 2279.8 kJ·kg⁻¹
# 换算 41.07 kJ·mol⁻¹；环己烷取 Jochems 1982 的 31.45 kJ·mol⁻¹。
DEFAULT_LIT = {
    'water': {'tb': 373.15, 'dh': 41.07},
    'cyclo': {'tb': 353.9, 'dh': 31.45},
}
TROUTON = 88.0           # J·mol⁻¹·K⁻¹


# ---------------------------------------------------------------- 示例数据
# 来自 蒸发热数据处理.xlsx（2025 年同课程报告的同一批数据）：
# 前 11 行水（升压，最后一行是大气压沸点三次平均），后 11 行环己烷（降压）。
SAMPLE_ROWS = [
    (50.05, 81.93), (55.03, 84.69), (60.20, 87.03), (65.16, 89.08),
    (69.96, 90.93), (75.14, 92.82), (80.05, 94.55), (84.98, 96.19),
    (90.08, 97.60), (95.09, 99.27), (101.08, 100.90),
    (101.13, 80.14), (95.26, 77.95), (88.41, 75.63), (84.50, 74.16),
    (80.60, 72.65), (75.93, 70.81), (70.61, 68.60), (65.21, 66.21),
    (60.68, 64.05), (55.28, 61.34), (50.41, 58.67),
]


def sample_data():
    """示例数据：与处理表逐位一致（水 10 点 + 大气压平均；环己烷同构）。"""
    water, cyclo = split_branches([list(r) for r in SAMPLE_ROWS])
    return {'water': water, 'cyclo': cyclo}


# ---------------------------------------------------------------- 数据解析
def parse_numeric_rows(text):
    """从粘贴的文本里读 (p, t) 数值对：逗号/制表符/空白分隔都认。"""
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
        if len(vals) >= 2 and all(math.isfinite(v) for v in vals[:2]):
            rows.append([vals[0], vals[1]])
    return rows


def parse_workbook(path_or_bytes):
    """读 xlsx（蒸发热数据处理.xlsx 的 5 列格式只取前两列 p、t）。"""
    import openpyxl
    if isinstance(path_or_bytes, (bytes, bytearray)):
        wb = openpyxl.load_workbook(io.BytesIO(path_or_bytes), data_only=True)
    else:
        wb = openpyxl.load_workbook(path_or_bytes, data_only=True)
    rows = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            vals = [v for v in row if isinstance(v, (int, float))
                    and not isinstance(v, bool)]
            if len(vals) >= 2 and all(math.isfinite(float(v)) for v in vals[:2]):
                rows.append([float(vals[0]), float(vals[1])])
    return rows


def split_branches(rows):
    """把一列 (p, t) 数据切成水/环己烷两支。

    判据：温度比上一行骤降超过 SPLIT_DROP ℃ 的行开始是第二种液体
    （水在大气压附近约 100 ℃，环己烷约 80 ℃，同压下温差远大于 10 ℃）。
    每支内部再分出「大气压沸点」（与该支最高压强相差 ≤ ATM_NEAR kPa 的行）。
    """
    pts = [[float(p), float(t)] for p, t in rows if p and t is not None]
    if not pts:
        raise ValueError('没有读到可用的 (p, t) 数据行')
    cut = len(pts)
    for i in range(1, len(pts)):
        if pts[i][1] < pts[i - 1][1] - SPLIT_DROP:
            cut = i
            break
    branches = [pts[:cut], pts[cut:]] if cut < len(pts) else [pts]

    out = []
    for branch in branches:
        if not branch:
            out.append({'atm': [], 'series': []})
            continue
        p_max = max(p for p, _ in branch)
        atm = [r for r in branch if p_max - r[0] <= ATM_NEAR]
        series = [r for r in branch if p_max - r[0] > ATM_NEAR]
        out.append({'atm': atm, 'series': series})
    if len(out) == 1:                       # 只有一支时环己烷留空
        out.append({'atm': [], 'series': []})
    return out[0], out[1]


def normalize_data(data):
    """界面/JSON 里的数据整理成内核格式：每支 {atm: [[p,t]…], series: […]。}"""
    def branch(b):
        out = {'atm': [], 'series': []}
        if not isinstance(b, dict):
            return out
        for key in ('atm', 'series'):
            for r in b.get(key) or []:
                try:
                    p, t = float(r[0]), float(r[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if math.isfinite(p) and math.isfinite(t):
                    out[key].append([p, t])
        return out

    return {'water': branch((data or {}).get('water')),
            'cyclo': branch((data or {}).get('cyclo'))}


# ---------------------------------------------------------------- 统计内核
def _ols(x, y):
    """一次线性拟合 y = m·x + b，返回参数与其标准误、R²、点数。"""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    n = x.size
    if n < 3:
        return None
    xm, ym = x.mean(), y.mean()
    sxx = float(((x - xm) ** 2).sum())
    if sxx <= 0:
        return None
    sxy = float(((x - xm) * (y - ym)).sum())
    m = sxy / sxx
    b = ym - m * xm
    resid = y - (m * x + b)
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - ym) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float('nan')
    s2 = ss_res / (n - 2)
    sigma_m = math.sqrt(s2 / sxx)
    sigma_b = math.sqrt(s2 * (1.0 / n + xm * xm / sxx))
    return {'m': m, 'b': b, 'sigma_m': sigma_m, 'sigma_b': sigma_b,
            'r2': r2, 'n': int(n)}


def _delta_t(T):
    """温度整体偏高 shift ℃ 对 1/T 的影响是非线性的；复算时直接平移温度。"""
    return T


def fit_liquid(points, p1=P_NORM, shift=0.0):
    """对一支 (p, t) 数据做完整的克氏拟合与热力学量计算。

    points: 全部参与拟合的点（大气压沸点平均值 + 变压系列），[p_kPa, t_℃]。
    shift : 复算时每个温度减去的 ℃ 数（0 = 正常拟合）。
    """
    if len(points) < 3:
        return None
    p = np.array([r[0] for r in points], float)
    t_c = np.array([r[1] for r in points], float)
    T = t_c + 273.15 - shift
    y = np.log(p / P_STD)
    x = 1.0 / T
    ols = _ols(x, y)
    if ols is None:
        return None

    A = -ols['m']                       # K
    sigma_A = ols['sigma_m']
    B = ols['b']
    sigma_B = ols['sigma_b']

    d = B - math.log(p1 / P_STD)        # 分母 B − ln(p1/p⊖)
    tb = A / d
    sigma_tb = math.sqrt((sigma_A / d) ** 2 + (A * sigma_B / d ** 2) ** 2)

    dh_J = A * R_GAS                    # J·mol⁻¹
    sigma_dh_J = sigma_A * R_GAS
    ds = dh_J / tb                      # J·mol⁻¹·K⁻¹
    sigma_ds = math.sqrt((sigma_dh_J / tb) ** 2
                         + (dh_J * sigma_tb / tb ** 2) ** 2)

    return {
        'A': A, 'sigma_A': sigma_A, 'B': B, 'sigma_B': sigma_B,
        'r2': ols['r2'], 'n': ols['n'],
        'tb': tb, 'sigma_tb': sigma_tb,
        'dh_kJ': dh_J / 1000.0, 'sigma_dh_kJ': sigma_dh_J / 1000.0,
        'ds': ds, 'sigma_ds': sigma_ds,
        # 画图 / 表 3 用的逐点数据（按 1/T 从小到大）
        'points': sorted(
            [{'p': float(pi), 't': float(ti), 'T': float(Ti),
              'lnp': float(yi), 'x': float(xi)}
             for pi, ti, Ti, yi, xi in zip(p, t_c, T, y, x)],
            key=lambda r: r['x']),
    }


def analyze_liquid(branch, cfg, lit):
    """一支数据 → 报告需要的全部量（含大气压沸点行与温度偏移复算）。"""
    atm = sorted(branch['atm'], key=lambda r: -r[0])
    series = list(branch['series'])
    atm_avg = None
    fit_points = [list(r) for r in series]
    if atm:
        atm_avg = {'p': float(np.mean([r[0] for r in atm])),
                   't': float(np.mean([r[1] for r in atm]))}
        fit_points.append([atm_avg['p'], atm_avg['t']])

    fit = fit_liquid(fit_points, p1=cfg.get('p1', P_NORM))
    shift_cfg = float(cfg.get('shift_check') or 0.0)
    shift = None
    if fit and shift_cfg > 0:
        refit = fit_liquid(fit_points, p1=cfg.get('p1', P_NORM),
                           shift=shift_cfg)
        if refit:
            shift = {'shift': shift_cfg, 'fit': refit}

    out = {
        'atm': atm, 'atm_avg': atm_avg, 'series': series,
        'fit': fit, 'shift': shift,
        'lit': lit, 'trouton': TROUTON,
    }
    if fit and lit:
        out['rel_tb'] = (fit['tb'] - lit['tb']) / lit['tb'] * 100.0
        out['rel_dh'] = (fit['dh_kJ'] - lit['dh']) / lit['dh'] * 100.0
        out['ds_minus_trouton'] = fit['ds'] - TROUTON
    return out


def analyze(data, cfg=None):
    """一次完整计算：两支液体 + 全局提示。"""
    cfg = cfg or {}
    data = normalize_data(data)
    lit = {
        'water': {'tb': float(cfg.get('lit_tb_water') or DEFAULT_LIT['water']['tb']),
                  'dh': float(cfg.get('lit_dh_water') or DEFAULT_LIT['water']['dh'])},
        'cyclo': {'tb': float(cfg.get('lit_tb_cyclo') or DEFAULT_LIT['cyclo']['tb']),
                  'dh': float(cfg.get('lit_dh_cyclo') or DEFAULT_LIT['cyclo']['dh'])},
    }
    result = {'p1': float(cfg.get('p1') or P_NORM), 'trouton': TROUTON,
              'lit': lit, 'warnings': []}
    for spec in LIQUIDS:
        key = spec['key']
        branch = data[key]
        res = analyze_liquid(branch, cfg, lit[key])
        res.update({'key': key})
        res.update({k: spec[k] for k in ('name', 'method', 'section')})
        if not branch['series'] and not branch['atm']:
            result['warnings'].append('%s还没有数据（从「数据」卡片导入 xlsx/csv 或手工输入）'
                                      % spec['name'])
        elif not res['fit']:
            result['warnings'].append('%s的数据点不足 3 个，无法拟合' % spec['name'])
        if res['fit'] and res['fit']['r2'] < 0.99:
            result['warnings'].append('%s的拟合 R² = %.4f 偏低，请检查数据'
                                      % (spec['name'], res['fit']['r2']))
        result[key] = res
    return result


# ---------------------------------------------------------------- JSON 桥
def rows_to_payload(rows):
    return [[float(r[0]), float(r[1])] for r in rows]


def data_to_json(data):
    data = normalize_data(data)
    return json.dumps(data, ensure_ascii=False)


def data_from_json(text):
    return normalize_data(json.loads(text))
