# -*- coding: utf-8 -*-
"""有效数字与「值 ± 不确定度」的统一实现（canonical 源）。

遵循 JJF 1059.1-2012 + GB/T 8170-2008，用户 2026-09-21 确认的口径：

1. 测得值的末位必须与不确定度的末位对齐（硬要求）；
2. 不确定度取 2 位有效数字（用户选了「一律 2 位」）；
3. 修约用「四舍六入五成双」（ROUND_HALF_EVEN）；
4. 相对偏差也给 2 位有效数字。

⚠ 这 5 个函数原来在 11 个 report.py 里各抄一份，实测已经分化出 8 种行为：
   · 3 个模块的 pm() 会把 NaN 原样印成「nan ± 0.50」；
   · 6 个模块的 pct(nan) 返回 '0.0'（凭空造出一个「0 偏差」）；
   · pct(None) 在所有模块都抛 TypeError。
本文件是唯一源，由 _core/sync_core.py 同步到各工具 pcal/sigfig.py。

语义约定（与化学动力学/表面吸附那份一致，是原来的多数派）：
   x 或 u 为 None / 非有限 → 该位置输出 '—'，绝不印 'nan'。
"""
from __future__ import annotations

import decimal
import math

SIG_DIGITS = 2          # 不确定度取 2 位有效数字（用户口径）

DASH = '—'


def _finite(v):
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _is_zero(v):
    return v == 0


def _sig(x, n=SIG_DIGITS):
    """保留 n 位有效数字（四舍六入五成双）。x 为 0 或非有限时返回 0.0。"""
    x = float(x)
    if x == 0 or not math.isfinite(x):
        return 0.0
    d = decimal.Decimal(repr(x))
    q = decimal.Decimal(1).scaleb(d.adjusted() - n + 1)
    return float(d.quantize(q, rounding=decimal.ROUND_HALF_EVEN))


def _place(u, n=SIG_DIGITS):
    """不确定度 u 保留 n 位有效数字后的量级（10 的幂），用来对齐末位。"""
    return decimal.Decimal(repr(float(u))).adjusted() - n + 1


def _fix(x, exp):
    """把 x 修约到 10^exp 这一位。"""
    q = decimal.Decimal(1).scaleb(exp)
    return float(decimal.Decimal(repr(float(x))).quantize(
        q, rounding=decimal.ROUND_HALF_EVEN))


def _fmt(x, exp):
    return '%.*f' % (max(0, -exp), x)


def k(x, nd=1):
    """固定小数位（旧接口，保留兼容；新代码优先用 val/unc/pm）。"""
    if not _finite(x):
        return DASH
    return '%.*f' % (nd, float(x))


def sig_fig(x, n=4):
    """保留 n 位有效数字，**保留末尾的 0**（如 0.0121 → '0.01210'）。

    与 _sig 的区别：_sig 返回 float，末尾的 0 会丢；这里直接返回字符串，
    电导率报告的 κ/Λm 表要它（0.0300 不能变成 0.03）。
    """
    if x is None or not _finite(x):
        return DASH
    if x == 0:
        return '0'
    d = decimal.Decimal(repr(abs(float(x))))
    exp = d.adjusted()
    q = decimal.Decimal(1).scaleb(exp - n + 1)
    v = d.quantize(q, rounding=decimal.ROUND_HALF_EVEN)
    s = '%.*f' % (max(0, n - 1 - exp), v)
    return ('-' + s) if x < 0 else s


def val(x, u, n=SIG_DIGITS, fallback=3):
    """只给值，按 u 的末位修约。u 缺失时退化成 fallback 位小数。"""
    if not _finite(x):
        return DASH
    if u in (None, 0) or not _finite(u):
        return k(x, fallback)
    e = _place(u, n)
    return _fmt(_fix(x, e), e)


def unc(u, n=SIG_DIGITS):
    """只给不确定度，2 位有效数字。"""
    if u in (None, 0) or not _finite(u):
        return DASH
    e = _place(u, n)
    return _fmt(_fix(u, e), e)


def pm(x, u, n=SIG_DIGITS, unit='', fallback=3):
    """「值 ± 不确定度」，末位对齐（JJF 1059.1 要求）。

    unit     —— 只是拼在末尾的字符串（如 ' kJ·mol⁻¹'），不做格式化；
    fallback —— u 缺失时值保留几位小数（各模块口径不同：多数用 3，
                燃烧热/溶解热原来用 1，电导率用 4 位有效数字）。
    """
    if not _finite(x):
        return DASH
    if u in (None, 0) or not _finite(u):
        return k(x, fallback) + unit
    e = _place(u, n)
    return '%s ± %s%s' % (_fmt(_fix(x, e), e), _fmt(_fix(u, e), e), unit)


def pct(x, n=SIG_DIGITS, sign=''):
    """相对偏差，2 位有效数字。

    sign —— 后缀符号：电导率报告的 pct 输出带 '%'，其余模块不带。
    x 非有限时给 '—'（原来会印成 0）。

    x 恰为 0 时按 n 位小数输出（'0.00'），与 _fmt(_sig(0), _place(0)) 一致。
    """
    if not _finite(x):
        return DASH
    return _fmt(_sig(x, n), _place(x, n)) + sign


def sci(x, nd=3, exp=None):
    """科学计数法的普通文本写法：(1.23)×10^{4}。"""
    if not _finite(x):
        return DASH
    if exp is None:
        exp = int(math.floor(math.log10(abs(x)))) if x else 0
    m = float(x) / (10.0 ** exp)
    return '(%.*f)×10^{%d}' % (nd, m, exp)


def sci_pm(x, u, exp=-6):
    """(4.3 ± 0.1)×10^{-6} 形式。"""
    if not _finite(x):
        return DASH
    s = 10.0 ** exp
    if u in (None, 0) or not _finite(u):
        return '(%s)×10^{%d}' % (k(x / s, 2), exp)
    return '(%s)×10^{%d}' % (pm(x / s, u / s), exp)
