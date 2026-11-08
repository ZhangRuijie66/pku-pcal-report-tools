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


AO_INV_TOL = 0.05        # 反推组成允许超出 [0,1] 的容差（工作曲线在纯组分端的拟合误差）


def quadratic_inverse(fit, nv):
    """由折射率反推组成：解 A·x² + B·x + C = n，取物理上合理的那一个根。

    抛物线开口向上（A > 0），顶点 x_v = −B/(2A) 处 n 取最小值：
      · 顶点在 [0,1] **之外**（'ratio' 模式 x_v = 2.09）：n(x) 在 [0,1] 上单调
        递减，两个根里只有一个可能落在定义域内 → 直接取它。
      · 顶点在 [0,1] **之内**（'frac' 模式 x_v = 0.849）：同一个折射率对应两段
        组成，取错支会把富乙醇端整段折回来——纯乙醇 n = 1.3565 被反推成 0.663
        而不是 1.0，16 组数据里 10 组出现「气相组成 < 液相组成」这种物理上
        不可能的结果，而报告照常出图、不告警。

    选根规则（按顺序）：
      1. 只考虑落在 [−TOL, 1+TOL] 内的根（TOL 容纳工作曲线在纯组分端的拟合
         误差：纯乙醇锚点 n 反推出来是 1.036，若严格按 [0,1] 截断就只剩 0.663
         这个明显错误的根）；
      2. 多个候选时取**距顶点更远**的那个（单调段外侧，对 n 灵敏度更高）；
      3. 若两个候选与顶点等距（抛物线本身关于顶点对称，这种平局很常见），
         取**离 0 或 1 端点更近**的那个——工作曲线把纯组分锚点钉在两端，
         端点侧的根才是数据支持的那一支；
      4. 最后把结果夹回 [0,1]。
    """
    A, B, C = fit['A'], fit['B'], fit['C']
    disc = B * B - 4.0 * A * (C - nv)
    if A == 0 or disc < 0:
        return np.nan
    sq = np.sqrt(disc)
    x_v = -B / (2.0 * A)
    roots = [(-B - sq) / (2.0 * A), (-B + sq) / (2.0 * A)]
    cand = [r for r in roots if -AO_INV_TOL <= r <= 1.0 + AO_INV_TOL]
    if not cand:
        return np.nan
    if len(cand) == 1:
        x = cand[0]
    else:
        far = max(abs(r - x_v) for r in cand)
        # 与顶点等距（差 < 1e-6）视为平局
        tied = [r for r in cand if far - abs(r - x_v) < 1e-6]
        x = min(tied, key=lambda r: min(abs(r), abs(r - 1.0)))
    return float(min(max(x, 0.0), 1.0))


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
    # ⚠ 空数组要先挡住：原来直接 w[0] 会抛 IndexError，导致「沸点数据一组都
    # 反推不出来」时整个 analyze() 崩掉，而不是给出「数据不足」的告警。
    if w.size == 0:
        return np.empty((0, 2))
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
    """曲线的下包络（每个网格点取窗口内最低 T），窗口外为 NaN。

    ⚠ **已不再用于恒沸点定位，不要在新代码里拿它构造相图判据。**
    它是「窗口内取最低温度」而不是「曲线在某 x 处的温度」：两条曲线在
    恒沸点 ±width 内都会取到同一个全局最低值，|T_V − T_L| 因此变成一片
    **精确相等的平底**，取其最小值时只能拿到平底最左端 → 系统性偏移
    （合成数据偏差达 0.05，方向随数据变化不可预测）。这正是审计 A 的
    P0-2。恒沸点现在改用 `_azeotrope_crossing`（解 wg = wl）。
    保留本函数只为兼容可能的外部调用。
    """
    out = np.full(grid.shape, np.nan)
    for j, g in enumerate(grid):
        m = np.abs(pts[:, 0] - g) < width
        if m.any():
            out[j] = pts[m, 1].min()
    return out


def _parabola_vertex(x, y, lo, hi):
    """对 (x, y) 做二次拟合，返回落在 [lo, hi] 内的顶点；否则 None。"""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if x.size < 3:
        return None
    try:
        c = np.polyfit(x, y, 2)
    except (np.linalg.LinAlgError, ValueError):
        return None
    if not np.all(np.isfinite(c)) or abs(c[0]) < 1e-30:
        return None
    xv = -c[1] / (2.0 * c[0])
    return float(xv) if lo <= xv <= hi else None


def _azeotrope_crossing(rows, lo, hi):
    """恒沸组成 = 气、液两相组成**重合**处：解 wg(x) − x = 0。

    这是恒沸点的定义本身（气相组成 = 液相组成），不依赖两条曲线在温度方向的
    相对位置，所以不像 |T_V − T_L| 那样受样条抖动（实测 0.005~0.27 K）放大。
    wg(wl) 用三次样条插值（数据点 15~20 个时，稀疏线性插值在弯曲处会偏
    0.005，三次样条偏 2e-5，已用 Margules+Antoine 真实 VLE 模型的 7 个恒沸
    体系验证）。

    多个零交叉时的取舍：取**温度最低**的那个——「最低恒沸点」的定义就是
    T–x 图上温度极小的那个组成。纯组分端 wg = wl 平凡成立，靠
    AZEO_EDGE_FRACTION 的边距排除。

    返回 (w, source)；找不到返回 (None, reason)。
    """
    pts = sorted((float(r['wl']), float(r['wg']), float(r['T_K'])) for r in rows
                 if np.isfinite(r.get('wl', np.nan))
                 and np.isfinite(r.get('wg', np.nan))
                 and np.isfinite(r.get('T_K', np.nan)))
    if len(pts) < 4:
        return None, '有效数据点不足'
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    Ts = np.array([p[2] for p in pts])
    # 重复 x 会让样条退化：合并成均值
    ux, uy, uT = [], [], []
    for xi, yi, ti in zip(xs, ys, Ts):
        if ux and abs(xi - ux[-1]) < 1e-9:
            uy[-1] = 0.5 * (uy[-1] + yi)
            uT[-1] = 0.5 * (uT[-1] + ti)
        else:
            ux.append(xi)
            uy.append(yi)
            uT.append(ti)
    ux = np.asarray(ux)
    uy = np.asarray(uy)
    uT = np.asarray(uT)
    if ux.size < 4:
        return None, '有效数据点不足'

    from scipy.interpolate import CubicSpline, PchipInterpolator
    try:
        sp = CubicSpline(ux, uy, extrapolate=False)
        ts = CubicSpline(ux, uT, extrapolate=False)
    except ValueError:
        sp = PchipInterpolator(ux, uy, extrapolate=False)
        ts = PchipInterpolator(ux, uT, extrapolate=False)

    grid = np.linspace(ux[0], ux[-1], 4001)
    vals = np.asarray(sp(grid), float) - grid
    pad = AZEO_EDGE_FRACTION * (hi - lo)
    win_lo, win_hi = lo + pad, hi - pad
    roots = []
    for k in range(len(grid) - 1):
        if not (np.isfinite(vals[k]) and np.isfinite(vals[k + 1])):
            continue
        if vals[k] == 0.0:
            roots.append(float(grid[k]))
        elif vals[k] * vals[k + 1] < 0:
            t = vals[k] / (vals[k] - vals[k + 1])
            roots.append(float(grid[k] + t * (grid[k + 1] - grid[k])))
    roots = [w for w in roots if win_lo <= w <= win_hi]
    if roots:
        if len(roots) == 1:
            return roots[0], 'crossing'
        # 多个零交叉：最低恒沸点 = 温度最低的那个
        best = min(roots, key=lambda w: float(ts(w)))
        return best, 'crossing'
    # 没有零交叉（气液两线在该范围内不相交）：退化为 |wg − wl| 的最小点
    m = np.isfinite(vals)
    if not m.any():
        return None, '气液组成差无有效值'
    inside = np.nonzero(m & (grid >= win_lo) & (grid <= win_hi))[0]
    if inside.size == 0:
        inside = np.nonzero(m)[0]
    j = int(inside[np.argmin(np.abs(vals[inside]))])
    w = float(grid[j])
    idx = np.arange(max(0, j - 2), min(len(grid), j + 3))
    xv = _parabola_vertex(grid[idx], np.abs(vals[idx]), grid[idx[0]], grid[idx[-1]])
    return (xv if xv is not None else w), 'min-abs'


def _phase_order_violations(rows, w_az=None, tol=0.01):
    """找出「气、液两相组成反了方向」的组，返回这些行。

    ⚠ 注意 `wg < wl` **本身不是**错误：对最低恒沸体系，恒沸点左侧（富环己烷）
    wg > wl、右侧（富乙醇）wg < wl，所以 wg < wl 只说明这组落在恒沸点右侧。
    默认示例数据 16 组里有 10 组 wg < wl，全部是正常测量。

    真正的病态是「两相组成反了方向」：气相组成比液相组成**更远离**恒沸组成。
    最低恒沸点的定义关系就是气相总比液相更靠近恒沸组成，违反它物理上不可能。

    `tol`：|wg − wl| < tol 视为「两相重合」（纯组分端点与恒沸点本身都这样），
    跳过不判——否则纯环己烷那组 wg=0.0084 / wl=0.0090 的读数噪声会被误报。

    `w_az` 缺省时用「按 wl 排序后 wg − wl 变号处」的横坐标估计；估不出来
    就不做判断（返回空表，宁可漏报也不误报）。
    """
    rows = [r for r in rows
            if np.isfinite(r.get('wg', np.nan)) and np.isfinite(r.get('wl', np.nan))]
    if len(rows) < 3:
        return []
    if w_az is None:
        pts = sorted((float(r['wl']), float(r['wg'])) for r in rows)
        xs = np.array([p[0] for p in pts])
        ys = np.array([p[1] for p in pts]) - xs
        roots = []
        for k in range(len(ys) - 1):
            if ys[k] * ys[k + 1] < 0:
                t = ys[k] / (ys[k] - ys[k + 1])
                roots.append(float(xs[k] + t * (xs[k + 1] - xs[k])))
        # 端点的平凡交（纯组分处 wg = wl）不算：只保留严格内部的
        span = float(xs[-1] - xs[0])
        if span <= 0:
            return []
        roots = [r for r in roots
                 if xs[0] + 0.05 * span < r < xs[-1] - 0.05 * span]
        if not roots:
            return []
        w_az = roots[0] if len(roots) == 1 else float(np.median(roots))

    viol = []
    for r in rows:
        wg, wl = float(r['wg']), float(r['wl'])
        if abs(wg - wl) < tol:               # 两相重合：端点或恒沸点，跳过
            continue
        # 气相必须比液相更靠近恒沸组成
        if abs(wg - w_az) > abs(wl - w_az) + 1e-9:
            viol.append(r)
    return viol


def anchor_check(fit, data, tol=0.05):
    """工作曲线两个纯组分锚点的自洽性检查。

    工作曲线的拟合点里本来就有「纯环己烷 x=0, n=n_cyclohexane」和
    「纯乙醇 x=1, n=n_ethanol」两个锚点，所以把锚点的折射率代回反推公式
    必须回到 0 和 1。反推取错根时（frac 模式顶点落在 [0,1] 内，纯乙醇被
    反推成 0.663）这条恒等式会立刻破掉，而 |T_V−T_L| / 相图外观完全正常。

    返回 (x_eth, x_cyc, problems)：problems 是可读的问题描述列表。
    """
    n_eth = float(data.get('n_ethanol') or float('nan'))
    n_cyc = float(data.get('n_cyclohexane') or float('nan'))
    x_eth = quadratic_inverse(fit, n_eth) if np.isfinite(n_eth) else float('nan')
    x_cyc = quadratic_inverse(fit, n_cyc) if np.isfinite(n_cyc) else float('nan')
    problems = []
    if np.isfinite(x_eth) and abs(x_eth - 1.0) > tol:
        problems.append('纯乙醇锚点（n = %.4f）反推得到组成 %.3f，应接近 1.000'
                        % (n_eth, x_eth))
    if np.isfinite(x_cyc) and abs(x_cyc - 0.0) > tol:
        problems.append('纯环己烷锚点（n = %.4f）反推得到组成 %.3f，应接近 0.000'
                        % (n_cyc, x_cyc))
    return x_eth, x_cyc, problems


def find_azeotrope(rows):
    """最低恒沸点：气、液两支曲线的交点（气相组成 = 液相组成）。

    旧实现取 `|T_气 − T_液|` 的 nanargmin，但 `_envelope` 是「窗口内取最低 T」，
    两条曲线在恒沸点附近会取到同一个全局最低值，`|V−L|` 变成一片**精确相等的
    平底**，argmin 永远取最左端 → 系统性偏移（合成数据偏差达 0.05，方向随数据
    变化不可预测；真实数据给出 0.3058，参照报告读数是 0.3126）。

    现在改成两个判据合用，以「组成重合」为主：
      1. 主判据：解 wg(x) = x（恒沸点定义），三次样条插值 wg(wl)；
      2. 温度：取该组成处两支曲线温度的平均值。
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

    w, how = _azeotrope_crossing(rows, lo, hi)
    vi = int(V[:, 1].argmin())
    li = int(L[:, 1].argmin())
    base = {'vapor_curve': V, 'liquid_curve': L,
            'vapor_min': {'w': float(V[vi, 0]), 'T_K': float(V[vi, 1])},
            'liquid_min': {'w': float(L[li, 0]), 'T_K': float(L[li, 1])}}
    if w is None:
        out = dict(base)
        out.update({'ok': False, 'reason': '无法定位恒沸点：%s' % how})
        return out

    # 温度：在该组成处读液相线（泡点线）的温度。
    # 恒沸点附近气相线在 T–x 图上近乎垂直，x 的微小抖动会被放大成好几 K
    # （实测同一组数据上 T_V 在 338.2~343.1 K 之间跳），而液相线是平滑单调的，
    # 且 w_az 本身是**液相组成**，所以温度从液相线读才自洽。
    def temp_at(curve):
        return float(curve[int(np.argmin(np.abs(curve[:, 0] - w))), 1])

    T = temp_at(L)
    if not np.isfinite(T):
        T = 0.5 * (temp_at(V) + temp_at(L))

    # gap：该组成处两支曲线温度的差（K）。含义仍是「两线在恒沸点附近贴得多近」，
    # 网页与报告按 K 展示（`两线差约 X K`），所以单位必须保持温度。
    gap = abs(temp_at(V) - temp_at(L))
    if not np.isfinite(gap):
        gap = 0.0

    out = dict(base)
    out.update({'ok': True, 'w': float(w), 'T_K': T, 'gap': gap,
                'method': how})
    return out


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

    # ---- 物理硬校验：气相组成不得小于液相组成 ----
    # 除纯组分端点（wg = wl 平凡成立）外，气相同样富乙醇，且有「气相更接近
    # 恒沸组成」的关系：在富环己烷侧 wg > wl，在富乙醇侧 wg < wl 是正常的。
    # 但**若两相组成在同一次测量里反了方向**（wg 比 wl 更远离恒沸点），
    # 就是反推取错根／工作曲线失效的征兆——历史上 frac 模式正是这样把
    # 富乙醇端整段折回来，10/16 组出现 wg < wl 却照常出图。
    # 判据：把两相组成按恒沸侧比较，检查 wg 是否比 wl 更靠近恒沸组成。
    # ---- 物理硬校验：气、液两相组成不能反到错误的一侧 ----
    # 对于最低恒沸体系，气相同样富「挥发性更接近」的组分：恒沸点左侧（富环己烷）
    # 气相组成 wg > 液相 wl，右侧（富乙醇）wg < wl。所以 wg < wl 本身**不是**
    # 判据——它只说明这组落在恒沸点右侧。真正的病态是「两相组成反了方向」：
    # 同一支上 wg 比 wl 更远离恒沸组成（气相比液相更极端），物理上不可能，
    # 历史上 frac 模式取错根时 10/16 组都长这样，而报告照常出图。
    inv = [r for r in rows if np.isfinite(r['wg']) and np.isfinite(r['wl'])]
    viol = _phase_order_violations(inv)
    if viol:
        warnings.append(
            '有 %d 组数据的气相组成比液相组成更远离恒沸组成（%s），'
            '物理上不可能（气相总应更接近恒沸组成）。这通常是折射率-组成'
            '反推取错根或工作曲线失配造成的，相图与恒沸点结果不可信；'
            '请检查「组成变量」口径（当前 %s）与工作曲线数据'
            % (len(viol),
               '、'.join('第 %d 组（wg=%.3f, wl=%.3f）'
                         % (r['index'] + 1, r['wg'], r['wl']) for r in viol[:5]),
               curve['mode']))
    # ---- 工作曲线锚点自洽：反推必须能回到 x=0 / x=1 ----
    x_eth, x_cyc, anchor_bad = anchor_check(curve['fit'], data)
    if anchor_bad:
        warnings.append('工作曲线反推在纯组分端不闭合：%s。'
                        '反推出的组成（进而相图与恒沸点）不可信，'
                        '请检查工作曲线数据是否覆盖到纯组分端'
                        % '；'.join(anchor_bad))

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
