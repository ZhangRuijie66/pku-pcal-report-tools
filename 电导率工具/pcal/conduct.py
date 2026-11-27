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
import math
import os
import threading

import numpy as np

from .atomicio import (CorruptFileError, atomic_write_json, quarantine,
                       read_json)

# ---------------------------------------------------------------- 常数
KCL_THEORY_US = 1415.0        # 0.01 mol·dm⁻³ KCl 的验收标准值 μS·cm⁻¹（参考报告口径）
KCL_TOLERANCE = 5.0
C_STD = 1000.0                # 标准浓度 c° / mol·m⁻³

# 25 ℃ 离子极限摩尔电导率（CRC Handbook，S·m²·mol⁻¹；参考报告引用值）
#
# ⚠ 2026-11-20 按 2026 秋季讲义改口径：讲义「仪器和试剂」与配制表用的是
# **NaCl / HCl**（共享数据表也是这两瓶），而 2025 参照报告用的是
# NaNO₃ / HNO₃。物种换过来以后，CL⁻ 的离子值必须有，否则理论值无从加和。
# NO₃⁻ 仍留在表里：老数据文件（NaNO₃ 口径）还能被解析，只是不再是默认物种。
LAMBDA_ION = {
    'H': 0.034965,
    'Na': 0.005008,
    'Ac': 0.00409,
    'Cl': 0.007631,
    'NO3': 0.007142,
}
# 由离子值加和的理论 Λm∞（S·m²·mol⁻¹）
LAMBDA_THEO = {
    'NaCl': LAMBDA_ION['Na'] + LAMBDA_ION['Cl'],
    'NaAc': LAMBDA_ION['Na'] + LAMBDA_ION['Ac'],
    'HCl': LAMBDA_ION['H'] + LAMBDA_ION['Cl'],
    'HAc': LAMBDA_ION['H'] + LAMBDA_ION['Ac'],
}
PKA_HAC = 4.756               # CRC，25 ℃
KA_HAC = 10 ** (-PKA_HAC)     # = 1.754×10⁻⁵

#: 25 ℃ 附近各离子的摩尔电导率温度系数 β = (1/Λ)(dΛ/dT)，单位 %/℃。
#:
#: 用途：**温度补偿误差**的定量估计。电导率仪按固定的 "2.00 %/℃" 做线性
#: 补偿（见数据文件 ``compensation``），而真实溶液的 β 随离子种类而变——
#: H⁺ 的 β 只有约 1.45 %/℃，Ac⁻/Na⁺ 约 2.1 %/℃，所以「用一个 2.00 补偿
#: 所有溶液」本身就有残差。
#:
#: 取自 CRC Handbook「Conductivity of Electrolytes」表中 25 ℃ 附近各离子
#: 的 dΛ/dT 折算（表列的是 Λ(T) 的一阶系数，单位 S·m²·mol⁻¹·K⁻¹）。
#: 报告里只作**半定量**量级估计用，不作精确定量依据。
ION_TEMP_COEFF = {'H': 1.45, 'Na': 2.10, 'Ac': 2.15, 'Cl': 2.05}

#: 实验的**参考温度**：电导率仪一律把读数补偿到 25 ℃（``T_REF_C``）。
T_REF_C = 25.0

#: 三种强电解质，顺序即报告里的表号顺序（表3/表4/表5、图3/图4/图5）。
STRONG_SPECIES = ('NaCl', 'NaAc', 'HCl')
#: 全部物种（含弱电解质），按加和关系组合时也依这个顺序。
SPECIES_ORDER = STRONG_SPECIES + ('HAc',)

SPECIES_LABEL = {'NaCl': 'NaCl', 'NaAc': 'NaAc', 'HCl': 'HCl', 'HAc': 'HAc',
                 'NaNO3': 'NaNO₃', 'HNO3': 'HNO₃'}
# 普通文本里的化学式（真下标写法）
CHEM_MARK = {'NaCl': 'NaCl', 'NaAc': 'NaAc', 'HCl': 'HCl', 'HAc': 'HAc',
             'NaNO3': 'NaNO_{3}', 'HNO3': 'HNO_{3}'}
# 拟合直线方程里用的 LaTeX 化学式（\mathrm 内不能有裸数字下标）
CHEM_LATEX = {'NaCl': r'\mathrm{NaCl}', 'NaAc': r'\mathrm{NaAc}',
              'HCl': r'\mathrm{HCl}', 'HAc': r'\mathrm{HAc}'}

#: 离子独立运动定律的组合：Λm∞(HAc) = Λm∞(HCl) + Λm∞(NaAc) − Λm∞(NaCl)
#: 等价于 (H⁺+Cl⁻)+(Na⁺+Ac⁻)−(Na⁺+Cl⁻) = H⁺+Ac⁻ = Λm∞(HAc)。
DEFAULT_COMBO = {'add': ['NaAc', 'HCl'], 'sub': ['NaCl']}

#: 默认数据：**共享数据表第 7 号仪器**（武湛博 / 张瑞杰 合作那一台，
#: 2026-11-18 周三组）。用真实数据当默认值，自检报告也就等于本人数据。
DEFAULT_DATA = {
    'temp_c': 23.5,
    'kcl_label_uS': 1415.0,
    'kcl_theory_uS': KCL_THEORY_US,
    'cell_constant_label': 0.977,
    'cell_constant': 0.977,
    'kcl_after_uS': 1415.0,
    'kappa_w_uS': 1.49,
    'compensation': 2.00,       # 仪器温度补偿系数 %/℃
    'solutions': {
        'NaCl': {'conc': ['25.00', '10.00', '5.000', '2.500', '1.250'],
                 'kappa': ['0.2860', '0.1176', '0.0593', '0.0311', '0.01532']},
        'NaAc': {'conc': ['25.00', '10.00', '5.000', '2.500', '1.250'],
                 'kappa': ['0.1990', '0.0820', '0.0419', '0.0222', '0.01113']},
        'HCl': {'conc': ['25.00', '12.00', '8.000', '5.000', '2.000'],
                'kappa': ['1.0060', '0.4910', '0.3290', '0.2090', '0.0851']},
        'HAc': {'conc': ['25.00', '10.00', '5.000', '2.500', '1.250'],
                'kappa': ['0.0256', '0.01598', '0.01111', '0.00785', '0.00541']},
    },
    # 离子独立运动定律的组合：Λm∞(HAc) = 加项 − 减项
    'combo': dict(DEFAULT_COMBO),
}

DATA_FILENAME = '电导率数据.json'


# 最近一次 load_data_ex 导致「用户数据不可用、改用参照数据」的留证文件路径。
# `/api/data` 保存成功后据此提示用户「原文件已备份为 xxx.corrupt-时间戳」。
#
# 用 threading.local()：服务器是 ThreadingHTTPServer，每个请求一个线程。
# 存模块级全局变量的话，A 请求刚留的证可能被 B 请求的读盘覆盖，
# 于是用户被告知了一个不属于他的备份路径——比不提示更糟。
_STATE = threading.local()


def _set_last_corrupt_path(path):
    _STATE.corrupt_path = path


def _latest_quarantine(data_dir, filename):
    """目录里该数据文件最新的留证文件路径（没有则 None）。

    留证命名是 ``<filename>.corrupt-<YYYYMMDD-HHMMSS>``，所以按名字排序
    就是按时间排序。
    """
    if not data_dir or not os.path.isdir(data_dir):
        return None
    prefix = filename + '.corrupt-'
    try:
        names = sorted(n for n in os.listdir(data_dir) if n.startswith(prefix))
    except OSError:
        return None
    return os.path.join(data_dir, names[-1]) if names else None


def _has_quarantine(data_dir, filename):
    """目录里是否留有 ``<filename>.corrupt-*`` —— 有就说明曾经坏过一次。"""
    return _latest_quarantine(data_dir, filename) is not None


def last_corrupt_path():
    """**本线程**最近一次 :func:`load_data_ex` 留证的路径；没留证则 None。

    语义是「当前这份数据不可用，原始文件被备份到哪儿了」：只有两种情况
    会返回路径——本次刚刚留证，或者文件已不在但目录里躺着以前的留证文件。
    数据文件本身正常时一律返回 None。

    :func:`load_data_ex` 每次调用都会重置它（也只影响当前线程），所以调用方
    在同一次请求里紧接着读取，拿到的就是本次的结果。
    """
    return getattr(_STATE, 'corrupt_path', None)


def load_data_ex(data_dir):
    """读数据 JSON，返回 ``(data, path, warnings)``——推荐调用方式。

    行为（2026-11-08 收紧，对应"打开页面 → 真实读数消失"事故）：

    * 文件**不存在且没有留证文件** → 落一份默认数据（便于用户直接在文件里改）；
    * 文件**存在但是坏 JSON** → **改名留证**（``*.corrupt-<时间戳>``），
      返回默认数据 + 一条告警。**绝不把默认数据写回磁盘顶掉坏文件**——
      旧代码 ``except (OSError, ValueError): pass`` 之后无条件重写默认数据，
      用户真实的实验读数就这样被 1387 字节的示例数据覆盖了；
    * 文件不存在**但目录里有留证文件** → 说明刚坏过、用户正在修，
      这时也**不初始化**，免得默认数据抢先占住原文件名，把用户手工
      恢复的那份挡住。

    留证路径另存进 :func:`last_corrupt_path`，供 ``/api/data`` 保存成功后
    提示用户「原文件已备份为 …」。
    """
    _set_last_corrupt_path(None)           # 每次调用重置，避免串到上一次的结果

    path = os.path.join(data_dir, DATA_FILENAME) if data_dir else None
    warnings = []
    if not path:
        return _deep_default(), None, warnings

    try:
        data = read_json(path, None)
    except CorruptFileError as exc:
        bad = quarantine(path, 'corrupt')
        if bad:
            _set_last_corrupt_path(bad)
            warnings.append(
                '%s 不是合法 JSON（%s），已改名留证为 %s，'
                '本次改用内置参照数据。修好留证文件后放回原名即可恢复。'
                % (os.path.basename(path), exc.original,
                   os.path.basename(bad)))
        else:
            warnings.append(
                '%s 不是合法 JSON（%s），且无法改名留证，'
                '本次改用内置参照数据。' % (os.path.basename(path),
                                            exc.original))
        return _deep_default(), None, warnings
    except OSError as exc:
        warnings.append('读取 %s 失败：%s。本次改用内置参照数据。'
                        % (os.path.basename(path), exc))
        return _deep_default(), path, warnings

    if data is None:                       # 文件真的不存在
        old = _latest_quarantine(data_dir, DATA_FILENAME)
        if old:
            # 刚留过证，用户可能正在手工修 → 不要再拿默认数据占位
            _set_last_corrupt_path(old)
            warnings.append(
                '%s 不存在，但目录里留有 %s.corrupt-* 留证文件。'
                '为免覆盖你的原始读数，本次不自动生成数据文件；'
                '把修好的留证文件改回 %s 即可恢复。'
                % (DATA_FILENAME, DATA_FILENAME, DATA_FILENAME))
            return _deep_default(), None, warnings
        data = _deep_default()
        try:
            os.makedirs(data_dir, exist_ok=True)
            atomic_write_json(path, data)
        except OSError as exc:
            warnings.append('初始化数据文件失败：%s' % exc)
            path = None
        return data, path, warnings
    return _merge(_deep_default(), data), path, warnings


def load_data(data_dir):
    """旧签名：返回 ``(data, path)``。告警请用 :func:`load_data_ex`。"""
    data, path, _warnings = load_data_ex(data_dir)
    return data, path


def save_data(data_dir, data):
    """原子写盘（先在内存里序列化成功，再整体替换），返回写好的路径。"""
    path = os.path.join(data_dir, DATA_FILENAME)
    atomic_write_json(path, data)
    return path


def _deep_default():
    return json.loads(json.dumps(DEFAULT_DATA, ensure_ascii=False))


def _merge(base, patch):
    """浅层合并 + solutions 逐键合并，容忍 JSON 里少写字段。

    ⚠ 合并**不删除** patch 里的额外物种：2026-11-20 把物种从
    NaNO₃/HNO₃ 改成 NaCl/HCl 以后，用户磁盘上的老 ``电导率数据.json``
    里仍是旧物种，合并后会同时存在四个物种（NaCl/NaAc/HCl/HAc 加上
    NaNO₃/HNO₃）。这本身不算错——老数据还能看——但 ``combo`` 若指向
    已经不存在的物种，就会在 ``combo_lambda_inf`` 里抛 KeyError。
    那种情况由 ``analysis._usable_combo`` 兜住。
    """
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
#
# 电导率仪的**末位**不该由「字符串里有几个字符」决定。
#
# 原来的规则是 σ_κ = 2×10^(−小数位数)，于是同一个仪器读数：
#      '0.277'  → 3 位小数 → σ_κ = 2e-3
#      '0.2770' → 4 位小数 → σ_κ = 2e-4      相差 10 倍
#      '25' / '25.0' / '25.00' 相差 100 倍
# 学生抄读数时习惯把末尾的 0 省掉，于是「抄了几个 0」直接决定报告的精度，
# 而报告 4.x 还会把这件事原样印成「σ_κ 随记录的小数位数而变」（审计 A 的 P1-6）。
#
# 现在的规则：**按仪器量程分档定末位**，字符串只用于「用户是否写了更高精度」。
#
# 分档依据是示例数据自身的规律：把 S·m⁻¹ 换算回仪器显示的 μS·cm⁻¹，
#     0.2770 → 2770    0.1139 → 1139    0.0574 → 574     0.0300 → 300
#     0.01575 → 157.5  0.01178 → 117.8  0.00766 → 76.6   0.00525 → 52.5
# 可以看出大量程显示到 1 μS·cm⁻¹（=1e-4 S·m⁻¹）、小量程显示到 0.1 μS·cm⁻¹
# （=1e-5 S·m⁻¹），分界约在 0.02 S·m⁻¹（=200 μS·cm⁻¹）。这也解释了
# 0.0574 / 0.0300 / 0.00525 为什么比同瓶其它读数少一位：那是学生把
# 「0.05740 / 0.03000 / 0.005250」末尾的 0 省掉了，不是仪器只有那么精。
#
# 于是：
#      κ >  0.02  → 末位 1e-4 → σ_κ = 2e-4
#      κ ≤  0.02  → 末位 1e-5 → σ_κ = 2e-5
# 这样 '0.277' 与 '0.2770' 得同一个 σ_κ、'0.0159' 与 '0.01592' 也相同，
# 少抄一个 0 不再改变任何不确定度。而且对**原始数据的正确读数**，
# 分档结果与旧规则（按小数位）逐位相同 —— 所以 K° 与 σ_K° 的既有数值
# 只有在瓶间离散那一项上才会变（见 k_from_mean）。
KAPPA_RANGE_EDGES = ((0.02, 4), (0.0, 5))   # (κ 下界, 末位小数位数)，按顺序匹配
KAPPA_SIG_DIGITS = 4                          # 兼容旧接口（未分档时的默认位数）


def _decimals(s):
    """字符串读数的小数位数（'0.01575' → 5）。仅用于**显示**与位数统计。"""
    s = str(s).strip()
    if '.' in s:
        return len(s.split('.')[-1].rstrip())
    return 0


def _sig_digits_written(s):
    """字符串里**实际写出的**有效数字位数（'0.277' → 3，'0.2770' → 4）。"""
    s = str(s).strip().lstrip('+-')
    if not s or s.lower() in ('nan', 'none'):
        return 0
    if 'e' in s.lower():
        s = s.lower().split('e')[0]
    digits = s.replace('.', '').lstrip('0')
    return len(digits)


def _tier_decimals(kappa):
    """按读数量级给出仪器末位的小数位数（分档见 KAPPA_RANGE_EDGES）。"""
    ax = abs(float(kappa))
    if not math.isfinite(ax):
        return KAPPA_RANGE_EDGES[-1][1]
    for lower, dec in KAPPA_RANGE_EDGES:
        if ax > lower:
            return dec
    return KAPPA_RANGE_EDGES[-1][1]


def sigma_kappa(reading, min_sigma=None):
    """仪器读数末位不确定度：末位取 2（沿用参考报告「最后一位的 2」口径）。

    末位**只由读数量级对应的仪器分辨力**决定（见文件头 KAPPA_RANGE_EDGES），
    与字符串里写了几个字符完全无关——'0.277'、'0.2770'、'0.27700' 得到同一个
    σ_κ。这是本条修复的核心：σ_κ 必须由**仪器**决定，不能由「学生抄了几个 0」
    决定。

    （早先版本还留了「用户写出更多小数位就升级精度」的分支，实测没有意义：
    手记电导率仪不可能真有 1e-6 S·m⁻¹ 的分辨力，`0.015920` 只是多抄了个 0，
    不该让 σ_κ 从 2e-5 缩到 2e-6，那会让不确定度变成「取决于抄写习惯」。）

    `min_sigma`：可选的绝对下限（S·m⁻¹），需要并进「±0.5% FS」这类相对项时用。
    """
    x = to_float(reading)
    dec = _tier_decimals(x) if math.isfinite(x) else KAPPA_RANGE_EDGES[-1][1]
    val = 2.0 * 10.0 ** (-dec)
    if min_sigma is not None and math.isfinite(min_sigma):
        val = max(val, float(min_sigma))
    return float(val)


def to_float(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return float('nan')


def line_fit(x, y):
    """不加权 OLS 直线拟合，返回 k, b, σk, σb, r, n。

    ⚠ 点数与「能算什么」的关系（2026-11-09 审计修正）：

      0 点      → 全 NaN（没有数据，没什么可算）
      1 点      → 全 NaN（过一点有无数条直线，斜率不唯一）
      **2 点**  → **k、b 照常给**（两点唯一确定一条直线，斜率与截距是精确解），
                  σk、σb、r 给 NaN（残差自由度 n−2 = 0，不确定度无定义）
      ≥3 点     → k、b、σk、σb、r 全给

    原来写成 `if n < 3: 全 NaN`，把**两点时的点估计也一起丢了**。两点数据
    在真实验里并不罕见（浓度档次少、或部分点被判为异常剔除后只剩两点），
    那样整个 Λm∞ 会变成 NaN，报告里一片「—」，而用户看不出是「工具不支持」
    还是「数据有问题」。现在点估计保留，不确定度留空由上层显示为「—」，
    并配一条警告说明为什么没有不确定度。
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    n = len(x)
    if n < 2 or x.size != y.size:
        return dict(k=float('nan'), b=float('nan'),
                    sigma_k=float('nan'), sigma_b=float('nan'),
                    r=float('nan'), n=n, s2=float('nan'), df=0)
    if n == 2:
        # 两点：斜率和截距是唯一解，直接用差分算（比 polyfit 更稳、更准）
        dx = float(x[1] - x[0])
        if dx == 0:
            return dict(k=float('nan'), b=float('nan'),
                        sigma_k=float('nan'), sigma_b=float('nan'),
                        r=float('nan'), n=n, s2=float('nan'), df=0)
        k = float((y[1] - y[0]) / dx)
        b = float(y[0] - k * x[0])
        return dict(k=k, b=b,
                    sigma_k=float('nan'), sigma_b=float('nan'),
                    r=float('nan'), n=n, s2=float('nan'), df=0)
    k, b = np.polyfit(x, y, 1)
    yhat = k * x + b
    resid = y - yhat
    sse = float(np.sum(resid ** 2))
    sxx = float(np.sum((x - x.mean()) ** 2))
    df = n - 2
    # 残差方差 s²：F 检验比较"各人的拟合精度"时用。sse/df 只在 df>0 时有定义。
    s2 = (sse / df) if df > 0 else float('nan')
    if n > 2 and sxx > 0:
        s = np.sqrt(sse / (n - 2))
        sigma_k = s / np.sqrt(sxx)
        sigma_b = s * np.sqrt(1.0 / n + x.mean() ** 2 / sxx)
    else:
        sigma_k = sigma_b = float('nan')
    sst = float(np.sum((y - y.mean()) ** 2))
    r = float(np.corrcoef(x, y)[0, 1]) if sst > 0 else float('nan')
    return dict(k=float(k), b=float(b), sigma_k=float(sigma_k),
                sigma_b=float(sigma_b), r=r, n=n,
                s2=float(s2), df=df)


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
    """求平均法：各瓶 K°、σ、平均与合成 σ。

    ⚠ σ 的口径（审计 A 的 P1-5）：5 个瓶是**不同浓度**下的 5 个独立估计，
    不是同一个量的 5 次重复测量。所以

      · `sigma_within = √(Σσ_i²)/n` 是「n 个等精度独立观测取平均」的标准误，
        它只反映**单瓶内部**的读数传播，把瓶间系统漂移当成了 0；
      · `sigma_between = std(K_i, ddof=1)/√n` 才是「这些瓶彼此有多一致」，
        也就是平均值的标准误。

    实测示例数据：各瓶 K° 从 1.639e-5 单调降到 1.189e-5（相差 38%，
    活度系数未校正造成的系统漂移），
        sigma_within  = 2.5676e-07
        sigma_between = 7.7960e-07     ← 相差 3.04 倍
    旧代码只报 within，等于宣称「5 个瓶一致到 1.8%」，与数据直接矛盾，
    后果是报告把 K° 与手册值的偏差判成「显著」、却把两法差异判成「一致」。

    这里改为报 `max(within, between)`：瓶间一致时退回 within（不虚高），
    瓶间有漂移时用 between（不虚低）。两者都留在返回值里，上层可以点名原因。
    """
    out = []
    for r in rows:
        b = k_bottle(r['c'], r['kappa_corr'], lam_inf)
        b['sigma_kappa'] = r['sigma_kappa']
        b['sigma_k'] = sigma_k_bottle(r['c'], r['kappa_corr'], lam_inf,
                                      r['sigma_kappa'], sigma_lam_inf)
        out.append(b)
    ks = np.array([b['k'] for b in out])
    sigmas = np.array([b['sigma_k'] for b in out])
    n = len(ks)
    mean = float(ks.mean())
    sigma_within = float(np.sqrt(np.nansum(sigmas ** 2)) / n) if n else float('nan')
    if n >= 2 and np.all(np.isfinite(ks)):
        sigma_between = float(np.std(ks, ddof=1) / math.sqrt(n))
        spread = float(np.std(ks, ddof=1))
    else:
        sigma_between = float('nan')
        spread = float('nan')
    if math.isfinite(sigma_between) and sigma_between > sigma_within:
        sigma = sigma_between
        sigma_source = 'between'
        # 瓶间离散超过单瓶传播 2 倍才算「有系统漂移」，需要在报告里点名
        drift = bool(sigma_between > 2.0 * sigma_within) if sigma_within else True
    else:
        sigma = sigma_within
        sigma_source = 'within'
        drift = False
    return dict(bottles=out, mean=mean, sigma=sigma, n=n,
                sigma_within=sigma_within, sigma_between=sigma_between,
                spread=spread, sigma_source=sigma_source, drift=drift,
                rel_spread=(spread / abs(mean) * 100.0
                            if mean and math.isfinite(spread) else float('nan')))


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


# ---------------------------------------------------------------- 误差预算
#
# 为什么需要这一节：3.3 里报的 σ(K°) 只是 **A 类**（由瓶间离散或读数末位
# 传播得到），它答不了「K° 的误差到底来自哪几项、各占多少」。课程要求的
# 误差分析要的是**对最终量的贡献分解**，所以这里按最终量 K° 做一次预算。
#
# 口径（三处必须说清，报告里也要印出来）：
#
#   1. **灵敏度用一阶解析式**。K° = (c/c°)α²/(1−α)、α = κ_c/(cΛ∞) 给出
#          |∂lnK/∂lnc| = 1+r,   ∂lnK/∂lnκ_c = ∂lnK/∂(−lnΛ∞) = 2+r,
#      其中 r = α/(1−α)。α < 0.11 时 r < 0.12，所以两个系数分别在 1.07 和
#      2.07 附近——**κ 的影响约为浓度的 2 倍**，这不是"两项差不多"。
#
#   2. **Λ∞(HAc) 的误差要按组合式传**。Λ∞(HAc)=Λ∞(NaAc)+Λ∞(HCl)−Λ∞(NaCl)，
#      所以某一物种 Λ∞ 的误差对 K° 的贡献是 (2+r)·w_s·σ(Λ∞_s)/Λ∞(HAc)，
#      权重 w_s = ±Λ∞_s/Λ∞(HAc)。实测 HAc 中 Λ∞(HCl)=0.0431 远大于其余两项,
#      于是 w(HCl)=1.09（主导）、w(NaCl)=−0.31、w(NaAc)=0.23——**Λ∞(HCl)
#      的一个小误差会被放大 1.09 倍传进 K°**，而它自身的相对不确定度只有
#      0.65%，在三个物种里最小。按「谁自己相对误差大谁就最重要」来排序会
#      得到相反结论。这里按**权重×自身误差**算，不按自身误差排序。
#
#   3. **温度补偿在 K° 里一阶抵消**。因为 Λ∞(HAc) 由同一批离子加和得到，
#      与 HAc 溶液自身的电导率**同源**：补偿系数整体偏一点，κ(HAc) 与
#      Λ∞(HAc) 按同一比例变，比值不变，K° 就不变。实测：|25−T|=1.5 K、
#      各物种 β 与设定 2.00 差 −0.44~+0.12 %/℃，代入后 ΔK°/K° = −0.005%。
#      所以温度补偿对 **K°** 是 0.0% 档，但对 **表6 的 Λ∞ 绝对值**是
#      O(0.7%) 档——两件事不能混为一谈，报告里必须分开说。
#
# 合成口径：各项均折算成 **ΔK°/K° 的相对量**后按方和根合成（相互独立）。
# 「共同项」（拟合、温度补偿、母液/容量瓶）对每瓶同向，不随瓶数下降；
# 「独立项」（逐瓶读数、逐瓶移液管、逐瓶温度波动）随瓶数按 1/√n 下降。

#: 容量允差（GB/T 12807 A 类，mL）。键是标称容量，值是允差。
PIPETTE_TOL_ML = {0.5: 0.010, 1.0: 0.007, 2.0: 0.010, 5.0: 0.015,
                  10.0: 0.020, 25.0: 0.030, 50.0: 0.050}
FLASK_TOL_ML = {50.0: 0.06, 100.0: 0.10, 250.0: 0.15}
FLASK_VOLUME_ML = 100.0        # 讲义配制表：一律定容到 100 mL
#: 母液浓度的相对不确定度（%）。母液由老师配制并标定，学生不参与，
#: 只能按「大致的四位数浓度」估；这是**估计值**，报告里要标明。
STOCK_REL_PCT = 0.5
#: 读数期间的恒温槽温度波动（℃）。讲义要求恒温，实际波动按 ±0.2 K 估。
TEMP_FLUCT_K = 0.2
#: 三角分布换算成标准不确定度的除数（容量允差是「最大允许误差」，按三角分布）
_TOL_DIVISOR = np.sqrt(3.0)


def pipette_for(volume_ml):
    """取能一次性放出 ``volume_ml`` 的**最小**标称吸量管，返回 (标称, 允差)。

    讲义配制表用的量取体积是 10/4/2/1/0.5 mL，而移液管只有 1/2/5/10/25 mL
    这些标称规格（0.5 mL 用 1 mL 分度管估读）。所以 4 mL 实际是用 5 mL
    移液管放到 4 mL 刻度——允差按**标称 5 mL 的允差**算，相对不确定度因此
    是 0.015/4 = 0.375% 而不是 0.015/5 = 0.3%。这一步容易写错。
    """
    for nom in sorted(PIPETTE_TOL_ML):
        if volume_ml <= nom + 1e-9:
            return float(nom), float(PIPETTE_TOL_ML[nom])
    nom = max(PIPETTE_TOL_ML)
    return float(nom), float(PIPETTE_TOL_ML[nom])


def species_temp_coeff(key):
    """某电解质的电导率温度系数 β（%/℃），由离子值按 Λ 加权。

    κ = Λm·c 而 Λm∞ 是各离子之和，所以盐的 β 是离子 β 按**离子摩尔电导率**
    加权（不是算术平均）：β_salt = Σ(λ_i·β_i)/Σ(λ_i)。
    """
    ions = {'NaCl': ('Na', 'Cl'), 'NaAc': ('Na', 'Ac'),
            'HCl': ('H', 'Cl'), 'HAc': ('H', 'Ac')}.get(key)
    if not ions:
        return float('nan')
    lam = [LAMBDA_ION[i] for i in ions]
    tot = sum(lam)
    if tot <= 0:
        return float('nan')
    return sum(l * ION_TEMP_COEFF[i] for l, i in zip(lam, ions)) / tot


def _lambda_weights(fits, lam_hac, combo):
    """组合式里各物种的**相对权重** w_s（加项为正、减项为负）。

    Λ∞(HAc) = Σ_add Λ∞_s − Σ_sub Λ∞_s，所以
        ∂Λ∞(HAc)/∂Λ∞_s = ±1
    写成相对形式：εΛ(HAc) = Σ w_s·εΛ_s，w_s = ±Λ∞_s / Λ∞(HAc)。
    """
    out = {}
    if not lam_hac:
        return out
    for k in combo.get('add', []):
        out[k] = float(fits[k]['lam_inf']) / lam_hac
    for k in combo.get('sub', []):
        out[k] = -float(fits[k]['lam_inf']) / lam_hac
    return out


def conduct_order(combo):
    """组合式里出现的物种（加项在前、减项在后），按 STRONG_SPECIES 归一顺序。"""
    keys = list((combo or {}).get('add', [])) + list((combo or {}).get('sub', []))
    return [k for k in STRONG_SPECIES if k in keys]


def _kbar_forward(tables, combo, kf=None, kappa_w=None):
    """独立的**前向模型**：按给定的 κ 缩放因子重算 K̄（求平均法均值）。

    ``kf`` = {物种: [逐瓶因子]}，把``tables[物种]`` 的**测量电导率**乘上这些
    因子（缺省为 1）。返回 ``(K̄, Λ∞(HAc))``；数据不齐时返回 ``(nan, nan)``。

    ⚠ 为什么误差预算必须走这个前向模型，而不是套解析灵敏度系数：

    一开始我按教科书公式推 ∂lnK/∂lnc = 1+r、∂lnK/∂lnκ = 2+r，然后逐项相乘。
    用整链有限差分一验，**符号和量级都不对**——因为这些误差并不是干净地只
    作用在一个输入量上：

      · 「母液浓度偏 f 倍」并不是「浓度变 f 倍」：实际浓度偏 f 时，测到的 κ
        也同比例偏大，而程序用的仍是**名义** c。于是 Λm = κ/c 偏 f、α = Λm/Λ∞
        里 f 又抵消，真正传下去的是「κ 偏 f 而 c 不动」。直接对 c 求偏导会得到
        完全不同的结果（实测：按 c 求偏导得 −1.07，按真实机制只有 2+r 的路径）。
      · Λ∞(HAc) 是**三个强电解质的加减**，带正负权重，某一物种的误差可能被
        放大（HCl 权重 1.09）也可能反向（NaCl 权重 −0.31）。手推容易丢符号。
      · K̄ 是**各瓶 K 的平均**，单瓶扰动的系数是 w_i(2+r_i)（w_i 为瓶权重），
        把「单瓶」当成「全体」会差 n 倍。

    与其把这三层耦合手推一遍（我推错过两版），不如让代码自己算：给 κ 加
    一个小扰动、重跑整条链、读 ΔK̄/K̄。符号与量级由构造保证，并与主计算共用
    同一套 ``kohlrausch`` / ``k_from_mean``，不会另立口径。
    """
    if not tables:
        return float('nan'), float('nan')
    present = [k for k in STRONG_SPECIES if k in tables]
    if len(present) < len(STRONG_SPECIES):
        return float('nan'), float('nan')
    need = list(STRONG_SPECIES) + ['HAc']
    if 'HAc' not in tables:
        return float('nan'), float('nan')

    def rows_for(key):
        src = tables[key]
        f = (kf or {}).get(key) or [1.0] * len(src)
        out = []
        for r, fi in zip(src, f):
            km = float(r.get('kappa', float('nan')))
            if not np.isfinite(km):
                km = r['kappa_corr'] + (kappa_w or 0.0)
            kw = (kappa_w if kappa_w is not None
                  else float(r['kappa']) - float(r['kappa_corr']))
            kc = km * fi - kw
            c = float(r['c'])
            out.append(dict(c=c, kappa=km * fi, kappa_corr=kc,
                            sigma_kappa=r.get('sigma_kappa', float('nan')),
                            lam=(kc / c) if c else float('nan')))
        return out

    fits = {}
    for key in STRONG_SPECIES:
        fits[key] = kohlrausch(rows_for(key))
    lam, _sig = combo_lambda_inf(fits, combo)
    if not np.isfinite(lam):
        return float('nan'), float('nan')
    rows_h = rows_for('HAc')
    ks = [k_bottle(r['c'], r['kappa_corr'], lam)['k'] for r in rows_h
          if r['c'] and np.isfinite(r['kappa_corr'])]
    if not ks:
        return float('nan'), float('nan')
    return float(np.mean(ks)), float(lam)


def _budget_forward(tables, combo, per_species=None, per_bottle=None,
                    kappa_w=None):
    """把一批 κ 扰动施加到前向模型上，返回 ``ΔK̄/K̄``（分数）。

    ``per_species``: {物种: 相对扰动}，该物种**所有瓶一起**动（共同项）
    ``per_bottle``: [(物种, 瓶序号, 相对扰动), …]，逐瓶独立扰动
    """
    K0, _ = _kbar_forward(tables, combo, kappa_w=kappa_w)
    if not np.isfinite(K0) or K0 == 0:
        return float('nan')
    kf = {}
    for key, eps in (per_species or {}).items():
        n = len(tables.get(key) or [])
        if n:
            kf[key] = [1.0 + eps] * n
    for key, idx, eps in (per_bottle or []):
        if key not in tables:
            continue
        f = kf.get(key)
        if f is None or len(f) != len(tables[key]):
            f = [1.0] * len(tables[key])
        else:
            f = list(f)
        f[idx] = f[idx] * (1.0 + eps)
        kf[key] = f
    K1, _ = _kbar_forward(tables, combo, kf=kf, kappa_w=kappa_w)
    if not np.isfinite(K1):
        return float('nan')
    return (K1 - K0) / K0


def error_budget(tables, fits, lam_inf, sigma_lam_inf, combo,
                 temp_c=None, compensation=None, kappa_w=None,
                 stock_rel_pct=None, flask_ml=None, temp_fluct_k=None):
    """把 K° 的误差拆成可命名的几项，返回 dict。

    参数
    ----
    tables : {物种: solution_table 的行}，需含 c / kappa / kappa_corr /
        sigma_kappa。**四个物种都要**（组合式要用三个强电解质）。
    fits : 三种强电解质的 Kohlrausch 拟合结果（取 sigma_inf）
    lam_inf, sigma_lam_inf : 组合得到的 Λ∞(HAc) 及其标准误
    combo : 离子独立运动定律的组合 {'add': [...], 'sub': [...]}
    temp_c / compensation : 实测温度（℃）与仪器设定的补偿系数（%/℃）
    kappa_w : 去离子水电导率（S·m⁻¹）

    各项都由 :func:`_budget_forward` 的**数值扰动**给出（见该函数说明），
    不用手推的灵敏度系数。

    返回::

        {'ok': bool,
         'terms': [{'key','name','value'(相对 K 的分数),'pct','share',
                    'kind':'common'|'independent','detail'}, …],  # 按 value 降序
         'total'/'total_pct': 合成相对不确定度,
         'coef': {'kappa': 2+r̄, 'c': 1+r̄},   # 仅供参考，不参与合成
         'weights': {物种: 组合权重},
         'comp_cancel': bool,      # 温度补偿是否一阶抵消
         'lam_comp_pct': 温度补偿对**表6 各 Λ∞ 绝对值**的影响（%）
         'notes': [...]}

    退化情形（数据不齐、温度未填）时 ``ok`` 为 False，``notes`` 说明原因。
    **不抛异常**。
    """
    notes = []
    terms = []

    if not tables or 'HAc' not in tables:
        return dict(ok=False, terms=[], total=float('nan'),
                    total_pct=float('nan'),
                    notes=['缺少 HAc 数据，无法做 K° 的误差预算。'])
    # ⚠ 先查缺物种、再查 Λ∞ 是否可用：强电解质不齐时 Λ∞(HAc) 必然是 NaN
    # （组合式做不出来），若先查 Λ∞ 就只会得到「Λ∞ 不可用」这句笼统的话，
    # 读者看不出到底是缺了哪一瓶的数据。诊断信息要指向**可操作**的原因。
    missing = [k for k in STRONG_SPECIES if k not in tables]
    if missing:
        return dict(ok=False, terms=[], total=float('nan'),
                    total_pct=float('nan'),
                    notes=['强电解质数据不齐（缺 %s），组合式不成立，'
                           '无法做 K° 的误差预算。'
                           % '、'.join(SPECIES_LABEL.get(k, k) for k in missing)])
    if not np.isfinite(lam_inf) or lam_inf <= 0:
        return dict(ok=False, terms=[], total=float('nan'),
                    total_pct=float('nan'),
                    notes=['Λ∞(HAc) 不可用（拟合退化或浓度点太少），'
                           '无法做 K° 的误差预算。'])

    rows_h = [r for r in tables['HAc']
              if np.isfinite(r.get('c', np.nan)) and r['c'] > 0]
    if len(rows_h) < len(tables['HAc']):
        notes.append('HAc 有无法解析的浓度，已从预算中剔除对应瓶。')
    n = len(rows_h)
    if n < 2:
        notes.append('HAc 只有 %d 瓶有效数据，误差预算的说服力有限。' % n)

    if kappa_w is None:
        r0 = tables['HAc'][0]
        kappa_w = float(r0.get('kappa', 0.0)) - float(r0.get('kappa_corr', 0.0))

    stock_rel = (STOCK_REL_PCT if stock_rel_pct is None else float(stock_rel_pct))
    flask = (FLASK_VOLUME_ML if flask_ml is None else float(flask_ml))
    t_fluct = (TEMP_FLUCT_K if temp_fluct_k is None else float(temp_fluct_k))
    flask_tol = FLASK_TOL_ML.get(flask)
    if flask_tol is None:
        nearest = min(FLASK_TOL_ML, key=lambda v: abs(v - flask))
        flask_tol = FLASK_TOL_ML[nearest] * flask / nearest
        notes.append('定容体积 %.0f mL 不在容量瓶允差表内，按 %.0f mL 折算。'
                     % (flask, nearest))

    weights = _lambda_weights(fits, lam_inf, combo)
    order = conduct_order(combo)

    # ---- 灵敏度系数（只用于正文说明"为什么 κ 的影响约为 c 的两倍"）
    rs = [max(r['kappa_corr'], 0.0) / (r['c'] * lam_inf) for r in rows_h]
    rr = [a / (1.0 - a) for a in rs if a < 1.0]
    s_c = 1.0 + float(np.mean(rr)) if rr else float('nan')
    s_kap = 2.0 + float(np.mean(rr)) if rr else float('nan')

    def add(key, name, value, kind, detail):
        if value is None or not np.isfinite(value):
            return
        terms.append(dict(key=key, name=name, value=abs(float(value)),
                          kind=kind, detail=detail))

    # ---- (1) 拟合误差 Λ∞(HAc)
    # 每个物种的 Λ∞ 标准误按其自身相对大小扰动该物种的 κ（等价于扰动 Λ∞_s），
    # 再 RSS。这样权重、符号、瓶数全部由前向模型负责。
    fit_parts = []
    for k in order:
        if k not in fits or k not in weights:
            continue
        s = float(fits[k].get('sigma_inf', float('nan')))
        lim = float(fits[k].get('lam_inf', float('nan')))
        if not (np.isfinite(s) and np.isfinite(lim) and lim):
            continue
        eps = s / lim                       # 该物种 Λ∞ 的相对标准不确定度
        d = _budget_forward(tables, combo, per_species={k: eps}, kappa_w=kappa_w)
        if np.isfinite(d):
            fit_parts.append((k, eps, d))
    if fit_parts:
        v = float(np.sqrt(sum(d ** 2 for _k, _e, d in fit_parts)))
        lead = max(fit_parts, key=lambda t: abs(t[2]))
        add('fit', '拟合误差', v, 'common',
            'Λ∞(HAc) 由 %s 组合，权重 %s；主导项 %s（自身 %.2f%%、权重 %+.2f）'
            % ('、'.join(SPECIES_LABEL.get(k, k) for k in order),
               '、'.join('%s %+.2f' % (SPECIES_LABEL.get(k, k), weights[k])
                        for k in order if k in weights),
               SPECIES_LABEL.get(lead[0], lead[0]), lead[1] * 100,
               weights.get(lead[0], float('nan'))))
    else:
        notes.append('各物种 Λ∞ 的标准误不可用（浓度点太少），拟合项无法估计。')

    # ---- (2) 温度补偿：残差
    lam_comp_pct = float('nan')
    if temp_c is None or not np.isfinite(temp_c):
        notes.append('未填实验温度，温度补偿与温度波动两项无法估计。')
    elif compensation is None or not np.isfinite(compensation):
        notes.append('未填补偿系数，温度补偿项无法估计。')
    else:
        dT = T_REF_C - float(temp_c)
        eps = {}
        for k in SPECIES_ORDER:
            b = species_temp_coeff(k)
            eps[k] = ((b - float(compensation)) * dT / 100.0
                      if np.isfinite(b) else 0.0)
        d = _budget_forward(tables, combo, per_species=eps, kappa_w=kappa_w)
        add('comp', '温度补偿', d, 'common',
            '|25−T| = %.1f K，仪器按固定 %.2f %%/℃ 补偿而各物种真实 β = %s，'
            '残差代入后 ΔK/K = %+.3f%%'
            % (abs(dT), float(compensation),
               '、'.join('%s %.2f' % (SPECIES_LABEL.get(k, k),
                                      species_temp_coeff(k))
                        for k in SPECIES_ORDER
                        if np.isfinite(species_temp_coeff(k))),
               (d or 0.0) * 100))
        # 对**表6 各 Λ∞ 绝对值**的影响（与 K 的抵消无关，单列供正文引用）
        lam_comp_pct = max(abs(eps[k]) for k in STRONG_SPECIES
                           if k in eps) * 100 if eps else float('nan')

        # 温度波动：逐瓶独立
        b_h = species_temp_coeff('HAc')
        if np.isfinite(b_h):
            u = t_fluct * b_h / 100.0
            per = [('HAc', i, u) for i in range(len(tables['HAc']))]
            # 强电解质也随温度漂，一并计入（它们进 Λ∞）
            for k in order:
                bk = species_temp_coeff(k)
                if np.isfinite(bk):
                    per.extend((k, i, t_fluct * bk / 100.0)
                               for i in range(len(tables.get(k) or [])))
            d = _budget_forward(tables, combo, per_bottle=per, kappa_w=kappa_w)
            add('fluct', '温度波动', d, 'independent',
                '恒温槽波动 ±%.1f K，按各物种 β 折算为 κ 的随机波动，逐瓶独立'
                % t_fluct)

    # ---- (3) 溶液浓度（母液标定 + 容量瓶定容）：同一物种内为共同项
    u_flask = flask_tol / _TOL_DIVISOR / flask
    u_conc = float(np.sqrt((stock_rel / 100.0) ** 2 + u_flask ** 2))
    parts = []
    for k in SPECIES_ORDER:
        d = _budget_forward(tables, combo, per_species={k: u_conc},
                            kappa_w=kappa_w)
        if np.isfinite(d):
            parts.append(d)
    if parts:
        add('conc', '溶液浓度', float(np.sqrt(sum(x ** 2 for x in parts))),
            'common',
            '母液 %.1f%%（估计值）+ 容量瓶 %.0f mL 允差 ±%.2f mL → '
            'u(c)/c = %.3f%%；实际偏 f 倍时测到的 κ 也同比例偏大、而程序用的是'
            '名义 c，故按「κ 偏 f」传入'
            % (stock_rel, flask, flask_tol, u_conc * 100))

    # ---- (4) 移液管允差：逐瓶独立
    per = []
    detail = []
    vols = {}
    for k in SPECIES_ORDER:
        for j, v_ml in enumerate(_PREP_VOLUMES.get(k, [])):
            if v_ml <= 0:
                continue
            nom, tol = pipette_for(v_ml)
            u_rel = tol / _TOL_DIVISOR / v_ml
            vols[(k, j)] = dict(volume_ml=v_ml, nominal_ml=nom,
                                tol_ml=tol, u_rel=u_rel)
            detail.append((k, j, v_ml, nom, tol, u_rel))
        if k in tables and len(_PREP_VOLUMES.get(k, [])) == len(tables[k]):
            per.extend((k, i, vols[(k, i)]['u_rel'])
                       for i in range(len(tables[k])))
    if per:
        d = _budget_forward(tables, combo, per_bottle=per, kappa_w=kappa_w)
        worst = max(detail, key=lambda t: t[5]) if detail else None
        add('pip', '移液管允差', d, 'independent',
            '按讲义配制表的量取体积逐瓶取「能放出该体积的最小标称规格」的允差'
            '（GB/T 12807 A 类）；最大一项为量取 %.1f mL 用 %.1f mL 管'
            '（±%.3f mL，u = %.2f%%）'
            % (worst[2], worst[3], worst[4], worst[5] * 100) if worst else '')

    # ---- (5) 电导率读数：逐瓶独立
    per = []
    ur = []
    for i, r in enumerate(tables['HAc']):
        sk = float(r.get('sigma_kappa', float('nan')))
        if np.isfinite(sk) and r['kappa_corr'] > 0:
            per.append(('HAc', i, sk / r['kappa_corr']))
            ur.append(sk / r['kappa_corr'])
    if per:
        d = _budget_forward(tables, combo, per_bottle=per, kappa_w=kappa_w)
        add('read', '电导率读数', d, 'independent',
            '读数末位取 2（末位由量程分档决定，与记录几位小数无关），'
            '逐瓶 σ_κ/κ = %.2f%%~%.2f%%' % (min(ur) * 100, max(ur) * 100))

    # ---- 合成
    total = float(np.sqrt(sum(t['value'] ** 2 for t in terms))) if terms else float('nan')
    for t in terms:
        t['pct'] = t['value'] * 100.0
        t['share'] = (t['value'] ** 2 / total ** 2 * 100.0) if total else float('nan')
    terms.sort(key=lambda t: -t['value'])

    # 温度补偿是否一阶抵消：残差项远小于它对单个 Λ∞ 的影响，即为抵消
    comp_term = next((t for t in terms if t['key'] == 'comp'), None)
    comp_cancel = bool(
        comp_term and np.isfinite(lam_comp_pct) and lam_comp_pct > 0
        and comp_term['pct'] < 0.25 * lam_comp_pct)

    return dict(ok=bool(terms) and bool(np.isfinite(total)),
                terms=terms, total=total, total_pct=total * 100.0,
                coef=dict(c=s_c, kappa=s_kap),
                weights=weights, vols=vols,
                comp_cancel=comp_cancel, lam_comp_pct=lam_comp_pct,
                n=n, temp_c=temp_c, compensation=compensation,
                dT=(T_REF_C - float(temp_c))
                if (temp_c is not None and np.isfinite(temp_c)) else float('nan'),
                stock_rel=stock_rel, flask_ml=flask, flask_tol_ml=flask_tol,
                notes=notes)

#: 母液浓度（mol·dm⁻³），讲义「仪器和试剂」给的值。用于反推投配体积。
_STOCK_MOL_DM3 = {'NaCl': 0.25, 'NaAc': 0.25, 'HAc': 0.25, 'HCl': 0.1}
#: 讲义配制表里各物种的量取体积（mL）。强电解质的投配体积以这张表为准，
#: 因为报告正文的 c 就是按它配出来的——不要用「实测 c 反推」，那会把
#: 学生的配制误差当成名义值，误差分析就自证其是了。
_PREP_VOLUMES = {
    'NaCl': [10.0, 4.0, 2.0, 1.0, 0.5],
    'NaAc': [10.0, 4.0, 2.0, 1.0, 0.5],
    'HAc': [10.0, 4.0, 2.0, 1.0, 0.5],
    'HCl': [25.0, 12.0, 8.0, 5.0, 2.0],
}
