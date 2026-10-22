# -*- coding: utf-8 -*-
"""《溶解热的测定》数据处理内核。

算法与课程软件 Dissolution-Combustion（作者赵泽华，GPL-3.0）一致：

    · 等面积雷诺校正（maths.Reynolds）——两段平台各作最小二乘直线外延，
      B 样条平滑过渡段，令竖线两侧所夹面积相等，两条直线在竖线处的差值
      即为校正后的温差；
    · 溶解热（maths.calculate_dissolution）——电热补偿法，

          Q' = I^2 R t            （通电输入的电热，R = (R1+R2)/2）
          Q  = Q' * dT_diss / dT_heat          （式(12)）

      其中 dT_diss 为溶解过程（吸热、温度下降）的校正温差，
      dT_heat 为通电加热过程（温度回升）的校正温差；
    · 积分溶解热（maths.dissolution_heat_regression）——按累加实验，

          n1  = rho*V / 18.015          （溶剂的物质的量）
          n0  = n1 / sum(n2)            （溶剂与溶质的物质的量之比）
          Qs  = sum(Q) / sum(n2)        （积分溶解热，kJ/mol）

      并用经验方程 Qs = Qs0 * a * n0 / (1 + a * n0) 非线性拟合；
    · 微分溶解热 / 微分冲淡热 / 积分冲淡热（maths.dissolution_heat_test）。
"""
from __future__ import annotations

import os

import numpy as np
from scipy import optimize
from scipy.integrate import simpson
from scipy.interpolate import BSpline, splrep

from . import water_properties as wp      # noqa: F401  （水的密度 / 比热容，CRC Handbook）

# ---------------------------------------------------------------- 常数
M_H2O = 18.015                    # g/mol   水的摩尔质量（同课程软件）
M_KNO3 = 101.102                  # g/mol   硝酸钾
DX = 0.1                          # 积分/绘图步长（同课程软件）

# 不确定度：直接给各量的标准差（沿用本课程报告一贯的估计口径）
#   · 电流很稳定，保守估计 σ_I = 0.01 A；
#   · 电阻在实验前后相差约 0.15 Ω（接触电阻使读数偏大），取 σ_R = 0.2 Ω；
#   · 秒表单次计时的反应误差约 0.5 s，通电时间是两次计时之差，σ_t = √2×0.5 = 0.7 s；
#   · 数字温差仪单次测温误差约 0.005 K，一个校正温差是两点相减，σ_ΔT = 2×0.005 = 0.01 K。
SIGMA_CURRENT = 0.01              # A    电流读数
SIGMA_RESISTANCE = 0.2            # Ohm  加热丝电阻
SIGMA_TIME = 0.7                  # s    通电时间差
SIGMA_DT = 0.01                   # K    每个校正温差

E_BALANCE = 0.0002                # g    万分之一分析天平（称量的不确定度）
E_VOLUME = 0.5                    # mL   500 mL 容量瓶（约 0.1%）
E_WATER_DENSITY = 0.0001          # g/mL CRC 水的密度表

SQRT3 = np.sqrt(3.0)


class DissolutionData:
    """一个溶解热数据文件（课程软件「数据记录」模式导出的 csv）。"""

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

    @property
    def dt(self):
        return float(np.median(np.diff(self.t))) if len(self.t) > 1 else 1.0

    def index_at(self, seconds):
        """离给定时刻最近的数据点下标。"""
        return int(np.argmin(np.abs(self.t - float(seconds))))

    def to_dict(self):
        return {'name': self.name, 'path': self.path, 'params': self.params,
                'n': len(self.t)}


def parse_dissolution_csv(text, name='data'):
    """解析课程软件溶解热数据文件（UTF-8）。前 9 行是参数，之后是 t / Delta_T。"""
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
        raise ValueError('数据点太少（%d 个），请检查文件是否为课程软件导出的 '
                         'dissolutiondata-*.csv' % len(t))
    return DissolutionData(name, params, t, y)


def load_dissolution_csv(path):
    with open(path, 'r', encoding='utf-8-sig') as fh:
        text = fh.read()
    d = parse_dissolution_csv(text, os.path.basename(path))
    d.path = path          # 报告要用同名 .png（课程软件导出的雷诺校正图）
    return d


def parse_summary_csv(text):
    """
    读取课程软件在数据目录里导出的 dissolution.csv —— 它记录了每一轮
    用户当时在软件里选定的 6 个取点与全部参数，是复现实验的权威依据。
    返回 {filename(不含扩展名): {'points': [...], 'params': {...}, 'Q': kJ}}。
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return {}
    cols = [c.strip() for c in lines[0].split(',')]
    out = {}
    for line in lines[1:]:
        vals = line.split(',')
        row = dict(zip(cols, [v.strip() for v in vals]))
        name = (row.get('filename') or '').strip()
        if not name:
            continue
        pts = []
        for key in ('Start 1', 'End 1', 'Start 2', 'End 2', 'Start 3', 'End 3'):
            try:
                pts.append(int(float(row.get(key, ''))))
            except (TypeError, ValueError):
                pts = []
                break
        params = {}
        for k in ('room_temperature(K)', 'water_volume(mL)', 'solute_mass(g)',
                  'solute_molarmass(g/mol)', 'R1(Omega)', 'R2(Omega)',
                  't1(s)', 't2(s)', 'current(A)'):
            try:
                params[k] = float(row[k])
            except (KeyError, TypeError, ValueError):
                pass
        rec = {'points': pts or None, 'params': params}
        if row.get('dissolution_heat(kJ)'):
            try:
                rec['Q_kJ'] = float(row['dissolution_heat(kJ)'])
            except ValueError:
                pass
        if row.get('water_density(g/mL)'):
            try:
                rec['water_density'] = float(row['water_density(g/mL)'])
            except ValueError:
                pass
        out[name] = rec
    return out


def load_summary_csv(path):
    with open(path, 'r', encoding='utf-8-sig', errors='replace') as fh:
        return parse_summary_csv(fh.read())


# ---------------------------------------------------------------- 线性回归
def linear_regression(csv_arr, start, end):
    """闭区间 [start, end] 上的最小二乘直线拟合（同课程软件 linear_regression）。"""
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


def _b_spline(t, y):
    tk, c, k = splrep(t, y)
    return BSpline(tk, c, k)


# ---------------------------------------------------------------- 雷诺校正
def reynolds(csv_arr, start1, end1, start2, end2, dx=DX):
    """
    等面积雷诺校正（复刻课程软件 maths.Reynolds）。

    对平台 [start1,end1] 与 [start2,end2] 各作最小二乘直线并外延；
    以 B 样条平滑 [end1, start2] 之间的实测曲线；若竖线 t0 左侧
    （拟合线1 与曲线所夹）面积等于右侧（拟合线2 与曲线所夹）面积，
    则在 t0 处两条直线的值即为校正后的过程前后温度。
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
        raise RuntimeError('雷诺校正点求解失败：等面积方程在数据区间内无实根，'
                           '请检查拟合区间（Start/End）是否取在平台段上。')

    s1 = simpson(integral_function(x_smooth[x_smooth <= x0], k1, b1),
                 x_smooth[x_smooth <= x0])
    s2 = simpson(integral_function(x_smooth[x_smooth >= x0], k2, b2),
                 x_smooth[x_smooth >= x0])

    t_left = k1 * x0 + b1
    t_right = k2 * x0 + b2
    return {
        'x0': float(x0),
        'T_left': float(t_left),
        'T_right': float(t_right),
        'dT': float(abs(t_right - t_left)),
        'signed_dT': float(t_right - t_left),
        'S_left': float(abs(s1)),
        'S_right': float(abs(s2)),
        'k1': float(k1), 'b1': float(b1),
        'k2': float(k2), 'b2': float(b2),
        'smooth': smooth,
        'x_smooth': x_smooth,
    }


def fit_info(csv_arr, start, end):
    k, b, sk, sb, r2 = linear_regression(csv_arr, start, end)
    return {'k': k, 'b': b, 'stddev_k': sk, 'stddev_b': sb, 'r_square': r2,
            'k1': k, 'b1': b, 'k2': k, 'b2': b,
            'stddev_k1': sk, 'stddev_b1': sb,
            'stddev_k2': sk, 'stddev_b2': sb,
            'start': int(start), 'end': int(end)}


# ---------------------------------------------------------------- 自动寻点
def _smooth_gradient(csv_arr, seconds=6.0):
    """按时间窗口平滑后的导数（用于识别溶解段与加热段）。"""
    t, y = csv_arr[:, 0], csv_arr[:, 1]
    dt = float(np.median(np.diff(t))) or 1.0
    w = max(3, int(round(seconds / dt)) | 1)
    kern = np.ones(w) / w
    pad = w // 2
    ys = np.convolve(np.pad(y, pad, mode='edge'), kern, mode='valid')
    return t, y, ys, np.gradient(ys, t)


def _flat_window(csv_arr, lo, hi, win, anchor, quality=0.30):
    """
    在 [lo, hi] 内找长度为 win 的「最平」窗口（对直线拟合的残差标准差最小）。

    与外推距离的权衡（同燃烧热工具的做法）：只要残差标准差不超过最优值
    (1+quality) 倍，就取**离 anchor 最近**的窗口——拟合区间贴着过渡段，
    雷诺校正的直线外推距离才短，结果才稳。
    """
    n = len(csv_arr)
    lo = max(0, int(lo))
    hi = min(n - 1, int(hi))
    if hi - lo + 1 < win:
        win = max(6, hi - lo + 1)
    if hi - lo + 1 < 6:
        return lo
    cands = []
    for s in range(lo, hi - win + 2):
        seg = csv_arr[s:s + win]
        resid = seg[:, 1] - np.polyval(np.polyfit(seg[:, 0], seg[:, 1], 1), seg[:, 0])
        cands.append((s, float(np.std(resid))))
    best = min(c[1] for c in cands)
    tol = best * (1.0 + quality) + 1e-12
    good = [s for s, r in cands if r <= tol]
    return int(min(good, key=lambda s: abs(s - anchor)))


def _transition_span(csv_arr, frac=0.25):
    """返回 (溶解段起止下标, 加热段起止下标)。"""
    t, y, ys, dy = _smooth_gradient(csv_arr, seconds=6.0)
    n = len(t)
    i_min = int(np.argmin(dy))
    i_max = int(np.argmax(dy))
    d_peak, r_peak = dy[i_min], dy[i_max]
    if d_peak >= -1e-9:
        raise RuntimeError('没有检测到溶解导致的降温段，请检查数据文件。')
    if r_peak <= 1e-9:
        raise RuntimeError('没有检测到通电加热导致的升温段，请检查数据文件。')
    drop = np.where(dy <= frac * d_peak)[0]
    rise = np.where(dy >= frac * r_peak)[0]
    rise = rise[rise > i_min]
    if len(rise) == 0:
        raise RuntimeError('升温段识别失败，请手动指定取点。')
    return (int(drop[0]), int(drop[-1])), (int(rise[0]), int(rise[-1]))


def find_start_end_point(csv_arr, heating_start=None, heating_end=None,
                         win_seconds=32.0, lead_seconds=6.0, lag_seconds=10.0):
    """
    自动取 6 个下标 [Start1, End1, Start2, End2, Start3, End3]。

    溶解热曲线有五个阶段：初始基线 → 溶解降温 → 低温平台 → 通电升温 → 终末平台。
    过渡段用平滑导数识别；三个平台段在各自的允许区间内取「最平的窗口」，
    并优先贴近过渡段以缩短雷诺校正的外推距离。加热的开始/结束时刻
    （csv 头里的 t1、t2）用来限定中间平台与终末平台的范围——它们比
    导数阈值可靠得多。
    """
    n = len(csv_arr)
    t = csv_arr[:, 0]
    dt = float(np.median(np.diff(t))) or 1.0
    win = max(8, int(round(win_seconds / dt)))
    lead = max(2, int(round(lead_seconds / dt)))
    lag = max(2, int(round(lag_seconds / dt)))

    (d0, d1), (r0, r1) = _transition_span(csv_arr)

    start1 = 0
    end1 = _flat_window(csv_arr, 0, d0 - lead, win, anchor=d0 - lead)

    if heating_start is not None:
        i_t1 = int(np.argmin(np.abs(t - float(heating_start))))
    else:
        i_t1 = r0
    hi2 = max(end1 + win + 4, i_t1 - lead)
    lo2 = max(end1 + 3, d1 + lag)
    if hi2 - lo2 < 8:                      # 中间平台太窄，退回到过渡段中点的两侧
        mid = (d1 + i_t1) // 2
        lo2, hi2 = max(end1 + 3, mid - win), max(mid, end1 + win + 4)
    start2 = _flat_window(csv_arr, lo2, hi2, win, anchor=hi2)
    end2 = start2 + win - 1

    if heating_end is not None:
        i_t2 = int(np.argmin(np.abs(t - float(heating_end))))
    else:
        i_t2 = r1
    if start2 >= i_t1:                     # 中间平台跑到加热之后了，兜底
        start2 = max(end1 + 3, i_t1 - lead - win)
        end2 = start2 + win - 1
    # 终末平台：记录末尾那段最平直（实验结束前温度已经完全稳定下来），
    # 因此窗口右端固定取最后一个数据点，只在尾部一小段里挑最平的起点。
    last_start = n - 1 - win
    lo3 = min(max(i_t2 + lag, end2 + 3, last_start - win), max(0, last_start))
    start3 = _flat_window(csv_arr, lo3, max(lo3, last_start), win, anchor=last_start)
    end3 = n - 1

    pts = [int(start1), int(end1), int(start2), int(end2), int(start3), int(end3)]
    for a, b in ((0, 1), (2, 3), (4, 5)):
        if pts[b] - pts[a] < 4:
            raise RuntimeError('自动取点失败：平台区间太窄。请手动指定 Start/End。')
    if not (pts[1] < pts[2] < pts[3] < pts[4]):
        raise RuntimeError('自动取点失败：平台顺序不合理，请手动指定 Start/End。')
    return pts


# ---------------------------------------------------------------- 单轮溶解热
def sigma_dT():
    """一个校正温差的标准差（单次测温 0.005 K，两点相减）。"""
    return float(SIGMA_DT)


def sigma_mass():
    """单次称量的标准差（均匀分布）。"""
    return float(E_BALANCE / SQRT3)


def calc_round_dissolution(heating_current, r1, r2, t1, t2,
                           dT_diss, dT_heat):
    """
    式(12)：电热补偿法求一次加入溶质所吸收的热量。

    返回 dict（Q 的单位是 J）。
    """
    R = (float(r1) + float(r2)) / 2.0
    dt_heat = float(t2) - float(t1)
    Q_elec = float(heating_current) ** 2 * R * dt_heat          # J
    Q = Q_elec * float(dT_diss) / float(dT_heat)                # J
    return {'R': R, 't_heat': dt_heat, 'Q_elec': Q_elec, 'Q': Q}


def sigma_Q(current, r1, r2, t1, t2, dT_diss, dT_heat,
            sigma_I=SIGMA_CURRENT, sigma_R=SIGMA_RESISTANCE,
            sigma_t=SIGMA_TIME, sigma_dT_=SIGMA_DT):
    """
    式(12) 的不确定度传播（相对形式）：

        σ_Q/Q = √[(2σ_I/I)² + (σ_R/R)² + (σ_t/Δt)²
                  + (σ_ΔTd/ΔTd)² + (σ_ΔTh/ΔTh)²]

    与本课程报告一贯用的绝对形式
        σ_Q² = (2IRt·r·σ_I)² + (I²t·r·σ_R)² + (I²R·r·σ_t)²
               + (I²Rt·σ_ΔTd/ΔT_h)² + (I²Rt·ΔT_d·σ_ΔTh/ΔT_h²)²
    （r = ΔT_d/ΔT_h）完全等价。
    """
    R = (float(r1) + float(r2)) / 2.0
    dt_heat = float(t2) - float(t1)
    rel = np.sqrt((2.0 * sigma_I / current) ** 2 + (sigma_R / R) ** 2
                  + (sigma_t / dt_heat) ** 2
                  + (sigma_dT_ / dT_diss) ** 2 + (sigma_dT_ / dT_heat) ** 2)
    return float(rel)


def sigma_terms(current, r1, r2, t1, t2, dT_diss, dT_heat,
                sigma_I=SIGMA_CURRENT, sigma_R=SIGMA_RESISTANCE,
                sigma_t=SIGMA_TIME, sigma_dT_=SIGMA_DT):
    """式(12) 各项对 σ_Q 的绝对贡献（J），用于误差分析的表格与文字。"""
    R = (float(r1) + float(r2)) / 2.0
    dt_heat = float(t2) - float(t1)
    Q_elec = float(current) ** 2 * R * dt_heat
    ratio = float(dT_diss) / float(dT_heat)
    Q = Q_elec * ratio
    terms = {
        'I': 2.0 * float(current) * R * dt_heat * ratio * sigma_I,
        'R': float(current) ** 2 * dt_heat * ratio * sigma_R,
        't': float(current) ** 2 * R * ratio * sigma_t,
        'd': Q_elec * sigma_dT_ / float(dT_heat),
        'h': Q_elec * float(dT_diss) * sigma_dT_ / float(dT_heat) ** 2,
    }
    terms['total'] = float(np.sqrt(sum(v ** 2 for k, v in terms.items())))
    terms['Q'] = Q
    return terms


# ---------------------------------------------------------------- 积分溶解热
def fit_integral_heat(rows, water_density, water_volume, water_molar_mass=M_H2O):
    """
    由各次实验的 (solute_mass, Q) 累加求积分溶解热并拟合经验方程。

    rows: [{'solute_mass': g, 'Q': J}, ...]  按实验先后顺序
    返回 dict：n / Qs 数组、拟合参数与标准差、R^2。
    """
    n1 = float(water_density) * float(water_volume) / float(water_molar_mass)
    n0, Qs, cum_m2, cum_Q = [], [], [], []
    sum_n2 = 0.0
    sum_Q = 0.0
    for r in rows:
        sum_n2 += float(r['solute_mass']) / float(r['solute_molar_mass'])
        sum_Q += float(r['Q']) / 1000.0                    # J -> kJ
        cum_m2.append(float(r['solute_mass']) + (cum_m2[-1] if cum_m2 else 0.0))
        cum_Q.append(sum_Q)
        n0.append(n1 / sum_n2)
        Qs.append(sum_Q / sum_n2)
    n0 = np.asarray(n0, dtype=float)
    Qs = np.asarray(Qs, dtype=float)

    def equation(n, Qs0, a):
        return (Qs0 * a * n) / (1.0 + a * n)

    # 用 1/n0 ~ 1/Qs 的线性拟合给非线性拟合初值（同课程软件）
    x = 1.0 / n0
    y = 1.0 / Qs
    k, b = np.polyfit(x, y, 1)[0:2]
    p0 = [1.0 / b, b / k]
    popt, pcov = optimize.curve_fit(equation, n0, Qs, p0=p0)
    perr = np.sqrt(np.diag(pcov))
    Qs0, a = float(popt[0]), float(popt[1])
    s_Qs0, s_a = float(perr[0]), float(perr[1])
    residuals = Qs - equation(n0, *popt)
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((Qs - np.mean(Qs)) ** 2))
    r_square = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return {'n0': n0, 'Qs': Qs, 'n1': n1, 'cum_m2': np.asarray(cum_m2),
            'cum_Q': np.asarray(cum_Q), 'Qs0': Qs0, 'a': a,
            'sigma_Qs0': s_Qs0, 'sigma_a': s_a, 'r_square': float(r_square),
            'equation': equation}


def differential_heats(Qs0, a, n_test=(200, 150, 100, 80, 50)):
    """
    由经验方程求各浓度下的
        积分溶解热   Qs        = Qs0*a*n0/(1+a*n0)              kJ/mol
        微分溶解热   Qs'_n2    = Qs0*(a*n0/(1+a*n0))^2          kJ/mol
        微分冲淡热   Qs'_n0    = Qs0*a/(1+a*n0)^2               J/mol
        积分冲淡热   Qd        = |Qs(n0_i) - Qs(n0_{i-1})|      J/mol
    """
    n_test = np.asarray(n_test, dtype=float)
    Qs = (Qs0 * a * n_test) / (1.0 + a * n_test)
    Qs_d2 = Qs0 * (a * n_test / (1.0 + a * n_test)) ** 2
    Qs_d1 = Qs0 * a / (1.0 + a * n_test) ** 2 * 1000.0
    Qd = np.abs(np.diff(Qs)) * 1000.0
    return {'n0': n_test, 'Qs': Qs, 'Qs_n2': Qs_d2, 'Qs_n0': Qs_d1, 'Qd': Qd}
