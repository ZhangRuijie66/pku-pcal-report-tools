# -*- coding: utf-8 -*-
"""共享数据表（周三组《电导率测定实验数据记录表》）的解析与纠错。

**为什么单独一个模块**：共享表和本工具的 ``电导率数据.json`` 是**同构**的
——都是「一台仪器 + 一组实验条件 + 若干溶液各 5 个浓度点」。所以这里只做
「xlsx → N 份同构 data dict」，拆出来以后每个成员的 ``Analysis`` 都能原样
跑一遍，组内统计直接落在现成的拟合结果上，计算内核不需要知道共享表的存在。

表结构（一个仪器块 8 行，纵向排列 10 块）::

    第 1 行    实验日期：20261118
    块首行     仪器序号：1  实验者姓名：蔡瑞洲  室温(℃)：23.3  气压(kPa)：102.1
               电导池常数：1.012  去离子水电导率：1.993 uS/cm
    块首+1     表头：氯化钠溶液\\nNaCl | 浓度(mol/L) | 电导率测量值(μS/cm) 传感器温度(℃)
               醋酸钠溶液\\nNaAc | ... | 盐酸溶液\\nHCl | ... | 醋酸溶液\\nHAc | ...
               极限摩尔电导率 / S·m2·mol-1 | 不确定度
    块首+2..6  5 个浓度点：浓度 | κ | 传感器温度（三种溶液各占 3 列）
    块首+7     老师算好的 Λm∞ 与不确定度、HAc 的标准电离平衡常数

**列位置不写死**：靠表头里的物种名定位（``氯化钠溶液 / 醋酸钠溶液 / 盐酸溶液 /
醋酸溶液``，也认 ``NaCl / NaAc / HCl / HAc / NaNO3 / HNO3``），物种名列 +1 是
浓度、+2 是 κ、+3 是传感器温度。第 10 号仪器把 NaCl 换成了硝酸钠，靠位置写死
就会张冠李戴。

**读数纠错（用户 2026-11-20 定口径：按量级自动改正后纳入）**：
真实表里有 ``0.00283``（应为 2830 μS·cm⁻¹，差 6 个量级）、``'10.31E3'``
（文本型科学计数法）这类。处理方式是**先按同组同浓度的中位数定标，若比值
接近 10 的整数次幂就按该次幂改正并留痕**——不是"猜一个数"，而是把
「单位/量级写错」这一种可判定的错误修掉。

改不掉的（例如 259.8 应为 159.8 的数字笔误，比值 1.6 不是 10 的幂）**不动**，
交给 :func:`suspect_points` 用「同浓度组内偏离」与「κ 必须随 c 单调增」
两条物理判据标出来，报告里如实点名。替别人改数据是不可接受的。
"""
from __future__ import annotations

import math
import os

from . import conduct

#: 表头里物种名 → 内部键。长名优先匹配，避免「氯化钠」被「钠」抢先。
_SPECIES_ALIASES = (
    ('NaNO3', ('硝酸钠', 'NaNO3', 'NaNO₃')),
    ('NaCl', ('氯化钠', 'NaCl')),
    ('NaAc', ('醋酸钠', '乙酸钠', 'NaAc')),
    ('HCl', ('盐酸', 'HCl')),
    ('HAc', ('醋酸', '乙酸', 'HAc')),
)

#: 元信息标签 → 内部键。值取标签右边第一个非空单元格。
_INFO_ALIASES = (
    ('no', ('仪器序号',)),
    ('name', ('实验者姓名', '姓名')),
    ('room_temp', ('室温',)),
    ('pressure', ('气压', '大气压')),
    ('cell_constant', ('电导池常数',)),
    ('kappa_w_uS', ('去离子水电导率',)),
)

#: κ 的合理量级（μS·cm⁻¹）。超出就认为单位/量级写错，需要按 10 的幂纠正。
KAPPA_MIN = 1.0
KAPPA_MAX = 50000.0
#: 判定「差 10 的整数次幂」时允许的比值容差（对数空间）。
_MAG_TOL = 0.25          # |log10(ratio) - round(log10(ratio))| < _MAG_TOL


class SharedTableError(Exception):
    """共享表无法解析（不是这个格式、或一个仪器块都找不到）。"""


# ---------------------------------------------------------------- 基础取值
def _num(value):
    """单元格 → float；认不了返回 nan。

    要容忍的写法：``'10.31E3'``（文本型科学计数法）、``'±0.00197'``（带 ±
    的不确定度）、``' 4.40E-4'``（前后空格）。
    """
    if value is None:
        return float('nan')
    if isinstance(value, bool):
        return float('nan')
    if isinstance(value, (int, float)):
        v = float(value)
        return v if math.isfinite(v) else float('nan')
    text = str(value).strip().replace('±', '').replace(' ', '')
    if not text:
        return float('nan')
    # 全角正负号/乘号之类不影响 float()，但 '×10' 这种要挡掉
    try:
        return float(text)
    except ValueError:
        return float('nan')


def _text(value):
    return '' if value is None else str(value).strip()


def _species_of(text):
    """表头文本 → 内部物种键；认不出返回 None。"""
    t = text.replace('\n', '').replace('\r', '')
    for key, aliases in _SPECIES_ALIASES:
        for alias in aliases:
            if alias in t:
                return key
    return None


# ---------------------------------------------------------------- 定位
def _find_blocks(ws):
    """找出所有仪器块的首行行号（A 列含「仪器序号」的行）。"""
    rows = []
    for r in range(1, ws.max_row + 1):
        if '仪器序号' in _text(ws.cell(r, 1).value):
            rows.append(r)
    return rows


def _info_row(ws, row):
    """块首行：按标签取元信息。返回 (info dict, 用量)。"""
    info = {}
    for c in range(1, ws.max_column + 1):
        label = _text(ws.cell(row, c).value)
        if not label:
            continue
        for key, aliases in _INFO_ALIASES:
            if key in info:
                continue
            if any(a in label for a in aliases):
                # 值取右边第一个非空单元格。
                # ⚠ 空白块（4/9/10 号）的块首行除了「仪器序号：」什么都没填，
                # 右边第一个非空单元格会是下一列的标签「室温(℃)：」——于是
                # 「姓名」被读成「室温(℃)：」。凡是"值"位置上本身是标签的，
                # 一律当作没填（值不可能含「：」，标签一定含）。
                for cc in range(c + 1, min(c + 4, ws.max_column + 1)):
                    v = ws.cell(row, cc).value
                    if v is None or not _text(v):
                        continue
                    if '：' in _text(v) or ':' in _text(v):
                        break
                    info[key] = v
                    break
                break
    return info


def _header_map(ws, row):
    """表头行 → {物种: (浓度列, κ列, 温度列)}（1-based 列号）。

    按物种名定位而不是写死列：第 10 号仪器把 NaCl 换成了硝酸钠，
    写死列号会把硝酸钠的数据当成 NaCl 读进来。
    """
    out = {}
    for c in range(1, ws.max_column + 1):
        key = _species_of(_text(ws.cell(row, c).value))
        if key and key not in out:
            out[key] = (c + 1, c + 2, c + 3)
    return out


def _read_series(ws, row0, cols, n_rows):
    """读一个物种的 5 个点：返回 (conc, kappa, temp) 三个 list（原始量级）。"""
    ccol, kcol, tcol = cols
    conc, kappa, temp = [], [], []
    for i in range(n_rows):
        r = row0 + i
        conc.append(_num(ws.cell(r, ccol).value))
        kappa.append(_num(ws.cell(r, kcol).value))
        temp.append(_num(ws.cell(r, tcol).value))
    return conc, kappa, temp


def _teacher_values(ws, row0, n_rows):
    """块末老师算好的参考答案（只作交叉核对，不当权威）。

    布局：``Y=物种名, Z=Λm∞, AA=不确定度``，最后一行是
    ``Y=HAc的标准电离平衡常数``。
    """
    out = {'lam_inf': {}, 'k_hac': None}
    for i in range(n_rows + 3):
        r = row0 + i
        name = _species_of(_text(ws.cell(r, 25).value))
        lam = _num(ws.cell(r, 26).value)
        sig = _text(ws.cell(r, 27).value)
        if '电离' in _text(ws.cell(r, 25).value):
            out['k_hac'] = lam
        elif name and math.isfinite(lam):
            out['lam_inf'][name] = lam
        if sig:
            out.setdefault('sigma_raw', {})[name or 'k_hac'] = sig
    return out


# ---------------------------------------------------------------- 主解析
def parse_workbook(path_or_bytes):
    """解析共享数据表，返回 ``(members, meta)``。

    ``members`` 是 list，每项::

        {'no': 1, 'name': '蔡瑞洲', 'room_temp': 23.3, 'pressure': 102.1,
         'cell_constant': 1.012, 'kappa_w_uS': 1.993, 'row': 4,
         'solutions': {'NaCl': {'conc': [...], 'kappa': [...], 'temp': [...]}, ...},
         'teacher': {...}}

    κ 保持**原始量级**（未纠错）——纠错需要全组中位数，由
    :func:`correct_magnitudes` 在两遍处理里做。
    """
    try:
        import openpyxl
    except ImportError as exc:            # pragma: no cover
        raise SharedTableError('解析 xlsx 需要 openpyxl：%s' % exc)

    try:
        if isinstance(path_or_bytes, (bytes, bytearray)):
            import io
            wb = openpyxl.load_workbook(io.BytesIO(path_or_bytes), data_only=True)
        else:
            wb = openpyxl.load_workbook(path_or_bytes, data_only=True)
    except SharedTableError:
        raise
    except Exception as exc:              # noqa: BLE001
        # openpyxl 对非 xlsx 抛 InvalidFileException；文件不存在抛 OSError；
        # 加密/损坏的 xlsm 抛别的。统一转成 SharedTableError，让调用方能
        # 用一条 except 接住，也把「该给用户看什么话」收在这里。
        raise SharedTableError(
            '这个文件打不开（%s）。共享数据表应当是《电导率测定实验数据'
            '记录表》那份 .xlsx。' % exc) from exc

    members, meta = [], {'date': None, 'sheets': [], 'skipped': []}
    for ws in wb.worksheets:
        meta['sheets'].append(ws.title)
        # 实验日期在表格最上方（A 列「实验日期：」，值在右边）
        for r in range(1, min(6, ws.max_row + 1)):
            for c in range(1, min(6, ws.max_column + 1)):
                if '实验日期' in _text(ws.cell(r, c).value):
                    val = ws.cell(r, c + 1).value
                    if val is not None:
                        meta['date'] = _text(val)
                    break
            if meta['date']:
                break

        blocks = _find_blocks(ws)
        if not blocks:
            continue
        for idx, row0 in enumerate(blocks):
            info = _info_row(ws, row0)
            name = _text(info.get('name'))
            # 仪器序号：B 列不一定填，用「块序」兜底，空白块也能正确标成 4/9/10。
            no = _num(info.get('no'))
            if not math.isfinite(no):
                no = idx + 1
            if not name:
                # 空白块（4/9/10 号）：整块没填 NAME，跳过但留痕。
                meta['skipped'].append(int(no) if math.isfinite(no) else idx + 1)
                continue
            header = _header_map(ws, row0 + 1)
            if not header:
                raise SharedTableError(
                    '第 %s 号仪器（%s）的表头里找不到任何溶液名（氯化钠/醋酸钠/'
                    '盐酸/醋酸），这份 xlsx 可能不是《电导率测定实验数据记录表》。'
                    % (_text(info.get('no')) or idx + 1, name))
            # 仪器序号就是块序号（1..10）：表里 B 列不一定填。
            # 用「块序」而不是「B 列的值」当编号，空白块也能正确标成 4/9/10。
            no = _num(info.get('no'))
            if not math.isfinite(no):
                no = idx + 1
            # 数据行数：表头下一行到块末（下一个块首或表尾），最多 5 行有浓度
            tail = blocks[idx + 1] if idx + 1 < len(blocks) else ws.max_row + 1
            n_rows = 0
            for r in range(row0 + 2, tail):
                # 只要有一列浓度有值就算一条
                if any(math.isfinite(_num(ws.cell(r, cc).value))
                       for cc, _k, _t in header.values()):
                    n_rows += 1
            n_rows = min(n_rows, 5) or 5

            solutions = {}
            for key, cols in header.items():
                conc, kappa, temp = _read_series(ws, row0 + 2, cols, n_rows)
                solutions[key] = {'conc': conc, 'kappa': kappa, 'temp': temp}

            members.append(dict(
                no=no,
                name=name,
                row=row0,
                room_temp=_num(info.get('room_temp')),
                pressure=_num(info.get('pressure')),
                cell_constant=_num(info.get('cell_constant')),
                kappa_w_uS=_num(info.get('kappa_w_uS')),
                solutions=solutions,
                teacher=_teacher_values(ws, row0, n_rows),
            ))
    if not members:
        raise SharedTableError(
            '这份 xlsx 里没有找到任何填了姓名的仪器块。'
            '请确认它是《电导率测定实验数据记录表》（每台仪器一块，'
            'A 列写「仪器序号：」，C 列写「实验者姓名：」）。')
    members.sort(key=lambda m: (m['no'] if math.isfinite(m['no']) else 1e9, m['row']))
    return members, meta


# ---------------------------------------------------------------- 量级纠错
def _group_median(members, species, ci):
    """同一物种、同一浓度序号上，全组 κ 的中位数（忽略 nan）。"""
    vals = []
    for m in members:
        sol = m['solutions'].get(species) or {}
        kappa = sol.get('kappa') or []
        if ci < len(kappa) and math.isfinite(kappa[ci]) and kappa[ci] > 0:
            vals.append(kappa[ci])
    if not vals:
        return float('nan')
    vals.sort()
    n = len(vals)
    return vals[n // 2] if n % 2 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])


def correct_magnitudes(members):
    """把「差了 10 的整数次幂」的 κ 改正过来，返回改正记录 list。

    判据：与同组同浓度中位数的比值，其常用对数接近整数、且比值远离 1。
    这类错误只有两种来源——**单位抄错**（S·m⁻¹ 当 μS·cm⁻¹）或**小数点错位**，
    都属于可判定的记写错误，不是「猜数据」。

    比值不接近 10 的整数次幂的（数字笔误，如 259.8 应为 159.8）**不在这里改**：
    那是真值层面的错误，只能由数据主人确认，硬改就是伪造数据。
    """
    fixes = []
    for m in members:
        for species, sol in m['solutions'].items():
            kappa = sol.get('kappa') or []
            for ci, val in enumerate(kappa):
                if not math.isfinite(val) or val <= 0:
                    continue
                if KAPPA_MIN <= val <= KAPPA_MAX:
                    continue
                med = _group_median(members, species, ci)
                if not math.isfinite(med) or med <= 0:
                    continue
                ratio = med / val
                if ratio <= 0:
                    continue
                lg = math.log10(ratio)
                power = round(lg)
                if power == 0 or abs(lg - power) > _MAG_TOL:
                    continue
                new = val * 10.0 ** power
                if not (KAPPA_MIN <= new <= KAPPA_MAX):
                    continue
                kappa[ci] = new
                fixes.append(dict(
                    name=m['name'], no=m['no'], species=species, index=ci,
                    old=val, new=new, power=power,
                    reason='量级差 10^%d（同组同浓度中位数 %.4g）' % (power, med)))
    return fixes


def suspect_points(members, rel_tol=0.5):
    """标出**改不掉**的可疑读数：同浓度组内严重偏离，或破坏 κ–c 单调性。

    两条都是物理判据，不依赖"老师那一列"：

    1. **单调性**：同一物种内，κ 必须随 c 增大而增大。``256, 259.8, 111.1``
       里 259.8 > 256 就违反了（c 从 0.025 降到 0.01，κ 反而升）。
    2. **组内偏离**：某成员在某浓度上与同浓度中位数相差超过 ``rel_tol``
       （默认 50%），而其他人彼此都很接近。

    返回 list of dict：``{name, no, species, index, value, expect, why}``。
    """
    out = []
    for m in members:
        for species, sol in m['solutions'].items():
            kappa = sol.get('kappa') or []
            conc = sol.get('conc') or []
            finite = [(i, k) for i, k in enumerate(kappa) if math.isfinite(k)]
            # 1) 单调性：按浓度升序检查 κ 是否也升序
            ordered = sorted(((conc[i], kappa[i], i) for i, _k in finite
                              if math.isfinite(conc[i])),
                             key=lambda t: t[0])
            for (c1, k1, i1), (c2, k2, i2) in zip(ordered, ordered[1:]):
                if c2 > c1 and k2 < k1:
                    # 高浓度反而读数更低：两个里必有一个错，指向偏离组内更远的
                    for (c, k, i) in ((c1, k1, i1), (c2, k2, i2)):
                        med = _group_median(members, species, i)
                        if math.isfinite(med) and med > 0 and \
                                abs(k - med) / med > rel_tol:
                            out.append(dict(
                                name=m['name'], no=m['no'], species=species,
                                index=i, value=k, expect=med,
                                why='κ 随浓度非单调（c=%.4g 处 κ=%.4g，'
                                    '而更高浓度仅为 %.4g）；同浓度组内中位数 %.4g'
                                    % (c1, k1, k2, med) if i == i1 else
                                    'κ 随浓度非单调（c=%.4g 处 κ=%.4g）；'
                                    '同浓度组内中位数 %.4g' % (c, k, med)))
            # 2) 组内偏离（只在组内样本足够多时判）
            for i, k in finite:
                vals = []
                for other in members:
                    if other is m:
                        continue
                    osol = other['solutions'].get(species) or {}
                    ok = osol.get('kappa') or []
                    if i < len(ok) and math.isfinite(ok[i]) and ok[i] > 0:
                        vals.append(ok[i])
                if len(vals) < 3:
                    continue
                vals.sort()
                med = (vals[len(vals) // 2] if len(vals) % 2
                       else 0.5 * (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]))
                if med <= 0:
                    continue
                if abs(k - med) / med > rel_tol:
                    # 已经被单调性判据记过就不重复记
                    if any(o['name'] == m['name'] and o['species'] == species
                           and o['index'] == i for o in out):
                        continue
                    out.append(dict(
                        name=m['name'], no=m['no'], species=species, index=i,
                        value=k, expect=med,
                        why='与同浓度组内中位数 %.4g 相差 %.0f%%'
                            % (med, abs(k - med) / med * 100)))
    return out


# ---------------------------------------------------------------- 转 data
def to_data(member, base=None):
    """成员记录 → 与 ``电导率数据.json`` 同构的 data dict。

    ``base`` 提供缺省字段（例如 kcl 相关项共享表里没有，就用工具的默认值）。

    ⚠ **单位必须换算**：共享表按仪器和配制表的习惯，浓度写 mol·dm⁻³
    （0.025）、电导率写 μS·cm⁻¹（2830）；而工具内部一律存
    mol·m⁻³（25.0）与 S·m⁻¹（0.2830）。不换算的话 Λm = κ/c 会差 10⁷ 倍
    （实测把 0.0126 算成 128081），而结果看上去"还是个正常的数"，
    不会报错——这类错最难发现。
    """
    data = dict((base or {}).get('_defaults') or {})
    kappa_w = member.get('kappa_w_uS')
    data.update({
        'temp_c': member.get('room_temp'),
        'cell_constant': member.get('cell_constant'),
        'cell_constant_label': member.get('cell_constant'),
        # κw 这一项工具内部就按 μS·cm⁻¹ 存（字段名带 uS），不换算
        'kappa_w_uS': kappa_w,
    })
    # NOTE: 共享表只给了「电导池常数」（一个值），没有标定前后的两个读数，
    # 所以 kcl_label_uS / kcl_after_uS 保留 base 里的缺省（不编造读数）。
    solutions = {}
    for species, sol in member['solutions'].items():
        conc = [('%.6g' % (v * 1000.0)) if math.isfinite(v) else ''
                for v in sol['conc']]                      # mol·dm⁻³ → mol·m⁻³
        kappa = [('%.6g' % (v * 1e-4)) if math.isfinite(v) else ''
                 for v in sol['kappa']]                    # μS·cm⁻¹ → S·m⁻¹
        # 去掉尾部空点（不同成员的浓度档数可能不同）
        while conc and not conc[-1] and not kappa[-1]:
            conc.pop()
            kappa.pop()
        if conc:
            solutions[species] = {'conc': conc, 'kappa': kappa}
    data['solutions'] = solutions
    data['combo'] = dict(conduct.DEFAULT_COMBO)
    return data


def member_names(members):
    """``['1 蔡瑞洲', '2 郭晓文', ...]``：给界面下拉框用。"""
    out = []
    for m in members:
        no = m['no']
        tag = ('%d' % no) if math.isfinite(no) else '?'
        out.append('%s %s' % (tag, m['name']))
    return out


def _norm_name(s):
    """姓名归一化：去空格、全角转半角留白，便于模糊匹配。"""
    t = _text(s)
    for a, b in (('\u3000', ''), (' ', ''), ('\t', '')):
        t = t.replace(a, b)
    return t


def match_member(members, name):
    """按姓名认领「我的数据」；认不出返回 ``(None, 候选列表)``。

    优先完全匹配，其次「包含」匹配（表里写「张瑞杰」而档案写「张瑞杰 」）。
    认不出时把候选名单返回给界面，由用户手动选——**绝不猜**：
    猜错了整份报告的数据就成了别人的。
    """
    target = _norm_name(name)
    if not target:
        return None, list(range(len(members)))
    for i, m in enumerate(members):
        if _norm_name(m['name']) == target:
            return i, []
    hits = [i for i, m in enumerate(members)
            if target in _norm_name(m['name'])
            or _norm_name(m['name']) in target]
    if len(hits) == 1:
        return hits[0], []
    return None, hits or list(range(len(members)))