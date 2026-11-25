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
#: 「大气压沸点」的**绝对**下限 /kPa。只靠「与最高压强相差 ≤ATM_NEAR」是不够的：
#: 若这份数据只测到 70 kPa（没测到大气压），最高压强那一点会被当成大气压沸点，
#: 平均值就成了假的大气压沸点。加一条绝对判据后，这种数据只会得到系列点。
ATM_FLOOR = 95.0
SPLIT_DROP = 10.0        # 温度骤降超过这么多 ℃ 视为换了一种液体

#: 判「某一行是不是在气液平衡态上」的残差容差，单位 ln(p/p⊖)。
#:
#: 实测两批数据（2026-11 的 水.csv / 环己烷.csv）：真正的平衡点残差 ≤0.063，
#: 而「检漏阶段没沸腾」「结束通大气后」的读数残差 0.74~2.43，两者差一个量级。
#: 取 0.10 落在空隙里：内点余量 1.6 倍、外点余量 7 倍，都不会误判。
RESID_TOL = 0.10
#: 共识点至少要占全部读数的这个比例，否则**不作剔除、只告警**。
#: 防止「整批数据都不靠谱」时把大半读数当离群点剔掉、还装作算出了结果。
MIN_INLIER_FRAC = 0.6
#: 判「这份数据是哪一支液体」时允许的最大偏差 / K（两支液体沸点相差 19 K 以上）
LIQUID_GUESS_TOL = 12.0

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
#: 采集软件导出的 csv 第一列是**时间**（`13:27:11.033`、`53:03.0`）。
#: 《饱和蒸气压实验在线采集操作说明》原话：「每个数据显示的内容为采集时间，
#: 压力和温度」。旧解析器把这列当第一个数值、`float()` 一失败就 break，
#: 整行被丢掉 —— 2026-11-25 的两份真实 csv（水 / 环己烷）都被读成 **0 行**。
_TIME_RE = re.compile(r'^\d{1,2}:\d{1,2}(?::\d{1,2})?(?:\.\d+)?$')

#: 表头识别：认得 `pressure(KPa)` / `temperature(°C)` / `p /kPa` / `压力` 等写法。
_P_COL_RE = re.compile(r'press|压力|压强|\bp\s*(?:/|\(|$)', re.IGNORECASE)
_T_COL_RE = re.compile(r'temp|温度|℃|°\s*c', re.IGNORECASE)
_KELVIN_RE = re.compile(r'/\s*k\b|开尔文|kelvin', re.IGNORECASE)

#: 两点枚举做共识拟合时最多取多少个锚点（防上千行时 O(n³)）。
MAX_ANCHOR = 60
#: 认定为「一支液体」所需的最小温度展布 / K。真实系列从 50 kPa 测到大气压，
#: 温度跨度 18~22 K；几个挤在同一温度的噪声点展布不足 1 K，靠这条挡掉。
MIN_SPREAD_T = 10.0
#: 被排除的读数占比超过这个值时补一条提示（只提示，不拦截）。
WARN_REJECT_FRAC = 0.4


def _num(cell):
    try:
        v = float(str(cell).strip())
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _column_roles(cells):
    """从一行表头里认出（压强列, 温度列）的下标；认不出返回 None。"""
    texts = [str(c if c is not None else '').strip() for c in cells]
    i_p = i_t = None
    for i, s in enumerate(texts):
        if i_t is None and _T_COL_RE.search(s) and not _KELVIN_RE.search(s):
            i_t = i
        if i_p is None and _P_COL_RE.search(s):
            i_p = i
    if i_t is None:                        # 只有 `t /℃` 这种纯符号表头
        for i, s in enumerate(texts):
            if re.match(r'^t\s*(?:/|\(|$)', s, re.IGNORECASE) \
                    and not _KELVIN_RE.search(s):
                i_t = i
                break
    if i_p is None or i_t is None:
        return None
    return i_p, i_t


def _parse_table(matrix):
    """把「一行行单元格」解析成 ``[[p_kPa, t_℃], …]``。

    三条判据（都是被真实文件逼出来的）：

      1. 有表头就按表头认列（``time, pressure(KPa), temperature(°C)``）；
      2. 没有表头时**跳过时间列**（``13:27:11.033`` 不是数值），取前两个数——
         这是 2025 那批「无表头 p t」xlsx 与粘贴文本的走法；
      3. 认不出的行（表头、空行、说明文字）逐行跳过，不因为一行坏掉就丢掉
         后面全部数据（旧实现是 ``break``，一列时间就全军覆没）。
    """
    rows = []
    roles = None
    for cells in matrix:
        cells = list(cells or ())
        if not any(str(c if c is not None else '').strip() for c in cells):
            continue
        if roles is None:
            found = _column_roles(cells)
            if found is not None:
                roles = found
                continue
        p = t = None
        if roles is not None and len(cells) > max(roles):
            p, t = _num(cells[roles[0]]), _num(cells[roles[1]])
        if p is None or t is None:
            vals = []
            for c in cells:
                if _TIME_RE.match(str(c).strip()):
                    continue               # 时间列，不是实验量
                v = _num(c)
                if v is not None:
                    vals.append(v)
            if len(vals) < 2:
                continue
            p, t = vals[0], vals[1]
        rows.append([float(p), float(t)])
    return rows


def parse_numeric_rows(text):
    """从文本里读 (p, t)：逗号/制表符/分号/空白分隔，带不带表头、带不带时间列都认。"""
    matrix = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        matrix.append([p for p in re.split(r'[,;\t]| {2,}| ', line) if p != ''])
    return _parse_table(matrix)


def parse_workbook(path_or_bytes):
    """读 xlsx：优先按表头里的 pressure / temperature 列认。

    无表头时退回「跳过时间列取前两个数」，兼容 2025 那批
    ``p /kPa, t /℃, T /K, ln(p/100), 1/T`` 的五列处理表（只取前两列）。
    采集软件导出的 excel 第一列是时间（可能是 Excel 时间序列号），
    只能靠**表头**认列，否则时间戳会被当成压强。
    """
    import openpyxl
    if isinstance(path_or_bytes, (bytes, bytearray)):
        wb = openpyxl.load_workbook(io.BytesIO(path_or_bytes), data_only=True)
    else:
        wb = openpyxl.load_workbook(path_or_bytes, data_only=True)
    rows = []
    for ws in wb.worksheets:
        rows.extend(_parse_table([list(r) for r in ws.iter_rows(values_only=True)]))
    return rows


# --------------------------------------------- 把一列读数切成「两支液体」
def _x_y(rows):
    """[p, t] → (1/T, ln(p/p⊖))。非法值让残差变 nan，由调用方过滤。"""
    p = np.array([r[0] for r in rows], float)
    T = np.array([r[1] for r in rows], float) + 273.15
    with np.errstate(divide='ignore', invalid='ignore'):
        return 1.0 / T, np.log(p / P_STD)


def _consensus(rows, tol=RESID_TOL):
    """在这些读数里找**最一致的那条直线**（两点枚举 + 内点计数 + 重拟合）。

    为什么不用「迭代剔最大残差」：那会把真实曲线的两端一点点削掉
    （实测水的 49.92/80.54 与 70.08/89.46 都被判成离群，最后只剩中间五点，
    ΔvapH 从 41.3 掉到 7.8 kJ·mol⁻¹）。真实数据的形态是
    **一条主曲线 + 若干根本不在曲线上的读数**（检漏、未沸腾、通大气），
    两点枚举找最大共识集才对得上。

    返回 ``(mask, {'m','b','r2','A','B','n'})``；找不到返回 ``(None, None)``。
    """
    n = len(rows)
    if n < 3:
        return None, None
    x, y = _x_y(rows)
    good = np.isfinite(x) & np.isfinite(y)
    idx = np.arange(n)
    if int(good.sum()) < 3:
        return None, None
    if n > MAX_ANCHOR:                      # 防 O(n³)：按 x 均匀抽锚点
        order = idx[good][np.argsort(x[good])]
        pick = np.unique(np.linspace(0, order.size - 1, MAX_ANCHOR)
                         .round().astype(int))
        idx = order[pick]
    valid = [(i, x[i], y[i]) for i in idx if good[i]]
    best = None
    for a in range(len(valid)):
        ia, xa, ya = valid[a]
        for b in range(a + 1, len(valid)):
            ib, xb, yb = valid[b]
            if xa == xb:
                continue
            m = (yb - ya) / (xb - xa)
            c = ya - m * xa
            resid = y - (m * x + c)
            inl = np.abs(resid) <= tol
            k = int(inl.sum())
            if k < 3:
                continue
            score = (k, -float(np.abs(resid[inl]).sum()))
            if best is None or score > best[0]:
                best = (score, inl)
    if best is None:
        return None, None
    mask = best[1] & good
    if int(mask.sum()) < 3:
        return None, None
    ols = _ols(x[mask], y[mask])
    if ols is None:
        return None, None
    return mask, {'m': ols['m'], 'b': ols['b'], 'r2': ols['r2'],
                  'A': -ols['m'], 'B': ols['b'], 'n': int(mask.sum())}


def _tb_of(params, p1=P_NORM):
    """由直线参数外推常压沸点；分母/斜率不正则返回 None（不硬造一个负温度）。"""
    if not params:
        return None
    d = params['B'] - math.log(p1 / P_STD)
    if d <= 0 or params['A'] <= 0:
        return None
    tb = params['A'] / d
    return tb if math.isfinite(tb) and tb > 0 else None


def _split_atm(points):
    """一支液体内部：摘出「大气压沸点」平台，其余是变压系列。"""
    if not points:
        return [], []
    p_max = max(p for p, _ in points)
    atm, series = [], []
    for r in points:
        if p_max - r[0] <= ATM_NEAR and r[0] >= ATM_FLOOR:
            atm.append(r)
        else:
            series.append(r)
    return atm, series


def classify_rows(rows, tol=RESID_TOL, lit=None):
    """把一列 (p, t) 读数分成「水」「环己烷」两支，并逐行说明哪些被排除。

    判定不看「温度有没有骤降」—— 那套在真实数据上完全失效：水的第一段是
    20 ℃ 左右**未沸腾**的检漏读数，温度是上升的；环己烷末尾通大气那一行
    温度骤降 22 ℃，会被误判成换液体。改成：

      1. **共识直线**：气液平衡点必然落在同一条 ln(p/p⊖)–1/T 直线上，
         两点枚举找内点最多的那条（容差 RESID_TOL）；
      2. **物理校验**：有效蒸气压曲线必须 A = −斜率 > 0（蒸发吸热）、
         温度展布 ≥ MIN_SPREAD_T K、点数 ≥ 3；
      3. 从剩下的读数里再找**第二条**曲线（另一支液体）；
      4. 两条曲线常压沸点相差 < LIQUID_GUESS_TOL K 时视为同一种液体测了两遍，
         合并成一支（否则 cyclo 那格会装进水的数据）；
      5. 剩下的读数全进 ``rejected``，带残差与原因，界面逐行显示。

    返回 ``{'water': {atm, series}, 'cyclo': {…}, 'rejected': [...],
    'notes': [...], 'lines': [...]}``。
    """
    pts = []
    for r in rows or ():
        try:
            p, t = float(r[0]), float(r[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(p) and math.isfinite(t):
            pts.append([p, t])
    if not pts:
        raise ValueError('没有读到可用的 (p, t) 数据行')

    lit = lit or DEFAULT_LIT
    out = {'water': {'atm': [], 'series': []},
           'cyclo': {'atm': [], 'series': []},
           'rejected': [], 'notes': [], 'lines': []}
    rest = list(range(len(pts)))
    groups = []
    # 一轮最多处理 len(pts) 次：每次要么认下一支液体（groups +1），要么把这簇
    # 读数从 rest 里摘掉继续找。没有这个上限，「认不出」的分支若忘了推进 rest
    # 就会死循环（这类修法最容易引入的死循环）。
    budget = len(pts) + 2
    while len(groups) < 2 and len(rest) >= 3 and budget > 0:
        budget -= 1
        sub = [pts[i] for i in rest]
        mask, params = _consensus(sub, tol)
        if mask is None:
            break
        keep = [i for i, ok in zip(rest, mask) if ok]
        removed = set(keep)
        remaining = [i for i in rest if i not in removed]

        # ---- 物理校验 1：斜率必须为负（ΔvapH > 0）
        if params['A'] <= 0:
            out['notes'].append(
                '有一簇 %d 个读数拟合出的斜率非负（A = %.1f K），不是气液平衡'
                '数据，已排除。' % (len(keep), params['A']))
            rest = remaining
            continue
        # ---- 物理校验 2：温度要拉得开
        spread = max(pts[i][1] for i in keep) - min(pts[i][1] for i in keep)
        if spread < MIN_SPREAD_T:
            out['notes'].append(
                '有 %d 个读数只分布在 %.1f K 的温区内（不足 %.0f K），'
                '不构成一支蒸气压系列，已排除。'
                % (len(keep), spread, MIN_SPREAD_T))
            rest = remaining
            continue
        # ---- 物理校验 3：外推的常压沸点必须落在某支液体的文献值附近
        # 只靠「共线 + 斜率为负 + 温区够宽」挡不住伪直线：环己烷那份数据里
        # 「抽真空到 47.6 kPa 时的 3 个室温检漏读数 + 末尾通大气 1 行」恰好
        # 共线（r2 = 0.99999），外推出的常压沸点却是 333 K —— 与水和环己烷
        # 的 373/354 K 都差 20 K 以上。真实液体的 tb 不会有这么大偏差。
        tb = _tb_of(params)
        if tb is None:
            out['notes'].append(
                '有一簇 %d 个读数外推不出正的常压沸点，已排除。' % len(keep))
            rest = remaining
            continue
        mid = (float(lit['water']['tb']) + float(lit['cyclo']['tb'])) / 2.0
        near = 'water' if tb > mid else 'cyclo'
        gap = abs(tb - float(lit[near]['tb']))
        if gap > LIQUID_GUESS_TOL:
            out['notes'].append(
                '有 %d 个读数虽然共线，但外推的常压沸点为 %.1f K，'
                '与水和环己烷的 %.1f/%.1f K 都不符，'
                '判为未达平衡的读数（多半是检漏或通大气前后的点），已排除。'
                % (len(keep), tb, float(lit['water']['tb']),
                   float(lit['cyclo']['tb'])))
            # ⚠ 这里必须是 continue 而不是 break：容差放大时，最大的一簇完全
            # 可能是一组伪直线（检漏 + 通大气恰好共线）。break 会直接放弃、
            # 把整份数据判成「找不到直线」，而真正的蒸气压曲线还留在 rest 里。
            rest = remaining
            continue
        groups.append({'idx': keep, 'params': params, 'tb': float(tb),
                       'spread': float(spread)})
        rest = remaining

    if not groups:
        detail = ('；'.join(out['notes'][:2]) if out['notes'] else
                  '没有任何一簇读数同时满足「斜率为负、温区 ≥ %.0f K、'
                  '外推沸点接近水和环己烷」' % MIN_SPREAD_T)
        raise ValueError('这些读数里找不到一条像样的 ln(p/p⊖)–1/T 直线。'
                         '判据：至少 3 个点、温度跨度 %.0f K 以上、'
                         '外推的常压沸点接近水（%.1f K）或环己烷（%.1f K）。'
                         '本次读数的诊断：%s'
                         % (MIN_SPREAD_T, float(lit['water']['tb']),
                            float(lit['cyclo']['tb']), detail))

    # ---- 同一种液体测了两遍 → 合并
    if len(groups) == 2:
        t1, t2 = groups[0]['tb'], groups[1]['tb']
        if (t1 is not None and t2 is not None
                and abs(t1 - t2) < LIQUID_GUESS_TOL):
            out['notes'].append(
                '两簇读数的常压沸点只差 %.1f K（< %.0f K），判为同一种液体测了'
                '两遍，已合并到同一支。' % (abs(t1 - t2), LIQUID_GUESS_TOL))
            groups = [{'idx': sorted(groups[0]['idx'] + groups[1]['idx']),
                       'params': groups[0]['params'], 'tb': t1,
                       'spread': max(groups[0]['spread'], groups[1]['spread'])}]

    # ---- 用常压沸点判这是哪一支（水 373 K / 环己烷 354 K）
    mid = (float(lit['water']['tb']) + float(lit['cyclo']['tb'])) / 2.0
    for g in groups:
        if g['tb'] is not None:
            key = 'water' if g['tb'] > mid else 'cyclo'
        else:                              # 外推不出沸点：退用平均温度
            temps = [pts[i][1] for i in g['idx']]
            key = 'water' if float(np.mean(temps)) + 273.15 > mid else 'cyclo'
        if out[key]['atm'] or out[key]['series']:
            key = 'cyclo' if key == 'water' else 'water'
        g['key'] = key
        out['lines'].append({'key': key, 'n': len(g['idx']), 'tb': g['tb'],
                             'spread': g['spread'],
                             'r2': g['params']['r2']})
        atm, series = _split_atm([pts[i] for i in g['idx']])
        out[key]['atm'] = atm
        out[key]['series'] = series

    # ---- 没进任何一支的读数：逐行给出偏离量与原因
    used = set()
    for g in groups:
        used.update(g['idx'])
    x, y = _x_y(pts)
    for i in range(len(pts)):
        if i in used:
            continue
        best = None
        for g in groups:
            prm = g['params']
            r = abs(float(y[i] - (prm['m'] * x[i] + prm['b'])))
            if best is None or r < best[0]:
                best = (r, g['key'])
        why = '既不在水也不在环己烷的平衡线上'
        key = None
        if best is not None:
            key = best[1]
            why = ('偏离%s的平衡线 %.2f（ln p 单位，容差 %.2f）'
                   % ('水' if key == 'water' else '环己烷', best[0], tol))
        out['rejected'].append({
            'p': float(pts[i][0]), 't': float(pts[i][1]),
            # key = 该点最接近哪一支（报告里按液体分别交代取舍时用）
            'key': key,
            'resid': (None if best is None else float(best[0])), 'why': why})
    if out['rejected'] and \
            len(out['rejected']) / float(len(pts)) > WARN_REJECT_FRAC:
        out['notes'].append(
            '共 %d 行里有 %d 行不在平衡线上（%.0f%%），请核对原始读数。'
            % (len(pts), len(out['rejected']),
               100.0 * len(out['rejected']) / len(pts)))
    return out


def split_branches(rows, lit=None):
    """把一列 (p, t) 数据切成水/环己烷两支（只要分支，不看诊断信息）。"""
    c = classify_rows(rows, lit=lit)
    return c['water'], c['cyclo']


def merge_classified(old, new, target='auto'):
    """把一次新导入并到已有数据上。

    这个实验天生要导两次文件：`水.csv` 记动态法的水，`环己烷.csv` 记静态法的
    环己烷。旧实现是**整体替换**，于是第二次导入会把第一支的数据抹掉，
    界面上另一支突然变成空的，而用户只是按顺序导了两个文件。

    合并口径：

      · ``target='auto'``：新数据里哪一支非空就换成哪一支，另一支保留原样；
      · ``target='water' / 'cyclo'``：强制只换指定那一支（用户明确指定时）；
      · 一格都没有的一边不参与合并（别用「空」把已有数据清掉）；
      · 被排除的读数与判断说明按液体分别累积，重复导入时不会把上一份的
        诊断记录一起冲掉。
    """
    old = normalize_data(old)
    new = normalize_data(new)
    out = {'water': {'atm': list(old['water']['atm']),
                     'series': list(old['water']['series'])},
           'cyclo': {'atm': list(old['cyclo']['atm']),
                     'series': list(old['cyclo']['series'])}}
    replaced = []
    for key in ('water', 'cyclo'):
        if target not in ('auto', key):
            continue
        src = new[key]
        if not src['atm'] and not src['series']:
            continue                       # 新数据里这支是空的，不动旧值
        out[key] = {'atm': list(src['atm']), 'series': list(src['series'])}
        replaced.append(key)
    return out, replaced


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
    """一次线性拟合 y = m·x + b，返回参数与其标准误、协方差、R²、点数。

    `cov_mb` 是 Cov(m, b) = −x̄·σ²/S_xx（斜率和截距由同一批点算出，
    两者强相关，不能当独立量）。Tb = A/(B−c) 里 A = −m 与 B = b 同时出现，
    漏掉这项会把 σ_Tb 高估几十倍（相关系数 0.9999 量级）。
    """
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
    cov_mb = -xm * s2 / sxx
    return {'m': m, 'b': b, 'sigma_m': sigma_m, 'sigma_b': sigma_b,
            'cov_mb': cov_mb, 'r2': r2, 'n': int(n)}


def _delta_t(T):
    """温度整体偏高 shift ℃ 对 1/T 的影响是非线性的；复算时直接平移温度。"""
    return T


def fit_liquid(points, p1=P_NORM, shift=0.0):
    """对一支 (p, t) 数据做完整的克氏拟合与热力学量计算。

    points: 全部参与拟合的点（大气压沸点平均值 + 变压系列），[p_kPa, t_℃]。
    shift : 复算时每个温度减去的 ℃ 数（0 = 正常拟合）。

    返回 None 表示数据不足或无有效点；调用方应当把「哪些点被剔除」
    写进 warnings，否则用户只会看到报告里一片「—」。
    """
    if len(points) < 3:
        return None
    p = np.array([r[0] for r in points], float)
    t_c = np.array([r[1] for r in points], float)
    T = t_c + 273.15 - shift
    # p ≤ 0 会让 log 变成 -inf / nan，进而把 A、B、Tb、ΔH、R² 全部污染成 nan，
    # 而原来的 r2 < 0.99 之类判据对 nan 恒为 False，所以一条告警都不会触发。
    # 这里显式剔掉非有限且非正的压强，并把剔除个数交给 upper 层报告。
    ok = np.isfinite(p) & np.isfinite(T) & (p > 0) & (T > 0)
    dropped = int((~ok).sum())
    p, t_c, T = p[ok], t_c[ok], T[ok]
    if len(p) < 3:
        return None
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
    # σ_Tb 的传播：Tb = A/d，d = B − ln(p1/p⊖)。
    #   ∂Tb/∂A = 1/d，∂Tb/∂B = −A/d²
    # A = −m、B = b 出自同一次最小二乘，相关系数 0.99987（水）/0.99981（环己烷），
    # 协方差项 Cov(A,B) = −Cov(m,b) = +x̄·σ²/S_xx 与两个平方项同量级、符号为负，
    # 漏掉它会把 σ_Tb 高估约 48.9 倍（水 3.2359 K vs 真值 0.0662 K）：
    #   旧：(σ_A/d)² + (A·σ_B/d²)²                       → 3.2359 K
    #   新：上式 + 2·(∂Tb/∂A)(∂Tb/∂B)·Cov(A,B)          → 0.0662 K
    # 40 万次 MC（对 A、B 抽带协方差的二元正态）确认 0.0662 K。
    dA = 1.0 / d
    dB = -A / (d ** 2)
    cov_AB = -ols['cov_mb']             # A = −m，所以 Cov(A,B) = −Cov(m,b)
    var_tb = (dA * sigma_A) ** 2 + (dB * sigma_B) ** 2 + 2.0 * dA * dB * cov_AB
    sigma_tb = math.sqrt(max(0.0, var_tb))

    dh_J = A * R_GAS                    # J·mol⁻¹
    sigma_dh_J = sigma_A * R_GAS
    ds = dh_J / tb                      # J·mol⁻¹·K⁻¹
    # Δ_vap S_m = ΔH/Tb = (A·R)/(A/d) = R·d，其中 d = B − ln(p1/p⊖)，
    # 与 A 严格无关（∂ΔS/∂A = 0），所以不确定度只由 σ_B 传播：
    #   σ_ΔS = R·σ_B
    # 以前按 sqrt((σ_ΔH/Tb)² + (ΔH·σ_Tb/Tb²)²) 合成，等于把 Tb = A/d
    # 当成与 A 独立的量，把 σ_ΔS 高估约 70%。
    sigma_ds = R_GAS * sigma_B

    return {
        'A': A, 'sigma_A': sigma_A, 'B': B, 'sigma_B': sigma_B,
        'cov_AB': cov_AB, 'r2': ols['r2'], 'n': ols['n'],
        'tb': tb, 'sigma_tb': sigma_tb,
        'dh_kJ': dh_J / 1000.0, 'sigma_dh_kJ': sigma_dh_J / 1000.0,
        'ds': ds, 'sigma_ds': sigma_ds,
        # 被剔掉的点（p ≤ 0 或温度非正）个数——由上层转成 warnings
        'dropped': dropped,
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


def analyze(data, cfg=None, diag=None):
    """一次完整计算：两支液体 + 全局提示。

    ``diag`` 是 :func:`classify_rows` 的返回值（可选）。传进来时会把
    「哪几行没进拟合、为什么」原样带出去，供界面逐行显示——否则用户只看到
    报告里点数比 csv 少，却不知道少在哪。
    """
    cfg = cfg or {}
    data = normalize_data(data)
    lit = {
        'water': {'tb': float(cfg.get('lit_tb_water') or DEFAULT_LIT['water']['tb']),
                  'dh': float(cfg.get('lit_dh_water') or DEFAULT_LIT['water']['dh'])},
        'cyclo': {'tb': float(cfg.get('lit_tb_cyclo') or DEFAULT_LIT['cyclo']['tb']),
                  'dh': float(cfg.get('lit_dh_cyclo') or DEFAULT_LIT['cyclo']['dh'])},
    }
    result = {'p1': float(cfg.get('p1') or P_NORM), 'trouton': TROUTON,
              'lit': lit, 'warnings': [],
              'rejected': list((diag or {}).get('rejected') or []),
              'import_notes': list((diag or {}).get('notes') or []),
              'lines': list((diag or {}).get('lines') or [])}
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
        # 被剔掉的非法点（p≤0、温度非正）必须显式告警：
        # 否则 log(p) 变成 nan，报告里只印一片「—」，用户分不清是数据错还是程序错。
        if res['fit'] and res['fit'].get('dropped'):
            result['warnings'].append(
                '%s有 %d 个点的压强≤0 或温度非正，已剔除不参与拟合'
                % (spec['name'], res['fit']['dropped']))
        if res['fit'] and not np.isfinite(res['fit']['r2']):
            result['warnings'].append(
                '%s的拟合结果含 NaN，请检查原始数据是否有空值或非正压强'
                % spec['name'])
        if res['fit'] and res['fit']['r2'] < 0.99:
            result['warnings'].append('%s的拟合 R² = %.4f 偏低，请检查数据'
                                      % (spec['name'], res['fit']['r2']))
        # 大气压沸点平台散得太开 = 平行测定不稳定，报告里那个平均值不可信
        atm = res.get('atm') or []
        if len(atm) > 1:
            spread = max(t for _, t in atm) - min(t for _, t in atm)
            if spread > 1.0:
                result['warnings'].append(
                    '%s的 %d 次大气压沸点读数相差 %.1f K（> 1 K），'
                    '平均值可能不代表平衡值，建议核对原始记录'
                    % (spec['name'], len(atm), spread))
        if len(res.get('series') or []) and len(res['series']) < 3:
            result['warnings'].append(
                '%s的变压系列只有 %d 个点，拟合主要靠大气压沸点撑着，'
                '结果仅供参考' % (spec['name'], len(res['series'])))
        # 按液体挂上「被排除的读数」：报告 3.x.1 要写清「原始 N 行里剔了哪几行」
        res['rejected'] = [r for r in result['rejected'] if r.get('key') == key]
        res['dropped_total'] = len(res['rejected'])
        result[key] = res
    for note in result['import_notes']:
        result['warnings'].append(note)
    if result['rejected']:
        result['warnings'].append(
            '导入的原始数据里有 %d 行没有进入任何一支的拟合（多为检漏、'
            '未沸腾或通大气前后的读数），明细见「被排除的读数」卡片。'
            % len(result['rejected']))
    return result


# ---------------------------------------------------------------- JSON 桥
def rows_to_payload(rows):
    return [[float(r[0]), float(r[1])] for r in rows]


def data_to_json(data):
    data = normalize_data(data)
    return json.dumps(data, ensure_ascii=False)


def data_from_json(text):
    return normalize_data(json.loads(text))
