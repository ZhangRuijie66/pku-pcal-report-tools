# -*- coding: utf-8 -*-
"""共享数据的组内统计：一致性、异常值甄别、t 检验与 F 检验。

讲义「五、数据记录和处理」第（5）条要求「利用共享数据与自测实验数据进行
误差分析」，思考题还点明「如何利用共享数据对实验结果进行定量或半定量误差
分析」。本模块就提供这部分定量结果。

**只做统计，不碰数据**：调用方传进来的是各成员已经算好的结果（Λm∞、拟合
残差方差、K°），这里不重新读表也不必知道共享表长什么样。

三个统计量的口径（都要写进报告，否则读者会误读）：

* **组内一致性**：对同一物理量（如各人的 Λm∞(NaCl)）算均值、样本标准偏差
  ``s``（ddof=1）、相对标准偏差 ``RSD = s/mean``。n 是**人数**，不是测量次数
  ——不能用 σ/√n 当"组内不确定度"，因为那是「平均值的不确定度」，而这里要
  回答的是「组员之间差多少」。
* **Grubbs 异常值甄别**：单侧检验统计量 ``G = max|x_i - x̄| / s``，临界值按
  ``t_{α/(2n), n-2}`` 换算。**n < 3 时不做**（两个点的"s"没意义）。
  显著性水平默认 0.05。
* **t 检验**：把"我的值"与"其余组员均值"比较。因为"其余组员"本身也是估计，
  标准误要含它自己的抽样误差，故
  ``SE = s_others · √(1 + 1/(n-1))``，自由度 ``n-2``。
  这不是标准的单样本 t 检验——标准单样本 t 检验假设参考值是**真值**，
  而这里参考值是从有限样本估出来的。
* **F 检验**：比较"我的拟合残差方差"与"其余组员拟合残差方差"，
  ``F = s²_mine / s²_others``，检验的是**实验精度**（重复性）是否同一水平，
  与 Λm∞ 的**准确度**是两件事。这一点报告里必须分开讲。

外部依赖只有 scipy.stats（套件本来就装了 scipy）。
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

#: Grubbs 检验的显著性水平
GRUBBS_ALPHA = 0.05
#: 少于这么多人就不做离散度/异常值判定
MIN_N_STAT = 3


def _finite(values):
    out = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return np.asarray(out, float)


def describe(values):
    """一列数的均值 / 样本标准差 / RSD%。

    返回 dict；样本数不足时相应字段为 NaN（由上层显示「—」）。
    ``rsd`` 是百分数（0.35 表示 0.35%）。
    """
    v = _finite(values)
    n = int(v.size)
    if n == 0:
        return dict(n=0, mean=float('nan'), sd=float('nan'),
                    rsd=float('nan'), min=float('nan'), max=float('nan'))
    mean = float(v.mean())
    sd = float(v.std(ddof=1)) if n >= 2 else float('nan')
    rsd = (sd / abs(mean) * 100.0) if (n >= 2 and mean) else float('nan')
    return dict(n=n, mean=mean, sd=sd, rsd=rsd,
                min=float(v.min()), max=float(v.max()))


def grubbs(values, alpha=GRUBBS_ALPHA):
    """Grubbs 单侧异常值检验（只判**一个**最离群点）。

    返回 dict：``outlier_index``（在原 list 里的下标）、``outlier``（值）、
    ``g``、``g_crit``、``is_outlier``、``alpha``、``n``。

    n < 3 时 ``is_outlier`` 恒为 False（样本太少，谈不上离群）。
    判出异常值后**是否剔除**由调用方决定——这里只报告判据结果。
    """
    v = _finite(values)
    n = int(v.size)
    if n < MIN_N_STAT:
        return dict(n=n, outlier_index=None, outlier=float('nan'),
                    g=float('nan'), g_crit=float('nan'),
                    is_outlier=False, alpha=alpha)
    mean = v.mean()
    sd = v.std(ddof=1)
    if sd == 0:
        return dict(n=n, outlier_index=None, outlier=float('nan'),
                    g=0.0, g_crit=float('nan'), is_outlier=False, alpha=alpha)
    dev = np.abs(v - mean)
    k = int(np.argmax(dev))
    g = float(dev[k] / sd)
    t = float(stats.t.ppf(1.0 - alpha / (2.0 * n), n - 2))
    g_crit = (n - 1) / math.sqrt(n) * math.sqrt(t * t / (n - 2 + t * t))
    # 把下标映射回**原始** list 里（_finite 丢掉了 nan）
    raw = [i for i, x in enumerate(values)
           if x is not None and math.isfinite(float(x))]
    return dict(n=n, outlier_index=raw[k], outlier=float(v[k]), g=g,
                g_crit=float(g_crit), is_outlier=bool(g > g_crit), alpha=alpha)


def t_test_vs_group(mine, others):
    """我的单值 vs 其余组员的均值。

    ``SE = s_others·√(1 + 1/n_others)``（其余组员均值本身带抽样误差），
    自由度 ``n_others − 1``。返回 dict 含 ``t``、``p``（双侧）、``df``、
    ``diff``、``se``、``significant``（p < 0.05）。

    动机：讲义要求"共享数据与自测数据做误差分析"，而直接比"是否落在组内
    范围内"没有统计含义——组内本来就分散，落不落在范围内取决于人数。
    """
    o = _finite(others)
    n = int(o.size)
    m = float(mine)
    if n < 2 or not math.isfinite(m):
        return dict(t=float('nan'), p=float('nan'), df=n - 1 if n else 0,
                    diff=float('nan'), se=float('nan'),
                    others_mean=float(o.mean()) if n else float('nan'),
                    n_others=n, significant=False)
    s = float(o.std(ddof=1))
    se = s * math.sqrt(1.0 + 1.0 / n)
    if se == 0:
        return dict(t=float('nan'), p=float('nan'), df=n - 1,
                    diff=m - float(o.mean()), se=0.0,
                    others_mean=float(o.mean()), n_others=n,
                    significant=False)
    diff = m - float(o.mean())
    t = diff / se
    df = n - 1
    p = float(2.0 * (1.0 - stats.t.cdf(abs(t), df)))
    return dict(t=float(t), p=p, df=df, diff=diff, se=se,
                others_mean=float(o.mean()), n_others=n,
                significant=bool(p < 0.05))


def f_test_variance(s2_mine, s2_others, df_mine=3, df_others=None):
    """我的拟合残差方差 vs 其余组员（**精度**比较，不是准确度）。

    ``F = s²_mine / s²_others``，双侧 p。``df_mine`` 默认 3：一条 5 点直线
    拟合的残差自由度是 n−2 = 3。
    """
    a, b = float(s2_mine), float(s2_others)
    if not (math.isfinite(a) and math.isfinite(b)) or a <= 0 or b <= 0:
        return dict(F=float('nan'), p=float('nan'), df1=df_mine,
                    df2=df_others, significant=False)
    d2 = df_others if df_others is not None else df_mine
    F = a / b
    cdf = float(stats.f.cdf(F, df_mine, d2))
    p = float(2.0 * min(cdf, 1.0 - cdf))
    p = min(max(p, 0.0), 1.0)
    return dict(F=F, p=p, df1=df_mine, df2=d2,
                significant=bool(p < 0.05))


def paired_test(a, b):
    """配对比较两组数（例如同一批人的「求平均法 K°」与「拟合直线法 K°」）。

    返回 ``mean_diff``、``sd_diff``、``t``、``p``、``df``、``significant``。
    配对的关键是**同一成员的两法结果相减**再统计，这样才抵消掉"人与人之
    间的浓度配制差异"这个共同项。
    """
    va, vb = _finite(a), _finite(b)
    n = int(min(va.size, vb.size))
    if n < 2:
        return dict(n=n, mean_diff=float('nan'), sd_diff=float('nan'),
                    t=float('nan'), p=float('nan'), df=n - 1,
                    significant=False)
    d = va[:n] - vb[:n]
    md = float(d.mean())
    sd = float(d.std(ddof=1))
    if sd == 0:
        return dict(n=n, mean_diff=md, sd_diff=0.0, t=float('nan'),
                    p=float('nan'), df=n - 1, significant=False)
    t = md / (sd / math.sqrt(n))
    p = float(2.0 * (1.0 - stats.t.cdf(abs(t), n - 1)))
    return dict(n=n, mean_diff=md, sd_diff=sd, t=float(t), p=p, df=n - 1,
                significant=bool(p < 0.05))


# ---------------------------------------------------------------- 汇总
def group_analysis(members_results, me_index=None):
    """把各成员的 ``Analysis`` 结果汇总成组内统计。

    ``members_results``：list of dict，每项至少含::

        {'no': 1, 'name': '蔡瑞洲',
         'fits': {'NaCl': {'lam_inf':…, 'sigma_inf':…, 's2':…}, …},
         'lam_hac': …, 'sigma_hac': …, 'kmean': …, 'kfit': …, }
        # kmean/kfit 可以是 dict 或纯 float

    ``me_index``：哪一项是"我"。给了就额外算 t 检验 / F 检验；
    没给（或为 None）就只出组内一致性统计。

    返回 dict::

        {'n': 7, 'names': [...], 'me': {...} or None,
         'species': {'NaCl': {'lam_inf': describe, 'grubbs': grubbs}, ...},
         'lam_hac': {'describe':…, 'grubbs':…},
         'k_methods': {'mean': describe, 'fit': describe,
                       'paired': paired_test(...)},
         'tests': {'NaCl': {'t':…, 'F':…}, ...}}
    """
    rows = [r for r in (members_results or []) if r]
    names = ['%s %s' % (int(r['no']) if r.get('no') is not None else '?',
                        r.get('name') or '')
             for r in rows]
    out = {'n': len(rows), 'names': names, 'me': None,
           'species': {}, 'lam_hac': None, 'k_methods': None, 'tests': {}}
    if not rows:
        return out

    species_keys = []
    for r in rows:
        for k in (r.get('fits') or {}):
            if k not in species_keys:
                species_keys.append(k)
    # 报告里要按 NaCl / NaAc / HCl 的固定顺序出表，不按 dict 巧合顺序
    from . import conduct
    species_keys.sort(key=lambda k: conduct.SPECIES_ORDER.index(k)
                      if k in conduct.SPECIES_ORDER else 99)

    for key in species_keys:
        vals, s2s = [], []
        for r in rows:
            f = (r.get('fits') or {}).get(key) or {}
            vals.append(f.get('lam_inf'))
            s2s.append(f.get('s2'))
        out['species'][key] = {
            'lam_inf': describe(vals),
            'grubbs': grubbs(vals),
            'values': vals,
            's2': describe(s2s),
            's2_values': s2s,
        }

    hac_vals = [r.get('lam_hac') for r in rows]
    out['lam_hac'] = {'describe': describe(hac_vals),
                      'grubbs': grubbs(hac_vals), 'values': hac_vals}

    def _kval(item, key):
        v = item.get(key)
        if isinstance(v, dict):
            return v.get('mean') if key == 'kmean' else v.get('K')
        return v

    km = [_kval(r, 'kmean') for r in rows]
    kf = [_kval(r, 'kfit') for r in rows]
    out['k_methods'] = {
        'mean': describe(km), 'fit': describe(kf),
        'mean_values': km, 'fit_values': kf,
        'paired': paired_test(km, kf),
    }

    # ---- "我" vs 其余组员
    if me_index is not None and 0 <= me_index < len(rows):
        me = rows[me_index]
        others = [r for i, r in enumerate(rows) if i != me_index]
        out['me'] = {'no': me.get('no'), 'name': me.get('name')}
        for key in species_keys:
            mine_f = (me.get('fits') or {}).get(key) or {}
            others_lam = [((r.get('fits') or {}).get(key) or {}).get('lam_inf')
                          for r in others]
            others_s2 = [((r.get('fits') or {}).get(key) or {}).get('s2')
                         for r in others]
            t = t_test_vs_group(mine_f.get('lam_inf'), others_lam)
            ov = _finite(others_s2)
            s2_pooled = float(ov.mean()) if ov.size else float('nan')
            # 其余组员的合并残差自由度：每人 1 条 5 点直线 → 3
            df_others = 3 * int(ov.size) if ov.size else 3
            f = f_test_variance(mine_f.get('s2'), s2_pooled,
                                df_mine=3, df_others=df_others)
            out['tests'][key] = {'t': t, 'F': f,
                                 'mine': mine_f.get('lam_inf'),
                                 's2_mine': mine_f.get('s2')}
        # HAc 的 Λm∞ 是组合量，也做一次 t 检验
        out['tests']['HAc'] = {
            't': t_test_vs_group(me.get('lam_hac'),
                                 [r.get('lam_hac') for r in others]),
            'F': None, 'mine': me.get('lam_hac'), 's2_mine': None}
        # K° 两法：我 vs 其余
        out['k_tests'] = {
            'mean': t_test_vs_group(_kval(me, 'kmean'),
                                    [_kval(r, 'kmean') for r in others]),
            'fit': t_test_vs_group(_kval(me, 'kfit'),
                                   [_kval(r, 'kfit') for r in others]),
        }
    return out