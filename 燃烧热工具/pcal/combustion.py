# -*- coding: utf-8 -*-
"""
燃烧热实验数据处理核心 —— 与课程软件 Dissolution_Combustion v2.2.4 算法一致。

算法出处（GPL-3.0）：
    北京大学化学与分子工程学院 热力学实验辅助程序 Dissolution-Combustion
    https://github.com/Zhao-Zehua/Dissolution-Combustion
本模块复刻其 maths.py 中的 linear_regression / B_Spline / Reynolds /
calculate_combustion / find_start_end_point，并保留相同的水密度、水热容查表。

单位约定与课程软件一致：温度 K，质量 g，体积 mL，能量 J（除非另注 kJ）。
"""
from __future__ import annotations

import csv
import io
import os

import numpy as np
from scipy import optimize
from scipy.integrate import simpson
from scipy.interpolate import BSpline, splrep

from . import water_properties as wp

# ---------------------------------------------------------------- 物理常数
R_GAS = 8.3144621                 # J/(mol*K)
M_BENZOIC = 122.123               # g/mol  苯甲酸
M_SUCROSE = 342.296               # g/mol  蔗糖
M_GLUCOSE = 180.156               # g/mol  葡萄糖
M_FRUCTOSE = 180.156              # g/mol  果糖

# 讲义给定的恒容燃烧热校正值
Q_NICKEL = -3243.0                # J/g 镍丝
Q_COTTON = -16736.0               # J/g 棉线
Q_IRON = -6694.0                  # J/g 铁丝

# 苯甲酸 -3228.2 kJ/mol（软件默认值，对应恒压燃烧热 -26460 J/g 附近）
BENZOIC_ENTHALPY = -3228.2        # kJ/mol

DX = 0.1                          # 积分/绘图步长（同 main.py）
STD_LIMIT = 0.005                 # 平台期标准差阈值（同课程软件 main.py 的 std_limit）
TIME_LOWER_LIMIT = 30.0           # 平台期最小时间窗口 / s（同 main.py）
TIME_UPPER_LIMIT = 40.0           # 平台期最大时间窗口 / s（同 main.py）

# 不确定度模型（万分之一天平 / 温差仪）
E_BALANCE = 0.0002                # g  仪器允差
E_TEMP = 0.002                    # K  温差仪允差
SQRT3 = np.sqrt(3.0)


# ---------------------------------------------------------------- 数据读取
class CombustionData:
    """一个燃烧热数据文件（课程软件 csv 格式）。"""

    def __init__(self, name, params, t, y, path=None):
        self.name = name
        self.params = params
        self.t = np.asarray(t, dtype=float)
        self.y = np.asarray(y, dtype=float)
        self.path = path
        self.csv = np.stack((self.t, self.y), axis=1)

    def __len__(self):
        return len(self.t)

    @property
    def duration(self):
        return float(self.t[-1] - self.t[0])

    def to_dict(self):
        return {
            'name': self.name,
            'path': self.path,
            'params': self.params,
            'n': len(self.t),
            't': self.t.tolist(),
            'y': self.y.tolist(),
        }


def parse_combustion_csv(text, name='data'):
    """解析课程软件燃烧热数据文件（UTF-8）。"""
    params = {}
    t, y = [], []
    started = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(',')]
        if not started:
            if parts[0].lower().startswith('time'):
                started = True
                continue
            if len(parts) >= 2:
                try:
                    params[parts[0]] = float(parts[1])
                except ValueError:
                    pass
            continue
        if len(parts) >= 2:
            try:
                t.append(float(parts[0]))
                y.append(float(parts[1]))
            except ValueError:
                continue
    if len(t) < 20:
        raise ValueError('数据点太少（%d 个），请检查文件格式是否为课程软件导出的 combustiondata.csv' % len(t))
    return CombustionData(name, params, t, y)


def load_combustion_csv(path):
    with open(path, 'r', encoding='utf-8-sig') as fh:
        text = fh.read()
    return parse_combustion_csv(text, os.path.basename(path))


# ---------------------------------------------------------------- 线性回归
def linear_regression(csv_arr, start, end):
    """闭区间 [start, end] 上的最小二乘直线拟合（同课程软件）。"""
    end = end + 1
    x = csv_arr[start:end, 0]
    y = csv_arr[start:end, 1]

    def equation(xx, k, b):
        return k * xx + b

    popt, pcov = optimize.curve_fit(equation, x, y)
    perr = np.sqrt(np.diag(pcov))
    k, b = popt
    stddev_k, stddev_b = perr
    residuals = y - equation(x, *popt)
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_square = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return k, b, float(stddev_k), float(stddev_b), float(r_square)


# ---------------------------------------------------------------- B 样条
def _b_spline(t, y):
    tk, c, k = splrep(t, y)
    return BSpline(tk, c, k)


# ---------------------------------------------------------------- 雷诺校正
def reynolds(csv_arr, start1, end1, start2, end2, dx=DX):
    """
    等面积雷诺校正（复刻课程软件 maths.Reynolds）。

    原理：对点火前平台 [start1,end1]、点火后平台 [start2,end2] 各作最小二乘直线
    外延；以 B 样条平滑 [end1, start2] 的实测曲线；令竖线 t0 右侧直线与曲线
    围成的面积等于左侧面积，则 t0 处的两条直线值之差即为校正温升。
    """
    k1, b1 = linear_regression(csv_arr, start1, end1)[0:2]
    k2, b2 = linear_regression(csv_arr, start2, end2)[0:2]

    seg = csv_arr[end1:(start2 + 1)]
    x_csv = seg[:, 0]
    y_csv = seg[:, 1]
    smooth = _b_spline(x_csv, y_csv)
    x_smooth = np.arange(x_csv.min(), x_csv.max(), dx)

    def integral_function(x, kk, bb):
        return kk * x + bb - smooth(x)

    k = k2 - k1
    b = b2 - b1
    integral = simpson(integral_function(x_smooth, k2, b2), x_smooth)
    total_integral = integral + 0.5 * k * x_csv.min() ** 2 + b * x_csv.min()

    roots = np.roots([0.5 * k, b, -total_integral])
    real = [float(r.real) for r in roots if abs(r.imag) < 1e-9]
    x0 = None
    for r in real:
        if x_csv.min() <= r <= x_csv.max():
            x0 = r
            break
    if x0 is None:
        raise RuntimeError('雷诺校正点求解失败：等面积方程在数据区间内无实根，请检查拟合区间。')

    s1 = simpson(integral_function(x_smooth[x_smooth <= x0], k1, b1), x_smooth[x_smooth <= x0])
    s2 = simpson(integral_function(x_smooth[x_smooth >= x0], k2, b2), x_smooth[x_smooth >= x0])

    t_left = k1 * x0 + b1
    t_right = k2 * x0 + b2
    return {
        'x0': float(x0),
        'T_left': float(t_left),
        'T_right': float(t_right),
        'dT': float(t_right - t_left),
        'S_left': float(abs(s1)),
        'S_right': float(abs(s2)),
        'k1': float(k1), 'b1': float(b1),
        'k2': float(k2), 'b2': float(b2),
        'smooth': smooth,
        'x_smooth': x_smooth,
    }


def fit_info(csv_arr, start, end):
    k, b, sk, sb, r2 = linear_regression(csv_arr, start, end)
    return {'k1': k, 'b1': b, 'k2': k, 'b2': b,
            'k': k, 'b': b,
            'stddev_k1': sk, 'stddev_b1': sb, 'stddev_k2': sk, 'stddev_b2': sb,
            'stddev_k': sk, 'stddev_b': sb, 'r_square': r2}


# ---------------------------------------------------------------- 自动寻点
def _rise_span(csv_arr, frac=0.40):
    """
    识别主升温区间，返回 (i_before, i_after)：
      i_before —— 曲线开始明显抬升的位置（拟合1 的右端应在它之前）；
      i_after  —— 主升温结束、进入尾部平台的位置（拟合2 的左端应在它之后）。

    frac 取导数相对峰值 0.40：取值过小会把点火前的基线漂移也算作升温
    （数据里 0.5 s 一个点的漂移也能有峰值的 10%），导致升温前的平台窗口被吃掉。
    """
    t, y, ys, dy = _smooth_gradient(csv_arr, seconds=5.0)
    n = len(t)
    peak = float(np.max(dy))
    if not np.isfinite(peak) or peak <= 0:
        return 0, n - 1
    idx = np.where(dy >= frac * peak)[0]
    if idx.size == 0:
        return 0, n - 1
    return int(idx[0]), int(idx[-1])


def _flat_window(csv_arr, lo, hi, win, anchor, quality=0.30):
    """
    在 [lo, hi] 内寻找长 win 的“最平”连续窗口，并让它尽量靠近 anchor。

    quality —— 窗口内极差必须小于 (该区间数据极差 × quality) 才认为足够平；
               找不到这样的窗口时返回靠近 anchor 的窗口。
    """
    t, y, ys, dy = _smooth_gradient(csv_arr, seconds=5.0)
    n = len(t)
    lo = int(np.clip(lo, 0, n - 1))
    hi = int(np.clip(hi, 0, n - 1))
    win = max(8, int(win))
    if hi - lo + 1 < win:
        win = hi - lo + 1
    if win < 8:
        return None
    k = max(3, int(round(win / 12.0)))          # 局部平滑尺度

    best = None
    for s in range(lo, hi - win + 2):
        e = s + win - 1
        seg = ys[s:e + 1]
        flat = float(np.max(seg) - np.min(seg))
        local_slope = abs(float(np.mean(dy[s:e + 1])))
        d = abs((s + e) / 2.0 - anchor)
        score = local_slope / (1.0 + d / 50.0)
        if best is None or score < best[0]:
            nearest = None
            if nearest is None or d < nearest[0]:
                pass
            best = (score, s, e, flat, local_slope)
        if s == lo:
            near = (d, s, e)
        elif d < near[0]:
            near = (d, s, e)
    span = float(np.max(ys[lo:hi + 1]) - np.min(ys[lo:hi + 1])) or 1.0
    if best is not None and best[3] <= quality * span:
        return [best[1], best[2]]
    if near is not None:
        return [near[1], near[2]]
    return [best[1], best[2]] if best else None


def _points_by_anchor(csv_arr, window_seconds=90.0, keep=6.0, lag=6.0):
    """
    平台锚点法（默认，推荐）。

    平台区取两段窗口，并让窗口紧贴升温段：
      · 平台1 —— 升温开始前 keep+window_seconds 到 keep 秒；
      · 平台2 —— 主升温结束 lag 秒后起，长度与平台1 相同。
    窗口贴着升温段取，既落在真正的平台上，又不会拖到指数拖尾深处。
    """
    t, y, ys, dy = _smooth_gradient(csv_arr, seconds=5.0)
    n = len(t)
    dt = float(np.median(np.diff(t))) or 0.5
    win = max(10, int(round(window_seconds / dt)))
    i_b, i_a = _rise_span(csv_arr, 0.40)

    e1 = int(np.searchsorted(t, t[i_b] - keep))
    s1 = int(np.searchsorted(t, t[i_b] - keep - window_seconds))
    s1 = max(0, s1)
    e1 = max(s1 + 8, min(e1, n - 1))

    s2 = int(np.searchsorted(t, t[i_a] + lag))
    e2 = min(n - 1, s2 + win - 1)
    s2 = max(0, min(s2, e2 - 8))
    if e1 <= s1 or e2 <= s2:
        return None
    return [s1, e1, s2, e2]


def _points_by_flat(csv_arr, window_seconds=70.0, lead=55.0, keep=8.0, lag=12.0):
    """
    平段切线法（推荐）。

    对两个平台区各取一段“最平”的连续窗口做线性拟合并外延：
      · 平台1：升温开始之前的尾部若干秒；
      · 平台2：主升温结束之后紧接的一段。
    窗口取短（默认 70 s），避免把指数型拖尾当直线拟合导致外延过量。
    """
    t, y, ys, dy = _smooth_gradient(csv_arr, seconds=5.0)
    n = len(t)
    dt = float(np.median(np.diff(t))) or 0.5
    win = max(10, int(round(window_seconds / dt)))
    i_b, i_a = _rise_span(csv_arr, 0.40)

    e1 = int(np.searchsorted(t, t[i_b] - keep))
    s1 = int(np.searchsorted(t, t[i_b] - keep - lead))
    w1 = _flat_window(csv_arr, max(0, s1), max(0, e1), win,
                      max(0, e1 - win // 2))
    s2 = int(np.searchsorted(t, t[i_a] + lag))
    e2 = min(n - 1, s2 + win - 1)
    w2 = _flat_window(csv_arr, s2, min(n - 1, e2 + win), win,
                      min(n - 1, s2 + win // 2))
    if not w1 or not w2:
        return None
    return [w1[0], w1[1], w2[0], w2[1]]


def find_start_end_point_ex(csv_arr, time_lower_limit=TIME_LOWER_LIMIT,
                            time_upper_limit=TIME_UPPER_LIMIT, std_limit=STD_LIMIT,
                            pairs=2, prefer='software'):
    """
    返回 (取点, 方案名, 警告)。

    prefer:
      'software' —— 课程软件算法（默认）。与你实验时在软件里看到、以及
                    combustion.csv 里记录的 Start/End 完全一致；
      'rise'     —— 升温段法：平台1 取升温前固定时长、平台2 取升温后固定时长。
                    基线漂移把软件算法的平台判据带偏时更稳；
      'anchor'   —— 平台锚点法：两段窗口都紧贴升温段。
    首选方案不可用时自动回退到其它方案。
    """
    n = len(csv_arr)
    if n < 20:
        raise ValueError('数据点太少（%d），无法自动寻点' % n)

    software = _points_by_software(csv_arr, time_lower_limit, time_upper_limit,
                                   std_limit, pairs)
    rise = _points_by_rise(csv_arr)
    anchor = _points_by_anchor(csv_arr)
    slope = _points_by_slope(csv_arr)

    named = {
        'software': ('软件算法（滑动窗口标准差，与课程软件一致）', software),
        'rise': ('升温段法（升温前后各取固定平台）', rise),
        'anchor': ('平台锚点法（窗口紧贴升温段）', anchor),
    }
    order = [prefer] + [k for k in ('software', 'rise', 'anchor') if k != prefer]
    candidates = [named[k] for k in order if k in named]
    candidates.append(('导数法（导数峰值 20%）', slope))

    first_struct = None
    for name, cand in candidates:
        if not cand or not _points_sane(csv_arr, cand):
            continue
        if first_struct is None:
            first_struct = (name, cand)
        try:
            reynolds(csv_arr, *cand)
        except Exception:  # noqa: BLE001
            continue
        warn = ''
        if first_struct[0] != name:
            warn = ('首选方案（%s）给出的区间无法求出雷诺校正点，已改用%s，'
                    '请核对图上高亮区间。' % (first_struct[0], name))
        return list(cand), name, warn
    if first_struct is not None:
        return (list(first_struct[1]), first_struct[0],
                '所选的自动区间无法求出雷诺校正点，请手动拖动端点调整拟合区间。')
    return ([0, max(8, n // 10), int(n * 0.85), n - 1], '兜底区间',
            '未能自动识别升温段，请手动调整拟合区间。')


def find_start_end_point(csv_arr, time_lower_limit=TIME_LOWER_LIMIT,
                         time_upper_limit=TIME_UPPER_LIMIT, std_limit=STD_LIMIT,
                         pairs=2, prefer='software'):
    """
    自动寻找平台期起止点，返回 [Start1, End1, Start2, End2]（数据点下标，闭区间）。

    首选方案见 find_start_end_point_ex 的 prefer 参数；不可用时依次回退到
    「软件算法」「升温段法」「平台锚点法」「导数法」。
    """
    return find_start_end_point_ex(csv_arr, time_lower_limit, time_upper_limit,
                                   std_limit, pairs, prefer)[0]


def _points_by_software(csv_arr, time_lower_limit, time_upper_limit, std_limit, pairs):
    """复刻课程软件 maths.find_start_end_point；结果不可用时返回 None。"""
    n = len(csv_arr)
    standard_deviation = []
    start_index, end_index = 0, 1
    while end_index < n:
        span = csv_arr[end_index][0] - csv_arr[start_index][0]
        if span > time_upper_limit:
            start_index += 1
        elif span < time_lower_limit:
            end_index += 1
        else:
            standard_deviation.append(
                [end_index, float(np.std(csv_arr[start_index:end_index, 1]))])
            end_index += 1

    count = 2 * pairs
    points = [0]
    platform = True
    for index, std in standard_deviation:
        if std <= std_limit and platform is False:
            points.append(index)
            platform = True
            count -= 1
        elif std > std_limit and platform is True:
            points.append(index)
            platform = False
            count -= 1
        if count == 2:
            break
    # 与软件一致：用尾部数据点补足（软件界面把 End 2 补为最后一个数据点）
    while len(points) < 2 * pairs:
        points.append(n - 1)
    return points[:2 * pairs]


def _points_sane(csv_arr, pts):
    """结构合法性：不重叠、不长于数据、区间内有足够多的点。"""
    if not pts or len(pts) != 4:
        return False
    s1, e1, s2, e2 = [int(p) for p in pts]
    n = len(csv_arr)
    if not (0 <= s1 < e1 < s2 < e2 <= n - 1):
        return False
    if (e1 - s1) < 8 or (e2 - s2) < 8:
        return False
    return True


def _smooth_gradient(csv_arr, seconds=5.0):
    t = csv_arr[:, 0]
    y = csv_arr[:, 1]
    dt = float(np.median(np.diff(t))) or 0.5
    w = max(3, int(seconds / dt))
    ys = np.convolve(y, np.ones(w) / w, mode='same')
    return t, y, ys, np.gradient(ys, t)


def _points_by_rise(csv_arr, lo_frac=0.05, hi_frac=0.95,
                    pad_before=40.0, pad_after=60.0):
    """
    升温段法。以“曲线抬升到总升温量 lo_frac / hi_frac 的时间”界定主升温段，
    在其前后各留一段平台用于线性拟合。基线漂移与缓慢升温都能正确处理。
    """
    t, y, ys, dy = _smooth_gradient(csv_arr)
    n = len(t)
    ipk = int(np.argmax(dy))
    base = float(np.median(y[:max(5, ipk // 4)]))
    top = float(np.percentile(ys[ipk:], 95))
    rise = top - base
    if not np.isfinite(rise) or rise <= 0:
        return None
    level_b = base + lo_frac * rise
    level_t = base + hi_frac * rise

    def first_cross(level, start, end):
        for i in range(start, end):
            if ys[i] >= level:
                return i
        return end

    i_b = first_cross(level_b, 0, ipk)
    i_t = first_cross(level_t, ipk, n)

    def at(tt):
        return int(np.clip(np.searchsorted(t, tt), 0, n - 1))

    return [0, at(t[i_b] - pad_before), at(t[i_t] + pad_after), n - 1]


def _points_by_slope(csv_arr, frac=0.2, keep=10.0, lead=60.0, lag=75.0):
    """纯导数法：主升温段 = 导数大于峰值 frac 倍的区间，两侧各留一段平台。"""
    t, y, ys, dy = _smooth_gradient(csv_arr, seconds=4.0)
    n = len(t)
    peak = float(np.max(dy))
    if peak <= 0:
        return [0, max(1, n // 10), int(n * 0.8), n - 1]
    idx = np.where(dy >= frac * peak)[0]
    i0, i1 = int(idx[0]), int(idx[-1])

    def at(tt):
        return int(np.clip(np.searchsorted(t, tt), 0, n - 1))

    return [at(t[i0] - keep - lead), at(t[i0] - keep),
            at(t[i1] + lag), n - 1]


# ---------------------------------------------------------------- 结果计算
def benzoic_qv_per_gram(temperature, enthalpy_kj_per_mol=BENZOIC_ENTHALPY):
    """苯甲酸恒压燃烧热 -> 恒容燃烧热（J/g），同课程软件公式。"""
    return (enthalpy_kj_per_mol * 1000.0 + 0.5 * R_GAS * temperature) / M_BENZOIC


def calc_constant(temperature, water_volume, water_density, water_capacity,
                  cotton_mass, combustible_mass, nickel_before, nickel_after,
                  dT, benzoic_enthalpy=BENZOIC_ENTHALPY,
                  cotton_heat=Q_COTTON, nickel_heat=Q_NICKEL,
                  sample_mass=None):
    """量热计常数 W（J/K）。sample_mass 缺省时取  combustible_mass - cotton_mass。"""
    if sample_mass is None:
        sample_mass = combustible_mass - cotton_mass
    water_total_capacity = water_volume * water_density * water_capacity
    q_cotton = cotton_mass * cotton_heat
    q_nickel = (nickel_before - nickel_after) * nickel_heat
    benzoic_heat = benzoic_qv_per_gram(temperature, benzoic_enthalpy)
    q_benzoic = sample_mass * benzoic_heat
    total = q_cotton + q_nickel + q_benzoic
    constant = -total / dT - water_total_capacity
    return {
        'sample_mass': sample_mass,
        'water_total_capacity': water_total_capacity,
        'Q_cotton': q_cotton,
        'Q_nickel': q_nickel,
        'Q_benzoic': q_benzoic,
        'sum_q': q_cotton + q_nickel,
        'benzoic_qv': benzoic_heat,
        'constant': constant,
    }


def calc_sample(temperature, water_volume, water_density, water_capacity,
                cotton_mass, combustible_mass, nickel_before, nickel_after,
                dT, constant, cotton_heat=Q_COTTON, nickel_heat=Q_NICKEL,
                sample_mass=None):
    """样品恒容燃烧热（J/g，取正值）。"""
    if sample_mass is None:
        sample_mass = combustible_mass - cotton_mass
    water_total_capacity = water_volume * water_density * water_capacity
    q_cotton = cotton_mass * cotton_heat
    q_nickel = (nickel_before - nickel_after) * nickel_heat
    q_x = -q_nickel - q_cotton - (constant + water_total_capacity) * dT
    return {
        'sample_mass': sample_mass,
        'water_total_capacity': water_total_capacity,
        'Q_cotton': q_cotton,
        'Q_nickel': q_nickel,
        'sum_q': q_cotton + q_nickel,
        'Q_total': (constant + water_total_capacity) * dT + q_cotton + q_nickel,
        'Qv_per_gram': q_x / sample_mass,
    }


# ---------------------------------------------------------------- 不确定度
SIGMA_DT = 2.0 * E_TEMP / SQRT3          # 两次温差之差
SIGMA_M_DIFF = np.sqrt(2.0) * E_BALANCE / SQRT3   # 两次称量之差
SIGMA_M_SINGLE = E_BALANCE / SQRT3       # 单次称量


def sigma_dt():
    return float(SIGMA_DT)


def sigma_sum_q(sigma_m_nickel=None, sigma_m_cotton=None,
                nickel_heat=Q_NICKEL, cotton_heat=Q_COTTON):
    smn = SIGMA_M_DIFF if sigma_m_nickel is None else sigma_m_nickel
    smc = SIGMA_M_SINGLE if sigma_m_cotton is None else sigma_m_cotton
    return float(np.sqrt((nickel_heat * smn) ** 2 + (cotton_heat * smc) ** 2))


def sigma_constant(Q_benzoic, sigma_G, sigma_sumq, numerator, dT, sigma_dT_):
    """
    W = -Q_benzoic*G/dT - sumq/dT - D*Cw  （D*Cw 视为常数，无不确定度贡献）
        = -(Q_benzoic*G + sumq)/dT
    取 Q_benzoic（单位质量燃烧热）为精确值。
    numerator = Q_benzoic*G + sumq
    """
    term1 = (Q_benzoic * sigma_G / dT) ** 2
    term2 = (sigma_sumq / dT) ** 2
    term3 = (numerator * sigma_dT_ / dT ** 2) ** 2
    return float(np.sqrt(term1 + term2 + term3))


def sigma_qv(dT, sigma_W, W_plus_DCw, sigma_dT_, sigma_sumq,
             total_heat, sigma_m_sam, m_sam):
    term1 = (dT * sigma_W / m_sam) ** 2
    term2 = (W_plus_DCw * sigma_dT_ / m_sam) ** 2
    term3 = (sigma_sumq / m_sam) ** 2
    term4 = (total_heat * sigma_m_sam / m_sam ** 2) ** 2
    return float(np.sqrt(term1 + term2 + term3 + term4))
