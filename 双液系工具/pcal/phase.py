# -*- coding: utf-8 -*-
"""双液体系（环己烷-乙醇）沸点-成分图实验 —— 数据与计算内核。

分析链条（参照 2025 年报告的做法，讲义《实验四》的数据处理要求）：
  1. 标准工作曲线：称量法配制一系列已知组成的滴瓶，测折射率，
     用二次多项式拟合 n = A·x² + B·x + C（x 为组成变量）；
  2. 离群点判断：学生化残差 |r| > 2 为可疑、|r| > 3 基本可认定；
  3. 沸点测定：每个组成测沸点与气、液两相折射率（各平行两次），
     平行读数分别由工作曲线反推后取平均，得两相组成；
  4. 相图：气相线 / 液相线用参数 B 样条平滑（弧长参数化，避免近垂直
     段的振荡），两支曲线差的最小值处即最低恒沸点；
  5. 误差：由拟合系数的标准差与折射率读数误差传播出组成的标准差。

组成变量由 cfg['composition_mode'] 决定：
  'ratio'（默认）  x = m(乙醇)/m(环己烷)，参照报告口径，二次拟合最优；
  'frac'           x = m(乙醇)/(m(乙醇)+m(环己烷))，讲义字面口径。
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import make_interp_spline

AZEO_SEARCH_PTS = 1500          # 相图曲线加密采样点数
AZEO_EDGE_FRACTION = 0.05       # 恒沸点搜索时两端排除的比例（纯组分端两线重合）


# ---------------------------------------------------------------- 示例数据
def sample_data():
    """2025 年秋季学期同一实验的完整数据（环己烷-乙醇，16 个沸点 + 9 点工作曲线）。

    说明：这是参照报告作者提供的原始数据，仅用于演示与自检；
    自己的数据请在网页上直接修改或点「载入示例数据」后编辑。
    """
    bottles = [
        {'m1': 0.7807, 'm2': 6.1820, 'n': 1.4113},
        {'m1': 1.5107, 'm2': 6.1126, 'n': 1.4014},
        {'m1': 2.3509, 'm2': 6.1955, 'n': 1.3919},
        {'m1': 3.1002, 'm2': 6.2028, 'n': 1.3874},
        {'m1': 3.8917, 'm2': 6.2029, 'n': 1.3750},
        {'m1': 4.7064, 'm2': 6.2577, 'n': 1.3680},
        {'m1': 5.4368, 'm2': 6.1296, 'n': 1.3614},
    ]
    boiling = [
        {'v_ethanol': 20, 'v_cyclohexane': 0, 'n_g': [1.3565, 1.3565],
         'n_l': [1.3564, 1.3566], 'T_c': 78.40, 'p_kpa': 101.8},
        {'v_ethanol': 20, 'v_cyclohexane': 1, 'n_g': [1.3695, 1.3687],
         'n_l': [1.3576, 1.3576], 'T_c': 75.60, 'p_kpa': 101.7},
        {'v_ethanol': 20, 'v_cyclohexane': 2, 'n_g': [1.3776, 1.3780],
         'n_l': [1.3587, 1.3587], 'T_c': 74.23, 'p_kpa': 101.7},
        {'v_ethanol': 20, 'v_cyclohexane': 3, 'n_g': [1.3880, 1.3872],
         'n_l': [1.3605, 1.3610], 'T_c': 70.90, 'p_kpa': 101.7},
        {'v_ethanol': 20, 'v_cyclohexane': 7, 'n_g': [1.3927, 1.3920],
         'n_l': [1.3667, 1.3669], 'T_c': 68.51, 'p_kpa': 101.6},
        {'v_ethanol': 20, 'v_cyclohexane': 10, 'n_g': [1.3947, 1.3950],
         'n_l': [1.3700, 1.3706], 'T_c': 66.96, 'p_kpa': 101.6},
        {'v_ethanol': 20, 'v_cyclohexane': 14, 'n_g': [1.3950, 1.3955],
         'n_l': [1.3760, 1.3756], 'T_c': 66.12, 'p_kpa': 101.6},
        {'v_ethanol': 20, 'v_cyclohexane': 19, 'n_g': [1.3960, 1.3958],
         'n_l': [1.3812, 1.3812], 'T_c': 65.55, 'p_kpa': 101.6},
        {'v_ethanol': 0, 'v_cyclohexane': 20, 'n_g': [1.4203, 1.4203],
         'n_l': [1.4202, 1.4203], 'T_c': 80.13, 'p_kpa': 101.6},
        {'v_ethanol': 0.2, 'v_cyclohexane': 20, 'n_g': [1.4027, 1.4027],
         'n_l': [1.4200, 1.4200], 'T_c': 77.70, 'p_kpa': 101.6},
        {'v_ethanol': 0.4, 'v_cyclohexane': 20, 'n_g': [1.3977, 1.3976],
         'n_l': [1.4198, 1.4198], 'T_c': 73.65, 'p_kpa': 101.5},
        {'v_ethanol': 0.9, 'v_cyclohexane': 20, 'n_g': [1.3969, 1.3963],
         'n_l': [1.4195, 1.4195], 'T_c': 67.73, 'p_kpa': 101.5},
        {'v_ethanol': 1.4, 'v_cyclohexane': 20, 'n_g': [1.3969, 1.3962],
         'n_l': [1.4190, 1.4180], 'T_c': 66.10, 'p_kpa': 101.5},
        {'v_ethanol': 3.4, 'v_cyclohexane': 20, 'n_g': [1.3965, 1.3965],
         'n_l': [1.4110, 1.4110], 'T_c': 65.24, 'p_kpa': 101.5},
        {'v_ethanol': 8.4, 'v_cyclohexane': 20, 'n_g': [1.3966, 1.3962],
         'n_l': [1.3970, 1.3972], 'T_c': 65.06, 'p_kpa': 101.5},
        {'v_ethanol': 13.4, 'v_cyclohexane': 20, 'n_g': [1.3962, 1.3962],
         'n_l': [1.3880, 1.3884], 'T_c': 65.05, 'p_kpa': 101.5},
    ]
    return {
        'note': '示例数据：2025 年秋同一实验的环己烷-乙醇体系原始数据（仅用于演示与自检）',
        'n_cyclohexane': 1.4203,
        'n_ethanol': 1.3565,
        'curve_exclude': [4],          # 工作曲线剔除点（合并序号，从 0 起：0=纯环己烷）
        'curve': bottles,
        'boiling': boiling,
    }


# ---------------------------------------------------------------- 小工具
def _avg(vals):
    vals = [v for v in vals if v is not None and np.isfinite(v)]
    return float(np.mean(vals)) if vals else None


def composition_variable(m1, m2, mode):
    """组成变量：'ratio' → m1/m2；'frac' → m1/(m1+m2)。"""
    m1 = np.asarray(m1, float)
    m2 = np.asarray(m2, float)
    if mode == 'frac':
        tot = m1 + m2
        return np.where(tot > 0, m1 / np.where(tot > 0, tot, 1.0), np.nan)
    return np.where(m2 != 0, m1 / np.where(m2 != 0, m2, 1.0), np.nan)


X_LABEL = {'ratio': '质量比 m(乙醇)/m(环己烷)',
           'frac': '乙醇质量分数 m(乙醇)/(m(乙醇)+m(环己烷))'}


def quadratic_inverse(fit, nv):
    """由折射率反推组成：x = [−B − √(B²−4A(C−n))] / (2A)（取 [0,1] 内的根）。"""
    A, B, C = fit['A'], fit['B'], fit['C']
    disc = B * B - 4.0 * A * (C - nv)
    if A == 0 or disc < 0:
        return np.nan
    x = (-B - np.sqrt(disc)) / (2.0 * A)
    return float(x) if 0.0 <= x <= 1.0 + 1e-9 else np.nan


def _studentized(xs, ns, order=2):
    """逐点学生化残差（剔除该点重拟合的口径，与参照报告一致）。"""
    n = len(xs)
    X = np.column_stack([xs ** k for k in range(order + 1)])
    beta, _, _, _ = np.linalg.lstsq(X, ns, rcond=None)
    e = ns - X @ beta
    H = X @ np.linalg.pinv(X.T @ X) @ X.T
    out = np.zeros(n)
    for i in range(n):
        m = np.ones(n, bool)
        m[i] = False
        if m.sum() <= order + 1:
            out[i] = np.nan
            continue
        bi, _, _, _ = np.linalg.lstsq(X[m], ns[m], rcond=None)
        ei = ns[m] - X[m] @ bi
        si = np.sqrt((ei ** 2).sum() / (m.sum() - order - 1))
        out[i] = e[i] / (si * np.sqrt(max(1e-12, 1.0 - H[i, i])))
    return out, e


# ---------------------------------------------------------------- 工作曲线
def fit_curve(data, cfg):
    """工作曲线：合并纯组分两点 + 滴瓶，二次拟合（可选剔除点）。"""
    mode = cfg.get('composition_mode') or 'ratio'
    x_b = composition_variable([b['m1'] for b in data['curve']],
                               [b['m2'] for b in data['curve']], mode)
    pts = [{'index': 0, 'kind': 'pure_cyc', 'label': '纯环己烷',
            'x': 0.0, 'n': data['n_cyclohexane'], 'm1': None, 'm2': None}]
    for i, b in enumerate(data['curve']):
        pts.append({'index': i + 1, 'kind': 'bottle', 'label': '%d 号瓶' % (i + 1),
                    'x': float(x_b[i]), 'n': b['n'], 'm1': b['m1'], 'm2': b['m2']})
    pts.append({'index': len(data['curve']) + 1, 'kind': 'pure_eth', 'label': '纯乙醇',
                'x': 1.0, 'n': data['n_ethanol'], 'm1': None, 'm2': None})
    exclude = [int(i) for i in (data.get('curve_exclude') or [])]
    exclude_set = {i for i in exclude if 0 <= i < len(pts)}

    xs = np.array([p['x'] for p in pts])
    ns = np.array([p['n'] for p in pts])
    keep = np.array([i for i in range(len(pts)) if i not in exclude_set])

    def _fit(idx):
        c, cov = np.polyfit(xs[idx], ns[idx], 2, cov=True)
        pred = np.polyval(c, xs[idx])
        ss_res = float(((pred - ns[idx]) ** 2).sum())
        ss_tot = float(((ns[idx] - ns[idx].mean()) ** 2).sum())
        se = np.sqrt(np.diag(cov))
        return {'A': float(c[0]), 'B': float(c[1]), 'C': float(c[2]),
                'se_A': float(se[0]), 'se_B': float(se[1]), 'se_C': float(se[2]),
                'r2': 1.0 - ss_res / ss_tot if ss_tot > 0 else float('nan'),
                'n': int(idx.size)}

    fit_all = _fit(np.array(range(len(pts))))
    fit = _fit(keep) if len(keep) >= 4 else fit_all

    resid_all, _ = _studentized(xs, ns)
    resid_keep, _ = _studentized(xs[keep], ns[keep])
    for j, p in enumerate(pts):
        p['resid_all'] = float(resid_all[j])
        p['in_fit'] = j in set(keep.tolist())
        p['resid'] = (float(resid_keep[keep.tolist().index(j)])
                      if j in set(keep.tolist()) else None)

    outliers = [{'index': p['index'], 'label': p['label'], 'r': p['resid_all']}
                for p in pts if np.isfinite(p['resid_all']) and abs(p['resid_all']) > 2.0]
    removed = [{'index': p['index'], 'label': p['label'], 'x': p['x'], 'n': p['n'],
                'resid': p['resid_all']} for p in pts if not p['in_fit']]

    return {'mode': mode, 'x_label': X_LABEL[mode], 'points': pts,
            'fit': fit, 'fit_all': fit_all, 'outliers': outliers,
            'removed': removed, 'exclude': sorted(exclude_set)}


# ---------------------------------------------------------------- 沸点数据
def analyze_boiling(data, cfg, fit):
    """反推每个沸点测量的气、液相组成（平行读数分别反推后取平均）。"""
    rows = []
    for i, b in enumerate(data['boiling']):
        ng = _avg(b.get('n_g'))
        nl = _avg(b.get('n_l'))
        wg_vals = [quadratic_inverse(fit, v) for v in b.get('n_g') or [] if v]
        wl_vals = [quadratic_inverse(fit, v) for v in b.get('n_l') or [] if v]
        wg = float(np.mean([v for v in wg_vals if np.isfinite(v)])) \
            if any(np.isfinite(v) for v in wg_vals) else np.nan
        wl = float(np.mean([v for v in wl_vals if np.isfinite(v)])) \
            if any(np.isfinite(v) for v in wl_vals) else np.nan
        rows.append({
            'index': i,
            'v_ethanol': b.get('v_ethanol'), 'v_cyclohexane': b.get('v_cyclohexane'),
            'n_g': ng, 'n_l': nl, 'wg': wg, 'wl': wl,
            'T_c': b.get('T_c'), 'T_K': (b['T_c'] + 273.15) if b.get('T_c') is not None else None,
            'p_kpa': b.get('p_kpa'),
            'n_g_raw': list(b.get('n_g') or []), 'n_l_raw': list(b.get('n_l') or []),
        })
    return rows


# ---------------------------------------------------------------- 相图与恒沸点
def _branch_curve(w, T):
    """弧长参数化的三次 B 样条，返回加密采样的 (x, T) 数组。"""
    w = np.asarray(w, float)
    T = np.asarray(T, float)
    ok = np.isfinite(w) & np.isfinite(T)
    w, T = w[ok], T[ok]
    order = np.argsort(w, kind='stable')
    w, T = w[order], T[order]
    # 合并几乎重复的 x（加权平均），否则样条节点退化
    ux, ut = [w[0]], [T[0]]
    for xi, ti in zip(w[1:], T[1:]):
        if abs(xi - ux[-1]) < 1e-9:
            ut[-1] = (ut[-1] + ti) / 2.0
        else:
            ux.append(xi)
            ut.append(ti)
    if len(ux) < 4:
        return np.column_stack([ux, ut]) if ux else np.empty((0, 2))
    pts = np.column_stack([ux, ut])
    d = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    try:
        sp = make_interp_spline(d, pts, k=3)
    except ValueError:
        return pts
    s = np.linspace(d[0], d[-1], AZEO_SEARCH_PTS)
    return sp(s)


def _envelope(pts, grid, width):
    """曲线的下包络（每个网格点取窗口内最低 T），窗口外为 NaN。"""
    out = np.full(grid.shape, np.nan)
    for j, g in enumerate(grid):
        m = np.abs(pts[:, 0] - g) < width
        if m.any():
            out[j] = pts[m, 1].min()
    return out


def find_azeotrope(rows):
    """最低恒沸点：气、液两支平滑曲线差的内区最小值处。

    相图上气相线（露点线）除纯组分端与恒沸点外都在液相线（泡点线）上方，
    因此 |T_气 − T_液| 在恒沸点处取极小（两端点处也为 0，搜索时排除两端）。
    """
    V = _branch_curve([r['wg'] for r in rows], [r['T_K'] for r in rows])
    L = _branch_curve([r['wl'] for r in rows], [r['T_K'] for r in rows])
    if V.shape[0] < 4 or L.shape[0] < 4:
        return {'ok': False, 'reason': '有效数据点不足，无法定位恒沸点',
                'vapor_curve': V, 'liquid_curve': L}
    lo = max(V[:, 0].min(), L[:, 0].min())
    hi = min(V[:, 0].max(), L[:, 0].max())
    if hi <= lo:
        return {'ok': False, 'reason': '两相组成范围不重叠', 'vapor_curve': V,
                'liquid_curve': L}
    pad = AZEO_EDGE_FRACTION * (hi - lo)
    grid = np.linspace(lo + pad, hi - pad, 600)
    width = (hi - lo) / 150.0
    diff = np.abs(_envelope(V, grid, width) - _envelope(L, grid, width))
    j = int(np.nanargmin(diff))
    w = float(grid[j])
    T = float(0.5 * (_envelope(V, grid[j:j + 1], width)[0]
                     + _envelope(L, grid[j:j + 1], width)[0]))
    vi = int(V[:, 1].argmin())
    li = int(L[:, 1].argmin())
    return {'ok': True, 'w': w, 'T_K': T, 'gap': float(diff[j]),
            'vapor_min': {'w': float(V[vi, 0]), 'T_K': float(V[vi, 1])},
            'liquid_min': {'w': float(L[li, 0]), 'T_K': float(L[li, 1])},
            'vapor_curve': V, 'liquid_curve': L}


# ---------------------------------------------------------------- 误差传播
def sigma_composition(fit, x, sigma_n=0.0005):
    """由拟合系数与读数误差传播组成的不确定度。

    n = A x² + B x + C 隐函数求导：
      ∂x/∂A = −x²/(2Ax+B)   ∂x/∂B = −x/(2Ax+B)
      ∂x/∂C = −1/(2Ax+B)    ∂x/∂n = 1/(2Ax+B)
    """
    A, B = fit['A'], fit['B']
    seA, seB, seC = fit['se_A'], fit['se_B'], fit['se_C']
    den = 2.0 * A * x + B
    if abs(den) < 1e-12:
        return float('nan'), {}
    parts = {
        'A': abs((-x * x / den) * seA),
        'B': abs((-x / den) * seB),
        'C': abs((-1.0 / den) * seC),
        'n': abs((1.0 / den) * sigma_n),
    }
    total = float(np.sqrt(sum(v * v for v in parts.values())))
    return total, parts


# ---------------------------------------------------------------- 主入口
def analyze(data, cfg):
    warnings = []
    if not data.get('curve'):
        warnings.append('工作曲线没有数据点')
    if not data.get('boiling'):
        warnings.append('沸点测定没有数据点')
    if len(data.get('boiling') or []) < 4:
        warnings.append('沸点测定少于 4 组，相图与恒沸点不可靠')

    curve = fit_curve(data, cfg)
    if curve['fit']['A'] <= 0:
        warnings.append('工作曲线二次项系数 A ≤ 0，反推公式可能失真，请检查数据')
    rows = analyze_boiling(data, cfg, curve['fit'])
    bad = [r for r in rows if not np.isfinite(r['wg']) or not np.isfinite(r['wl'])]
    if bad:
        warnings.append('%d 组沸点数据的折射率超出工作曲线范围（%.4f~%.4f），'
                        '无法反推组成' % (len(bad), data['n_ethanol'], data['n_cyclohexane']))
    azeo = find_azeotrope(rows)
    sigma_n = float(cfg.get('sigma_n') or 0.0005)
    sig = {}
    if azeo.get('ok'):
        sw, parts = sigma_composition(curve['fit'], azeo['w'], sigma_n)
        azeo['sigma_w'] = sw
        azeo['sigma_parts'] = parts
        sig = parts

    lit_w = cfg.get('lit_w')
    lit_T = cfg.get('lit_T_K')
    deviation = None
    lit_x = None
    if azeo.get('ok') and lit_w not in (None, ''):
        # 文献值一律以乙醇质量分数保存，与当前口径换算到同一变量再比较
        wf = float(lit_w)
        lit_x = (wf / (1.0 - wf)) if curve['mode'] == 'ratio' else wf
        deviation = (azeo['w'] - lit_x) / lit_x

    return {'curve': curve, 'rows': rows, 'azeotrope': azeo,
            'sigma_n': sigma_n, 'sigma_parts': sig,
            'lit_w': lit_w, 'lit_x': lit_x, 'lit_T_K': lit_T,
            'deviation': deviation,
            'warnings': warnings,
            'mode': curve['mode'], 'x_label': curve['x_label']}
