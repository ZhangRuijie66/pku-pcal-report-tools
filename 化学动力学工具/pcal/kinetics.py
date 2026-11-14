# -*- coding: utf-8 -*-
"""化学反应动力学探究（蔗糖水解）—— 数据模型与计算内核。

数据来源：Polariputer 动态测量导出的 xlsx（列：index, time, steps, angle），
或两列文本（t / α）。处理链：

    旋光度–浓度标定  α = k c + b
    α∞：实验值（反应完全后的静态测量）或由比旋光度计算的理论值
    各级反应尝试：α–t（零级）、ln(α−α∞)–t（一级）、1/(α−α∞)–t（二级）
    k1 = −slope，t1/2 = ln2/k1
    k1 = k0 + kH c(H+)ⁿ 非线性拟合 → 氢离子反应级数 n
    lg(k1−k0) = lg kH + n lg c(H+) 线性拟合作验证
"""
from __future__ import annotations

import math
import re
import warnings as warnings_

import numpy as np
from scipy.optimize import curve_fit
from scipy.stats import linregress, t as tdist

R = 8.314462618

# 比旋光度（20 ℃，D 线）与摩尔质量
M_SUC = 342.296
M_GLU = 180.156
M_FRU = 180.156
A_SUC = 66.6
A_GLU = 52.5
A_FRU = -91.9


# ---------------------------------------------------------------- 示例数据
def sample_data():
    """2025 年同一课程实验的完整数据（蔗糖水解，5 个盐酸浓度）。"""
    groups = [
        ('6M', 6.0, 3.015, [], [
            (131.879, 2.27748), (155.137, 2.077748), (181.226, 1.878016),
            (208.723, 1.678284), (235.204, 1.478552), (288.11, 1.143432),
            (323.607, 0.9437), (360.284, 0.743968), (407.267, 0.544236),
            (459.517, 0.344504), (518.806, 0.144772), (589.378, -0.05496),
            (677.614, -0.254692), (795.812, -0.454424), (965.083, -0.654155),
            (1345.004, -0.853887)]),
        ('5M', 5.0, 2.490, [], [
            (146.863, 2.510724), (165.113, 2.310992), (203.478, 2.11126),
            (249.067, 1.911528), (295.371, 1.711796), (345.438, 1.512064),
            (401.104, 1.312332), (464.345, 1.112601), (530.932, 0.912869),
            (605.491, 0.713137), (686.27, 0.513405), (776.663, 0.313673),
            (889.526, 0.113941), (1010.072, -0.085791), (1150.225, -0.285523),
            (1341.744, -0.485255), (1592.234, -0.684987)]),
        ('4M', 4.0, 2.000, [], [
            (128.157, 2.872654), (185.364, 2.672922), (231.041, 2.47319),
            (280.302, 2.273458), (333.815, 2.073727), (393.097, 1.873995),
            (453.561, 1.674263), (516.791, 1.474531), (585.186, 1.274799),
            (662.682, 1.075067), (748.129, 0.875335), (835.616, 0.675603),
            (946.033, 0.475871), (1071.823, 0.276139), (1213.772, 0.076408),
            (1390.677, -0.123324), (1604.966, -0.323056), (1915.627, -0.522788)]),
        ('3M', 3.0, 1.530, [], [
            (126.022, 2.969169), (201.518, 2.769437), (275.33, 2.569705),
            (347.684, 2.369973), (429.968, 2.170241), (518.456, 1.970509),
            (613.441, 1.770777), (710.579, 1.571046), (810.815, 1.371314),
            (924.522, 1.171582), (1047.007, 0.97185), (1175.64, 0.772118),
            (1334.024, 0.572386), (1505.209, 0.372654), (1689.674, 0.172922)]),
        ('2M', 2.0, 1.000, [5], [
            (140.855, 3.097855), (270.178, 2.898123), (403.39, 2.698391),
            (581.793, 2.49866), (761.599, 2.298928), (916.558, 2.099196),
            (1157.552, 1.899464), (1277.793, 1.798928), (1387.552, 1.698391),
            (1512.296, 1.597855), (1637.881, 1.497319), (1753.8, 1.396783)]),
    ]
    return {
        'temperature_c': 30.0,
        'sucrose_stock': 0.050,       # 配制的蔗糖溶液 g·mL⁻¹，混合后 1:1 稀释
        'alpha_inf_measured': -1.10,
        'calibration': [
            {'c': 0.0050, 'alpha': 0.87}, {'c': 0.0104, 'alpha': 1.51},
            {'c': 0.0250, 'alpha': 3.45}, {'c': 0.0504, 'alpha': 6.88},
            {'c': 0.0814, 'alpha': 11.11}, {'c': 0.100, 'alpha': 12.08},
            {'c': 0.120, 'alpha': 16.25}, {'c': 0.150, 'alpha': 20.60},
        ],
        'calibration_exclude': [5],
        'groups': [
            {'label': lab, 'acid_nominal': nom, 'acid_true': true,
             'alpha_inf': None, 'exclude': list(ex),
             'data': [[t, a] for t, a in pts]}
            for lab, nom, true, ex, pts in groups
        ],
    }


# ---------------------------------------------------------------- 解析
def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_numeric_rows(text):
    rows = []
    for line in str(text or '').replace('\r', '').split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [p for p in re.split(r'[,;\t ]+', line) if p]
        vals = []
        ok = True
        for p in parts:
            v = _to_float(p)
            if v is None:
                ok = False
                break
            vals.append(v)
        if ok and vals:
            rows.append(vals)
    return rows


# ---------------------------------------------------------------- 读数文件识别
#
# Polariputer 导出两种 xlsx，**列结构完全不同**，必须按列名区分：
#
#   动态测量：index, time,  steps, angle, …, 实验参数 → 时间序列 [[t, α], …]
#   静态测量：index, steps, angle             → 同一份样品的重复读数
#
# 2026-11-10 用户报过一个静默错数：把静态文件（无穷.xlsx 等）导入标定表时，
# 旧的 `parse_calibration_xlsx` 走「找不到 c/alpha 表头就取前两列数字」的兜底，
# 于是 **index 被当成浓度 c、steps 被当成角度 α**（steps=−3292 印成 α=−3292°）；
# `parse_polariputer_xlsx` 也把静态文件按 `[r[1], r[-1]]` 解析成 [steps, angle]。
# 两份报告都"正常"生成，数字全错而不报错——正是本项目最难发现的那类缺陷。
#
# 现在的口径：**先认列名，再决定语义**；认不出来就明确报错，绝不按列序号猜。

#: 动态测量（有时间列）
KIND_DYNAMIC = 'dynamic'
#: 静态测量（同一份样品重复读 angle，没有时间列）
KIND_STATIC = 'static'
#: c–α 标定表（同时有浓度列与角度列）
KIND_CALIB = 'calibration'
#: 认不出列名（或缺列）
KIND_UNKNOWN = 'unknown'

KIND_LABEL = {KIND_DYNAMIC: '动态测量（α–t 时间序列）',
              KIND_STATIC: '静态测量（重复读数）',
              KIND_CALIB: '旋光度–浓度标定表',
              KIND_UNKNOWN: '无法识别的读数文件'}

#: 表头词元 → 字段。一律先 _norm_head() 归一化再比（去单位、去空格、小写）。
_HEAD_TOKENS = {
    'time': ('time', 't', '时间', 'time/s', 't/s', '秒', 'elapsed'),
    'angle': ('angle', 'alpha', 'α', '旋光度', '旋光角', 'angle/°',
              'alpha/°', '角度'),
    'steps': ('steps', 'step', '步数', '步进', '步进数', '步进角数'),
    'index': ('index', '序号', '#', 'no', 'no.', '编号', 'i'),
    'c': ('c', 'c_suc', 'csuc', '浓度', '蔗糖浓度', 'c/g·ml-1'),
}


def _norm_head(value):
    """表头单元格归一化：``α/(°)`` → ``α``、``Time / s`` → ``time``。

    去掉括号里的单位（不同软件版本写法不一致），去空格，转小写。
    """
    s = str(value if value is not None else '').strip().lower()
    s = s.replace('（', '(').replace('）', ')')
    s = re.sub(r'\([^)]*\)', '', s)          # 去掉单位括号
    s = s.replace(' ', '').replace('\u00a0', '')
    # ``c / (g·mL⁻¹)`` 去掉括号后残留 ``c/``，要再剥一层尾部分隔符才对得上词元表
    return s.rstrip(':：/-·')


def _header_fields(row):
    """一行表头 → ``{字段: 列号}``；认不出任何字段时返回 ``{}``。"""
    out = {}
    for j, cell in enumerate(row or ()):
        key = _norm_head(cell)
        if not key:
            continue
        for field, tokens in _HEAD_TOKENS.items():
            if field in out:
                continue
            if key in tokens:
                out[field] = j
                break
    return out


def _read_xlsx_rows(source):
    """打开 xlsx（路径 / 字节流 / 文件对象）并返回第一个 sheet 的全部行。"""
    import io

    import openpyxl

    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    try:
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
    finally:
        wb.close()
    return rows


def _stats(values):
    """重复读数的统计量。n=1 时 sd/sem 为 0（不编造离散度）。"""
    vals = [float(v) for v in (values or []) if v is not None]
    n = len(vals)
    if not n:
        return {'mean': None, 'sd': None, 'sem': None, 'n': 0, 'values': []}
    mean = sum(vals) / n
    if n > 1:
        var = sum((v - mean) ** 2 for v in vals) / (n - 1)
        sd = math.sqrt(var)
        sem = sd / math.sqrt(n)
    else:
        sd = sem = 0.0
    return {'mean': mean, 'sd': sd, 'sem': sem, 'n': n, 'values': vals}


#: 文件名里出现这些词说明它**不是**一份带浓度的样品文件，别猜浓度
_NO_C_WORDS = ('无穷', 'alpha∞', '完全反应', '去离子水', '水', '零点',
               '空白', 'water', 'blank', 'inf')

#: 名字里的单位片段——先剥掉再数数字，否则 ``蔗糖0.05g L-1`` 会被
#: 当成「0.05 和 1 两个数字」而拒绝猜浓度（那正是最典型的样品文件名）。
#: 长的写在前面，``g·ml-1`` 必须先于 ``ml`` 被剥掉。
_UNIT_TOKENS = (
    'g·ml⁻¹', 'g·ml-1', 'g ml-1', 'g/ml', 'g·l⁻¹', 'g·l-1', 'g l-1',
    'gl-1', 'g/l', 'mol·dm⁻³', 'mol·dm-3', 'mol dm-3', 'mol/l', 'mol·l⁻¹',
    'mol·l-1', 'mol l-1',
    'g', 'ml', 'l⁻¹', 'l-1', 'm',
)


def concentration_hint(stem):
    """从文件名猜浓度（g·mL⁻¹）——**只在唯一且明确时**返回，否则 None。

    静态测量文件里没有浓度列，浓度只写在文件名上（``0.0412.xlsx``、
    ``蔗糖0.05g L-1.xlsx``）。猜错会静默改掉整条标定直线，所以判据很严格：

      · 先剥掉单位片段（``g L-1``、``g·mL⁻¹``、``mL`` …），再数剩下几个数字；
      · 文件名里必须**恰好只有一个**数字（``0.15-2``、``1.4927-50ml`` 有两个 → 不猜）；
      · 该数字落在 (0, 0.5] g·mL⁻¹ 的合理区间；
      · 文件名不含「无穷 / 完全反应 / 去离子水 / 零点」这类**非样品**词。
    """
    text = str(stem or '')
    low = text.lower()
    if any(w.lower() in low for w in _NO_C_WORDS):
        return None
    for tok in _UNIT_TOKENS:
        low = low.replace(tok, ' ')
    nums = re.findall(r'\d+(?:\.\d+)?', low)
    if len(nums) != 1:
        return None
    try:
        val = float(nums[0])
    except ValueError:
        return None
    if not (0.0 < val <= 0.5):
        return None
    return val


def _meta_from_rows(rows):
    """从「实验参数」侧栏取温度/浓度等元信息（与列位置无关）。"""
    meta = {'temperature': None, 'sucrose': None, 'acid': None,
            'zero': None, 'step_angle': None, 'n_points': None}
    names = {'temperature': ('实验温度', '温度'), 'sucrose': ('蔗糖浓度',),
             'acid': ('盐酸浓度', '酸浓度'), 'zero': ('初始旋光角',),
             'step_angle': ('步进角',), 'n_points': ('采样点数',)}
    for row in rows:
        for j, cell in enumerate(row or ()):
            if not isinstance(cell, str):
                continue
            key = cell.strip()
            for field, wanted in names.items():
                if meta[field] is not None:
                    continue
                if not any(w == key or w in key for w in wanted):
                    continue
                for x in row[j + 1:]:
                    val = _to_float(x)
                    if val is not None:
                        meta[field] = val
                        break
    return meta


def parse_measurement_xlsx(source, stem=None):
    """xlsx 统一解析入口：按**列名**判定是动态、静态还是标定表。

    返回 dict：

    ============ ==========================================================
    ``kind``     KIND_DYNAMIC / KIND_STATIC / KIND_CALIB / KIND_UNKNOWN
    ``points``   动态测量的 [[t, α], …]（其它类型为空）
    ``alpha``    静态测量的 ``{mean, sd, sem, n, values}``（其它类型为 None）
    ``rows``     标定表的 ``[{c, alpha, n}]``（其它类型为空）
    ``steps``    静态测量的步数统计（诊断用，不参与计算）
    ``c_hint``   文件名里唯一明确的浓度候选，否则 None
    ``stem``     文件名（不含扩展名），报错/界面提示用
    ``warnings`` 解析过程中的可读提示
    ============ ==========================================================

    ⚠ **没有任何按列序号的兜底**：认不出含 angle 的表头就返回 KIND_UNKNOWN。
    宁可让用户看到「这个文件的表头认不出来」，也不要按 ``r[1], r[-1]``
    猜成 [steps, angle] 把步数当角度。
    """
    rows = _read_xlsx_rows(source)
    out = {'kind': KIND_UNKNOWN, 'points': [], 'alpha': None, 'rows': [],
           'steps': None, 'c_hint': None, 'stem': stem or '',
           'warnings': []}
    out.update(_meta_from_rows(rows))
    if stem:
        out['c_hint'] = concentration_hint(stem)
    if not rows:
        out['warnings'].append('文件里没有任何行')
        return out

    hi, fields = None, {}
    for i, row in enumerate(rows[:12]):
        f = _header_fields(row)
        if 'angle' in f or 'time' in f:
            hi, fields = i, f
            break
    if hi is None:
        out['warnings'].append(
            '找不到含 time / angle 的表头行，无法判断这是动态测量还是静态读数')
        return out

    body = rows[hi + 1:]

    # ---- 1) 有时间列 → 动态测量
    if 'time' in fields and 'angle' in fields:
        ti, ai = fields['time'], fields['angle']
        bad = 0
        for row in body:
            if len(row) <= max(ti, ai):
                bad += 1
                continue
            t, a = _to_float(row[ti]), _to_float(row[ai])
            if t is None or a is None:
                bad += 1
                continue
            out['points'].append([t, a])
        if out['points']:
            out['kind'] = KIND_DYNAMIC
            if bad:
                out['warnings'].append('%d 行的 time/angle 不是数字，已跳过' % bad)
        else:
            out['warnings'].append('表头含 time / angle，但没有解析出任何数据点')
        return out

    # ---- 2) 同时有浓度列与角度列 → 标定表
    if 'c' in fields and 'angle' in fields:
        ci, ai = fields['c'], fields['angle']
        for row in body:
            c = _to_float(row[ci]) if len(row) > ci else None
            a = _to_float(row[ai]) if len(row) > ai else None
            if c is not None and a is not None:
                out['rows'].append({'c': c, 'alpha': a, 'n': 1, 'sd': None})
        out['kind'] = KIND_CALIB if out['rows'] else KIND_UNKNOWN
        if not out['rows']:
            out['warnings'].append('表头含 c / angle，但没有解析出任何成对数据')
        return out

    # ---- 3) 只有角度列（可能带 steps / index）→ 静态重复读数
    if 'angle' in fields:
        ai = fields['angle']
        vals = []
        for row in body:
            if len(row) <= ai:
                continue
            a = _to_float(row[ai])
            if a is not None:
                vals.append(a)
        if not vals:
            out['warnings'].append('表头含 angle，但角度列没有数字')
            return out
        out['kind'] = KIND_STATIC
        out['alpha'] = _stats(vals)
        if 'steps' in fields:
            si = fields['steps']
            steps = [v for v in ((_to_float(row[si]) if len(row) > si else None)
                                 for row in body) if v is not None]
            if steps:
                out['steps'] = _stats(steps)
        return out

    out['warnings'].append('表头只有 time 列、没有 angle 列，无法读取旋光度')
    return out


def parse_static_text(text):
    """纯文本的静态重复读数：每行一个角度（或 ``序号 角度``）。

    返回与 ``parse_measurement_xlsx`` 的 ``alpha`` 同结构的 dict；
    没有任何数字时返回 ``None``。
    """
    vals = []
    for line in str(text or '').replace('\r', '').split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [p for p in re.split(r'[,;\t ]+', line) if p]
        nums = [_to_float(p) for p in parts]
        nums = [v for v in nums if v is not None]
        if not nums:
            continue
        # 两列且第一列是 1,2,3… 的序号 → 取第二列；否则取最后一个数
        if len(nums) >= 2 and float(nums[0]).is_integer() and 0 < nums[0] < 1e4:
            vals.append(nums[-1])
        else:
            vals.append(nums[-1])
    return _stats(vals) if vals else None


def parse_points(text):
    """把文本解析成 [[t, α], ...]。

    支持：两列 t/α；三列 index,t,α；四列 index,t,steps,angle；
    也支持带表头的文件（表头含 time / angle / alpha）。

    ⚠ 只有**明确含 time 列**的表头才按列名取；没有 time 列时按列数推断，
    但会先检查表头里有没有 steps——有 steps 而没有 time 说明这是**静态读数**，
    按 ``r[1], r[-1]`` 取会把步数当成时间，直接返回空让上层报错。
    """
    lines = [ln.strip() for ln in str(text or '').replace('\r', '').split('\n')
             if ln.strip() and not ln.strip().startswith('#')]
    if not lines:
        return []
    header = [p.lower() for p in re.split(r'[,;\t ]+', lines[0]) if p]
    ti = ai = None
    has_steps = False
    for i, h in enumerate(header):
        if h in _HEAD_TOKENS['time']:
            ti = i
        if h in _HEAD_TOKENS['angle']:
            ai = i
        if h in _HEAD_TOKENS['steps']:
            has_steps = True
    if ai is not None and ti is None and has_steps:
        # 静态读数（index, steps, angle）：不能当时间序列
        return []
    data_lines = lines[1:] if (ti is not None or ai is not None) else lines
    rows = parse_numeric_rows('\n'.join(data_lines))
    out = []
    for r in rows:
        if ti is not None and ai is not None and len(r) > max(ti, ai):
            out.append([r[ti], r[ai]])
        elif len(r) == 2:
            out.append([r[0], r[1]])
        elif len(r) == 3:
            out.append([r[1], r[2]])
        elif len(r) >= 4:
            out.append([r[1], r[-1]])
    return out


def parse_calibration(text):
    rows = parse_numeric_rows(text)
    return [{'c': r[0], 'alpha': r[1], 'n': 1, 'sd': None}
            for r in rows if len(r) >= 2]


def parse_calibration_xlsx(source):
    """读 c–α 标定表 xlsx；**只认 c/浓度 + angle 表头**。

    认不出来时返回 ``[]``（上层会明确报错），不再按「前两列数字」兜底——
    那个兜底把静态文件的 index 当浓度、steps 当角度，是 2026-11-10 那个
    静默错数的直接原因。静态读数请走 :func:`parse_measurement_xlsx`。
    """
    res = parse_measurement_xlsx(source)
    return res['rows'] if res['kind'] == KIND_CALIB else []


def parse_polariputer_xlsx(source):
    """读取 Polariputer 动态测量 xlsx。

    source 可以是路径或文件对象/字节流。返回
    ``{'points': [[t, α], ...], 'temperature': float|None,
       'sucrose': float|None, 'kind': ..., 'alpha': ..., 'warnings': [...]}``。

    ⚠ 静态测量文件（只有 steps/angle，没有 time）**不再**被当成时间序列：
    此时 ``points`` 为空、``kind == KIND_STATIC``、``alpha`` 带重复读数统计，
    调用方必须按类型分流（见 server._import）。
    """
    res = parse_measurement_xlsx(source)
    return {'points': res['points'], 'temperature': res['temperature'],
            'sucrose': res['sucrose'], 'acid': res['acid'],
            'kind': res['kind'], 'alpha': res['alpha'], 'rows': res['rows'],
            'c_hint': res['c_hint'], 'warnings': res['warnings']}


# ---------------------------------------------------------------- 拟合
def _line_fit(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if x.size < 2:
        return None
    res = linregress(x, y)
    yhat = res.slope * x + res.intercept
    resid = y - yhat
    dof = x.size - 2
    s_err = math.sqrt(float(np.sum(resid ** 2)) / dof) if dof > 0 else float('nan')
    # 归一化残差（相对标准误）：把 s_err 除以因变量自身的量级，使它可以在
    # **不同线性化**之间横向比较。三种级数的因变量分别是 α、ln(α−α∞)、
    # 1/(α−α∞)，量级差几个数量级，直接比 s_err 或 R² 都不公平：
    #   0 级残差 std = 2.65e-01（y 均值 1.09），1 级 = 1.21e-02（y 均值 0.73）
    #   绝对残差差 22 倍，但相对残差只差 15 倍——R² 更把它们压成 0.927 vs 0.9996。
    ybar = abs(float(np.mean(y))) if y.size else float('nan')
    s_rel = (s_err / ybar) if (ybar and math.isfinite(ybar)) else float('nan')
    ci = None
    if dof > 0 and x.size >= 3:
        xbar = float(np.mean(x))
        sxx = float(np.sum((x - xbar) ** 2))
        if sxx > 0:
            tval = float(tdist.ppf(0.975, dof))
            xx = np.linspace(float(x.min()), float(x.max()), 120)
            half = tval * s_err * np.sqrt(1.0 / x.size + (xx - xbar) ** 2 / sxx)
            yy = res.slope * xx + res.intercept
            ci = dict(x=list(map(float, xx)), lo=list(map(float, yy - half)),
                      hi=list(map(float, yy + half)))
    return dict(slope=float(res.slope), intercept=float(res.intercept),
                sigma_slope=float(res.stderr or 0.0),
                sigma_intercept=float(res.intercept_stderr or 0.0),
                r2=float(res.rvalue ** 2), n=int(x.size),
                s_err=s_err, s_rel=s_rel, y_mean=float(np.mean(y)) if y.size else float('nan'),
                x=list(map(float, x)), y=list(map(float, y)),
                ci=ci)


def _order_y(alpha, alpha_inf, order):
    a = np.asarray(alpha, float)
    if order == 0:
        return a
    d = a - float(alpha_inf)
    if order == 1:
        y = np.full_like(d, np.nan)
        ok = d > 0
        y[ok] = np.log(d[ok])
        return y
    if order == 2:
        y = np.full_like(d, np.nan)
        ok = d != 0
        y[ok] = 1.0 / d[ok]
        return y
    raise ValueError('order must be 0/1/2')


#: 标称酸浓度 → 实际 c(H⁺) 的默认换算系数。
#: 盐酸母液经稀释/混合后浓度减半（与前端「c₀ = 母液浓度 / 2」同源），
#: 2025 课程数据实测 0.498~0.510，取 0.5。界面上可以改。
ACID_RATIO_DEFAULT = 0.5


def acid_ratio_of(cfg):
    """从配置里取换算系数；缺失/非法时退回默认值。"""
    try:
        v = float((cfg or {}).get('acid_ratio'))
    except (TypeError, ValueError):
        return ACID_RATIO_DEFAULT
    if not (v > 0) or not math.isfinite(v):
        return ACID_RATIO_DEFAULT
    return v


def effective_acid(nominal, true, ratio):
    """这一组的实际 c(H⁺)，以及它是怎么来的。

    返回 ``(value, source)``，source ∈ 'measured' / 'nominal' / 'missing'：

    · 手填了 ``acid_true`` → 用它（**永不覆盖**，那是核过实验条件的值）；
    · 只填了 ``acid_nominal`` → 按 ``ratio`` 换算；
    · 两个都没有 → None，由上层给警告（不静默当 0 参与拟合）。
    """
    def _ok(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) else None

    t = _ok(true)
    if t is not None:
        return t, 'measured'
    n = _ok(nominal)
    if n is not None:
        try:
            r = float(ratio)
            if r > 0 and math.isfinite(r):
                return n * r, 'nominal'
        except (TypeError, ValueError):
            pass
    return None, 'missing'


def _fit_group(group, alpha_inf_used, ratio=None):
    pts = []
    for i, p in enumerate(group.get('data') or []):
        if len(p) >= 2:
            t, a = _to_float(p[0]), _to_float(p[1])
            if t is not None and a is not None:
                pts.append((i, t, a))
    exclude = set(int(i) for i in (group.get('exclude') or []))
    use = [(t, a) for i, t, a in pts if i not in exclude]
    t = np.array([p[0] for p in use], float)
    a = np.array([p[1] for p in use], float)
    fits = {}
    for order in (0, 1, 2):
        y = _order_y(a, alpha_inf_used, order)
        fits[str(order)] = _line_fit(t, y)
    first = fits['1']
    k1 = sigma_k1 = t_half = sigma_t_half = float('nan')
    alpha0_fit = float('nan')
    if first and first['slope'] < 0:
        k1 = -first['slope']
        sigma_k1 = first['sigma_slope']
        t_half = math.log(2.0) / k1
        sigma_t_half = math.log(2.0) / (k1 ** 2) * sigma_k1
        alpha0_fit = alpha_inf_used + math.exp(first['intercept'])
    acid_eff, acid_src = effective_acid(
        group.get('acid_nominal'), group.get('acid_true'), ratio)
    return dict(label=group.get('label'), acid_nominal=group.get('acid_nominal'),
                acid_true=group.get('acid_true'),
                acid_eff=acid_eff, acid_source=acid_src,
                alpha_inf=alpha_inf_used,
                exclude=sorted(exclude), data=[[float(x), float(y)] for x, y in use],
                all_data=[[float(t), float(a)] for _, t, a in pts],
                n=len(use), fits=fits,
                k1=k1, sigma_k1=sigma_k1, t_half=t_half,
                sigma_t_half=sigma_t_half, alpha0_fit=alpha0_fit)


def _rate_law(cH, k):
    cH = np.asarray(cH, float)
    k = np.asarray(k, float)
    mask = np.isfinite(cH) & np.isfinite(k) & (cH > 0) & (k > 0)
    cH, k = cH[mask], k[mask]
    if cH.size < 3:
        return None

    def model(c, k0, k_h, n):
        return k0 + k_h * np.power(c, n)

    kmin, kmax = float(k.min()), float(k.max())
    p0 = [max(kmin * 0.1, 1e-7), max((kmax - kmin) / (cH.max() ** 2), 1e-8), 2.0]
    with warnings_.catch_warnings():
        # 3 组数据拟 3 个参数时协方差必然是奇异的（残差自由度为 0），
        # scipy 会刷 Covariance could not be estimated —— 那不是错误，见下。
        warnings_.simplefilter('ignore')
        try:
            popt, pcov = curve_fit(model, cH, k, p0=p0,
                                   bounds=([0.0, 0.0, 0.05], [np.inf, np.inf, 4.0]),
                                   maxfev=40000)
            perr = np.sqrt(np.diag(pcov))
        except Exception:                                 # noqa: BLE001
            return None
    yhat = model(cH, *popt)
    ss_res = float(np.sum((k - yhat) ** 2))
    ss_tot = float(np.sum((k - k.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else float('nan')

    # ⚠ 自由度 = 数据点数 − 参数个数。**恰好定解**（3 点 3 参数）时
    # 点估计仍然成立（n 是唯一解），但残差自由度 0 → 不确定度无定义，
    # scipy 给的是 inf 或 nan。不能把这个 inf 一路传进报告：
    # `pm(4.0, inf)` 会印成 "4.000"，静默丢掉不确定度，读者以为 n 精确到毫位。
    # 按 SKILL §27「点估计与不确定度分开」：n 照给，sigma 明确置 None，
    # 并让上层告警说清「几组数据拟几个参数，无自由度」。
    dof = int(cH.size) - 3
    sigma_ok = bool(dof > 0) and all(np.isfinite(perr))
    if sigma_ok:
        sig = dict(sigma_k0=float(perr[0]), sigma_k_h=float(perr[1]),
                   sigma_n=float(perr[2]))
    else:
        sig = dict(sigma_k0=None, sigma_k_h=None, sigma_n=None)
    sigma_note = ('' if sigma_ok else
                  '只有 %d 组数据却要拟合 3 个参数（残差自由度 0），'
                  '参数的不确定度无法估计；'
                  % cH.size)
    # n 顶到上界 4.0 说明真解在边界外，n 只能当「≥4」读，不能当等号
    at_bound = bool(abs(float(popt[2]) - 4.0) < 1e-6)
    if at_bound:
        sigma_note += ('氢离子级数 n 顶到拟合上界 4，真值可能更大，'
                       '该值只能作下限看待（增加盐酸浓度档次才能定准）；')
    return dict(cH=list(map(float, cH)), k=list(map(float, k)),
                k0=float(popt[0]), k_h=float(popt[1]),
                n=float(popt[2]), r2=float(r2),
                dof=dof, n_points=int(cH.size), n_params=3,
                sigma_ok=sigma_ok, at_bound=at_bound, note=sigma_note,
                model='k1 = k0 + k_H c(H+)^n', **sig)


def _loglog(cH, k, k0):
    cH = np.asarray(cH, float)
    k = np.asarray(k, float)
    d = k - float(k0)
    mask = np.isfinite(cH) & np.isfinite(k) & (cH > 0) & (d > 0)
    cH, d = cH[mask], d[mask]
    if cH.size < 2:
        return None
    fit = _line_fit(np.log10(cH), np.log10(d))
    if not fit:
        return None
    fit['n'] = fit['slope']
    fit['sigma_n'] = fit['sigma_slope']
    fit['kH'] = 10.0 ** fit['intercept']
    fit['k0'] = float(k0)
    return fit


def analyze(data, cfg=None):
    cfg = dict(cfg or {})
    data = dict(data or {})
    warnings = []
    T = float(data.get('temperature_c') or 30.0)
    stock = float(data.get('sucrose_stock') or 0.0)
    c0 = stock / 2.0 if stock else float('nan')
    alpha_inf_measured = data.get('alpha_inf_measured')
    try:
        alpha_inf_measured = float(alpha_inf_measured)
    except (TypeError, ValueError):
        alpha_inf_measured = float('nan')
    # α∞ 也是平行重复读数得来的（Polariputer 静态测量连读 N 次），
    # 与标定点同样只报「平均值 + 重复次数」。
    #
    # ⚠ sd 用 **None** 表示「不知道」，绝不能用 nan：这个值会进 /api/state 的
    # JSON，而 `json.dumps` 默认把 float('nan') 写成裸 `NaN`——**那不是合法
    # JSON**，前端 `await res.json()` 会直接抛
    #   Unexpected token 'N', " 1, \"sd\": NaN}" is not valid JSON
    # 于是整页卡在「初始化失败」。2026-11-10 这次就是这么把页面弄挂的：
    # 分析内核里出现一个 nan，整个界面就打不开了，所以一律用 None 表示缺失。
    try:
        alpha_inf_n = max(1, int(data.get('alpha_inf_n') or 1))
    except (TypeError, ValueError):
        alpha_inf_n = 1
    alpha_inf_sd = None
    raw_sd = data.get('alpha_inf_sd')
    if raw_sd not in (None, ''):
        try:
            cand = float(raw_sd)
            if np.isfinite(cand) and cand >= 0:
                alpha_inf_sd = cand
        except (TypeError, ValueError):
            pass

    # 标称酸浓度 → 实际 c(H⁺) 的换算系数（手填 acid_true 时不用它）
    acid_ratio = acid_ratio_of(cfg)

    # ---- 1) α–c 标定
    #
    # 标定点带可选的 ``n``（该浓度下平行测量了几次）与 ``sd``（读数的标准差）。
    # 数据来源不同，n 的含义也不同：
    #   · 小组成员共享数据 → 每人只给一个最终平均值，n=1；
    #   · 自己的静态重复读数（Polariputer 静态测量） → n 是仪器连续读出几次。
    # 报告表 1 要把 n>1 的点标出来（用户 2026-11-10 要求「只示出平均值和重复次数」），
    # 所以 n/sd 必须一路传到 report.py，不能在 analyze 里丢掉。
    cal_pts = []
    for i, p in enumerate(data.get('calibration') or []):
        try:
            c, a = float(p['c']), float(p['alpha'])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            n = int(p.get('n') or 1)
        except (TypeError, ValueError):
            n = 1
        try:
            sd = float(p['sd']) if p.get('sd') not in (None, '') else None
        except (TypeError, ValueError):
            sd = None
        cal_pts.append((i, c, a, max(1, n), sd))
    cal_ex = set(int(i) for i in (data.get('calibration_exclude') or []))
    use = [(p[1], p[2]) for p in cal_pts if p[0] not in cal_ex]
    cal_fit = _line_fit([p[0] for p in use], [p[1] for p in use])
    alpha0 = (cal_fit['slope'] * c0 + cal_fit['intercept']
              if cal_fit and np.isfinite(c0) else float('nan'))

    # ---- 2) α∞ 理论值
    alpha_inf_theory = float('nan')
    if np.isfinite(alpha0):
        alpha_inf_theory = alpha0 * (M_GLU / M_SUC) * (A_GLU + A_FRU) / A_SUC
    mode = cfg.get('alpha_inf_mode') or 'measured'
    alpha_inf_global = (alpha_inf_measured if mode == 'measured'
                        and np.isfinite(alpha_inf_measured)
                        else alpha_inf_theory)
    if not np.isfinite(alpha_inf_global):
        warnings.append('α∞ 没有可用值：请填实验测得的最终旋光度，或检查蔗糖浓度/标定')
    rel_ainf = ((alpha_inf_measured - alpha_inf_theory) / alpha_inf_theory * 100.0
                if np.isfinite(alpha_inf_measured)
                and np.isfinite(alpha_inf_theory) and alpha_inf_theory
                else float('nan'))

    # ---- 3) 各组动力学
    groups = []
    derived = []          # c(H⁺) 由标称浓度换算得到的组（报告里要标注）
    for g in data.get('groups') or []:
        if not g.get('label'):
            continue
        used = g.get('alpha_inf')
        try:
            used = float(used)
        except (TypeError, ValueError):
            used = alpha_inf_global
        if not np.isfinite(used):
            used = alpha_inf_global
        r = _fit_group(g, used, acid_ratio)
        groups.append(r)
        if r['n'] < 3:
            warnings.append('%s：有效数据点只有 %d 个' % (r['label'], r['n']))
        if not np.isfinite(r['k1']):
            warnings.append('%s：一级拟合失败（检查 α−α∞ 是否为正）' % r['label'])
        elif r['fits']['1']['r2'] < 0.98:
            warnings.append('%s：一级拟合 R² = %.4f，偏低'
                            % (r['label'], r['fits']['1']['r2']))

    # ---- 4) 级数判定
    #
    # ⚠ 报告里「k₁ 随 c(H⁺) 单调增大」这类论断的前提是**按氢离子浓度排序**。
    # 以前的组顺序完全按数据录入顺序（用户实际是 3M、1M、2M 三次测量），
    # 于是报告表 4 的 k₁ 一列是 4.67 → 0.84 → 1.47（先降后升），
    # 正文却印「单调增大」——数字与措辞对不上，读者一眼觉得算错了。
    # 这里按 c(H⁺) 从小到大稳定排序（浓度缺失/相同的保持原顺序），
    # 使表、图和正文论断三者一致。
    # 注意：用**有效浓度** acid_eff 排（手填值优先，否则由标称值换算），
    # 不动 acid_nominal 的语义，也不改数据本体。
    # 只认 acid_true 会漏掉"只填标称浓度"的用法：那时 acid_true 全是 None，
    # 排序退化成原始录入顺序，表和正文的「随浓度增大」就对不上了。
    def _acid_key(g):
        v = g.get('acid_eff', g.get('acid_true'))
        try:
            v = float(v)
            return (0, v) if np.isfinite(v) else (1, 0.0)
        except (TypeError, ValueError):
            return (1, 0.0)

    groups.sort(key=_acid_key)
    #
    # ⚠ 级数判定不能拿 R² 横向比：三种线性化的因变量是 α、ln(α−α∞)、1/(α−α∞)，
    # 量级差几个数量级，R² 被「因变量自身的方差」掩盖，判据不可比。
    # 示例数据上 0 级 R²=0.9266 与 1 级 0.9996 只差 0.073，但残差标准差相差
    # 22 倍；一旦 α∞ 输错或时间窗被截短，R² 排序就会翻转，报告会静默印出
    # 「蔗糖为 0 级反应」这种化学上荒谬的结论。
    #
    # 现在改成比较**归一化残差** s_rel = s_err/|ȳ|（相当于变异系数）：
    # 它把「拟合得多好」换算成无量纲的相对偏离，三种级数之间可以直接比。
    # 另外：三个 s_rel 全都不是有限值时**不猜**，返回 order=None 并告警，
    # 报告印「本次数据不足以判定反应级数」而不是默默给一个 '0' 级
    # （旧代码 `max(..., key=...-1)` 在三个 nan 上会返回字典第一个键 '0'）。
    order = None
    order_label = cfg.get('order_group') or (groups[1]['label'] if len(groups) > 1
                                             else (groups[0]['label'] if groups else ''))
    order_group = next((g for g in groups if g['label'] == order_label), None)
    if order_group is None and groups:
        order_group = groups[0]
    if order_group:
        fits = order_group['fits']
        r2 = {k: (v['r2'] if v else float('nan')) for k, v in fits.items()}
        s_rel = {k: (v.get('s_rel') if v else float('nan'))
                 for k, v in fits.items()}
        cand = {k: val for k, val in s_rel.items() if np.isfinite(val)}
        # 「区分不出差别」的两种情形都要当成无法判定，而不是随便挑一个：
        #   · 全部非有限（拟合失败）；
        #   · 全部为 0（因变量是一模一样的常数，例如所有 α 都录成同一个值，
        #     三种线性化的残差都恰好为 0——此时 argmin 会随手返回 '0' 级）。
        usable = {k: val for k, val in cand.items() if val > 0}
        if not usable:
            # order 保持 None，让上层走「没有可用于级数判定的数据组」这条
            # 既有分支，绝不默许一个 '0' 级。
            order = None
            if not cand:
                warnings.append(
                    '%s 组：三种线性化的残差都无法计算（有效数据点不足或 '
                    'α−α∞ 全部非正），本次数据不足以判定反应级数'
                    % order_group['label'])
            else:
                warnings.append(
                    '%s 组：三种线性化的残差全为 0（因变量几乎不含变化），'
                    '无法据以判定反应级数；请检查 α–t 数据是否录入正确'
                    % order_group['label'])
        else:
            best = min(usable, key=lambda kk: usable[kk])
            best_rel = usable[best]
            # 次优与最优的相对残差相差不到 20% → 判据分辨不出来，点名告警
            rest = sorted(v for kk, v in cand.items() if kk != best)
            ambiguous = (bool(rest) and best_rel > 0
                         and (rest[0] - best_rel) / best_rel < 0.20)
            is_first = (best == '1' and np.isfinite(r2.get('1', np.nan))
                        and r2['1'] >= 0.99)
            order = dict(group=order_group['label'], r2=r2, s_rel=s_rel,
                         best=int(best), is_first=is_first, decided=True,
                         reason='')
            if ambiguous:
                warnings.append(
                    '%s 组：%s级与%s级的归一化残差只相差 %.0f%%，级数判定不明确；'
                    '请检查 α∞ 取值与时间窗是否覆盖足够多的转化率'
                    % (order_group['label'],
                       {'0': '零', '1': '一', '2': '二'}[best],
                       {'0': '零', '1': '一', '2': '二'}[
                           min((kk for kk in cand if kk != best),
                               key=lambda kk: cand[kk])],
                    (rest[0] - best_rel) / best_rel * 100.0))
            if (not is_first and np.isfinite(r2.get(best, np.nan))
                    and r2[best] < 0.99):
                warnings.append(
                    '%s 组：判定为 %s 级，但该级线性化 R² = %.4f 未达 0.99，'
                    '结论需结合实验条件核对'
                    % (order_group['label'],
                       {'0': '零', '1': '一', '2': '二'}[best], r2[best]))

    # ---- 5) k1–c(H+) 与 lg–lg
    # 用「有效浓度」做 k1–c(H⁺) 拟合：手填的 acid_true 优先，
    # 只填标称值时按 acid_ratio 换算（见 effective_acid）。
    cH = [g['acid_eff'] for g in groups]
    for g in groups:
        if g['acid_source'] == 'missing':
            warnings.append('%s：既没填标称酸浓度也没填 c(H⁺)，该组不参与 '
                            'k₁–c(H⁺) 拟合' % g['label'])
        elif g['acid_source'] == 'nominal':
            derived.append(g['label'])
    k1 = [g['k1'] for g in groups]
    rate_law = _rate_law(cH, k1)
    loglog = None
    if rate_law:
        loglog = _loglog(cH, k1, rate_law['k0'])
        if loglog:
            loglog['n_nonlinear'] = rate_law['n']
    if rate_law is None:
        warnings.append('k1–c(H+) 数据不足或非线性拟合失败（至少需要 3 组有效数据）')
    else:
        if rate_law['r2'] < 0.95:
            warnings.append('k1–c(H+) 拟合 R² = %.4f，偏低；'
                            '检查各组是否同一温度/同一蔗糖浓度'
                            % rate_law['r2'])
        if rate_law['note']:
            warnings.append('k1–c(H+) 拟合：' + rate_law['note'].rstrip('；') + '。')

    if cal_fit is None:
        warnings.append('旋光度–浓度标定点少于 2 个，无法求 α0 与 α∞ 理论值')
    if np.isfinite(rel_ainf) and abs(rel_ainf) > 5:
        warnings.append('α∞ 实验值与理论值相差 %.1f%%，建议核对比旋光度/浓度'
                        % rel_ainf)

    return dict(
        temperature=T, c0=c0, alpha0=alpha0,
        calibration=dict(points=[{'index': i, 'c': c, 'alpha': a,
                                  'n': n, 'sd': sd, 'exclude': i in cal_ex}
                                 for i, c, a, n, sd in cal_pts],
                         fit=cal_fit, exclude=sorted(cal_ex), n=len(use)),
        alpha_inf=dict(measured=alpha_inf_measured, theory=alpha_inf_theory,
                       used=alpha_inf_global, mode=mode, relative=rel_ainf,
                       n=alpha_inf_n, sd=alpha_inf_sd),
        groups=groups, order=order, rate_law=rate_law, loglog=loglog,
        # c(H⁺) 的换算口径：ratio 是系数，derived 是「由标称值换算而来」的组
        acid=dict(ratio=acid_ratio, derived=derived),
        warnings=warnings, constants=dict(M_SUC=M_SUC, M_GLU=M_GLU,
                                          A_SUC=A_SUC, A_GLU=A_GLU, A_FRU=A_FRU))
