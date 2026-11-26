# -*- coding: utf-8 -*-
"""电解质溶液电导率的测定 —— 参数模型与一次完整计算。

界面、自检、报告生成都只跟这里的 :class:`Analysis` 打交道：
换参数就重建一个 Analysis 并 ``run()`` 一次，得到全部结果。

原始读数存放在 ``<data_dir>/电导率数据.json``（界面可编辑并保存）；
封面等偏好在 settings.json（PERSIST_KEYS）。
"""
from __future__ import annotations

import copy
import os

import numpy as np

from . import conduct

# 默认数据目录：**运行时推导**，不写死任何一台机器上的绝对路径。
# 可移植包解压到别人电脑上以后照样能跑：先找套件根下的 数据/，再找课程原始
# 数据目录（相对套件根，跟着包走），再找工具目录里的 样例数据/；都没有就退回
# 工具目录本身（目录一定存在，绝不会因为路径不存在抛 FileNotFoundError）。
# 优先级：settings.json / profile.json 里记住的 data_dir（由调用方先填进
#        cfg，见 server）＞ 本函数的推导结果。
#
# 定位逻辑统一走共享层 ``pcal/dataloc.py``（11 个模块共用一份），本文件只负责
# 说清「这个实验的数据还可能放在哪」——那几个相对套件根的候选目录。
_TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 电导率的候选数据目录（相对套件根）。顺序即优先级，越具体越靠前。
DATA_DIR_CANDIDATES = (
    # 课程原始数据（电导率数据.json 在 物理化学实验/物理化学实验/电导率/）
    os.path.join('物理化学实验', '物理化学实验', '电导率'),
    '电导率',                                                   # 精简布局
)


def _default_data_dir():
    from . import dataloc
    return dataloc.find_data_dir(_TOOL_DIR, extra=DATA_DIR_CANDIDATES,
                                 tool_subdirs=('样例数据',))


DEFAULT_DATA_DIR = _default_data_dir()

#: 本实验的数据文件名（手记读数，字符串存以保留末位 0）
DATA_FILENAME = conduct.DATA_FILENAME

STRONG_KEYS = conduct.STRONG_SPECIES


def _usable_combo(combo, fits):
    """校验数据文件里的 ``combo``，不可用就退回默认组合。

    ⚠ 为什么必须校验：``电导率数据.json`` 是**用户磁盘上的旧文件**，
    物种从 NaNO₃/HNO₃ 改成 NaCl/HCl 以后，老文件里的
    ``{"add": ["NaAc","HNO3"], "sub": ["NaNO3"]}`` 仍然指向已经不存在的物种，
    直接拿去 :func:`conduct.combo_lambda_inf` 会抛
    ``KeyError: 'HNO3'``——一个"数据没坏但配置文件旧了"的崩。

    判定标准是**参与组合的物种是否都算出来了**：少一个就整条组合式不成立，
    只能退回默认组合（而不是拿残缺的项硬加，那会得到错数）。
    """
    default = dict(conduct.DEFAULT_COMBO)
    if not isinstance(combo, dict):
        return default
    keys = list(combo.get('add') or []) + list(combo.get('sub') or [])
    if not keys or any(k not in fits for k in keys):
        return default
    return combo


def default_config():
    return {
        # ---- 封面
        'student_name': '',
        'student_id': '',
        'group': '',
        'group_no': '',
        'date': '',
        'room_temp': None,
        'pressure': None,
        # ---- 数据
        'data_dir': DEFAULT_DATA_DIR,
        # ---- 共享数据（周三组那台共享表）
        # 空串表示"这次不用共享数据"；给了路径就解析并做组内统计。
        # 不设默认路径：可移植包里本来就不附这门课的其他文件。
        'shared_path': '',
        # 「我的数据」：先按姓名自动认领（与个人档案的 student_name 比），
        # 认不出就用 shared_index 手动指定（0 基下标，None 表示没选）。
        'shared_index': None,
    }


PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'room_temp', 'pressure', 'data_dir', 'shared_path', 'shared_index',
)


def merge_saved(cfg, saved):
    if not saved:
        return cfg
    for k, v in saved.items():
        if k in PERSIST_KEYS and v is not None:
            cfg[k] = v
    return cfg


def default_config_with_saved(saved):
    return merge_saved(default_config(), saved)


class Analysis:
    """一次完整的实验数据处理。"""

    def __init__(self, config):
        self.cfg = copy.deepcopy(config) if config else default_config()
        self.warnings = []
        self.data = {}
        self.data_path = None
        self.ctx = {}
        self.tables = {}      # key -> 基本处理行
        self.fits = {}        # key -> Kohlrausch 拟合
        self.esa = None       # (Λm∞(HAc), σ)
        self.kmean = None
        self.kfit = None
        # ⚠ `lit_table`（表6 的文献对比表）原来只在 `compute()` 末尾赋值，
        # 而 `compute()` 在「强电解质数据不齐」时会**提前 return**（L182）。
        # 于是那份报告里 `an.lit_table` 根本不存在，`report.py` 取它
        # 直接 AttributeError（实测：删掉 NaAc 的数据 → 生成失败）。
        # 与 esa/kmean/kfit 一样，这里先给安全的默认值。
        self.lit_table = []
        # 共享数据的组内统计结果（``analyze_shared`` 挂在这里）；
        # 没读共享表时为 None，报告据此整节省略 4.2。
        self.shared = None

    # ------------------------------------------------------------ 主流程
    def run(self):
        cfg = self.cfg
        data_dir = cfg.get('data_dir') or DEFAULT_DATA_DIR
        self.data_dir = data_dir
        self.warnings = []

        self.data, self.data_path, data_warnings = conduct.load_data_ex(data_dir)
        self.warnings.extend(data_warnings)
        return self.compute()

    def compute(self):
        """在 ``self.data`` 已就位的前提下算出全部结果。

        抽出来是为了让**共享数据的每个成员**走完全相同的代码路径：
        组内统计必须用同一套口径，不能各写一份"差不多"的实现。
        """
        self.warnings = []
        self.ctx = conduct.prepare(self.data)

        sols = self.data.get('solutions', {})
        for key in conduct.SPECIES_ORDER:
            sol = sols.get(key)
            if not sol or not sol.get('kappa'):
                self.warnings.append('缺少 %s 的测量数据' % conduct.SPECIES_LABEL.get(key, key))
                continue
            rows = conduct.solution_table(sol, self.ctx['kappa_w'])
            if any(not np.isfinite(r['lam']) for r in rows):
                self.warnings.append('%s 数据里有无法解析的读数' % conduct.SPECIES_LABEL.get(key, key))
            self.tables[key] = rows
            if key in STRONG_KEYS:
                self.fits[key] = conduct.kohlrausch(rows)
                # 点数决定「能算什么」：2 点可定直线（Λm∞ 与 B 有精确解），
                # 但残差自由度 n−2 = 0，算不出不确定度。这类退化必须说出来，
                # 否则报告里 Λm∞ 有值、σ 却是「—」，读者会以为是打印问题。
                n_used = self.fits[key].get('n') or 0
                if n_used == 2:
                    self.warnings.append(
                        '%s 只有 2 个浓度点：Λm∞ 与 B 按两点连线给出（点估计精确），'
                        '但无法估计不确定度，报告里对应位置显示「—」。'
                        % conduct.SPECIES_LABEL.get(key, key))
                elif n_used < 2:
                    self.warnings.append(
                        '%s 的浓度点不足 2 个，无法拟合 Λm∞。'
                        % conduct.SPECIES_LABEL.get(key, key))

        missing = [k for k in STRONG_KEYS if k not in self.fits]
        if missing:
            self.warnings.append('强电解质数据不齐（%s），无法求 Λm∞(HAc)' %
                                 '、'.join(conduct.SPECIES_LABEL.get(k, k) for k in missing))
            return self

        combo = _usable_combo(self.data.get('combo'), self.fits)
        # 数据文件是**旧版物种口径**（NaNO₃/HNO₃）时要明说：老数据本身还能
        # 正常显示，但报告正文按 2026 讲义的新物种写，两者会不一致。
        # 静默沿用旧物种会让用户以为"怎么报告里写着 NaCl 而界面是 NaNO₃"。
        legacy = [k for k in (self.data.get('solutions') or {})
                  if k not in conduct.SPECIES_ORDER and k not in ('HAc',)]
        if legacy:
            self.warnings.append(
                '当前数据文件里还有旧物种（%s），而本版按 2026 秋讲义改用 '
                '%s。旧物种不会被用于计算与报告；如需作为本次实验的数据，'
                '请在左侧「测量数据」里按 NaCl / HCl 填新的读数并保存。'
                % ('、'.join(conduct.SPECIES_LABEL.get(k, k) for k in legacy),
                   ' / '.join(conduct.SPECIES_LABEL[k]
                              for k in conduct.STRONG_SPECIES)))
        lam_hac, sigma_hac = conduct.combo_lambda_inf(self.fits, combo)
        self.esa = dict(lam_inf=lam_hac, sigma=sigma_hac, combo=combo)

        # 文献对比表（表6）
        self.lit_table = []
        for key in conduct.SPECIES_ORDER:
            lam_exp = lam_hac if key == 'HAc' else self.fits[key]['lam_inf']
            sig = sigma_hac if key == 'HAc' else self.fits[key]['sigma_inf']
            theo = conduct.LAMBDA_THEO[key]
            self.lit_table.append(dict(
                key=key, exp=lam_exp, sigma=sig, theo=theo,
                er=conduct.er_percent(lam_exp, theo)))

        # 弱电解质
        if 'HAc' in self.tables and np.isfinite(lam_hac):
            rows = self.tables['HAc']
            self.kmean = conduct.k_from_mean(rows, lam_hac, sigma_hac)
            self.kfit = conduct.k_from_fit(rows, lam_hac, sigma_hac)
        else:
            self.warnings.append('缺少 HAc 数据或 Λm∞(HAc) 不可用，跳过 K° 计算')

        return self

    # ------------------------------------------------------------ 便捷
    def strong_keys(self):
        return list(STRONG_KEYS)

    def has(self, key):
        return key in self.tables

    # ------------------------------------------------------------ 共享数据
    def group_report(self, me_index=None):
        """组内统计（本工具只负责算"我这一份"）。

        共享表的解析与逐人计算都在 :func:`analyze_shared` 里；
        这里只是把"我"的 cfg 带进组内统计，便于 server 直接取用。
        """
        from . import groupstat
        return groupstat.group_analysis([], me_index=me_index)


def analyze_shared(path_or_bytes, base_cfg=None, me_name=None, me_index=None,
                   progress=None):
    """解析共享数据表 → 逐人跑一遍 → 组内统计。

    返回 dict::

        {'ok': True,
         'members': [{'no':…, 'name':…, 'is_me':bool, 'analysis':Analysis,
                      'lam':{…}, 'k':{…}}, …],
         'group': groupstat.group_analysis(...) 的返回值,
         'meta': {'date':…, 'skipped':[…], 'sheets':[…]},
         'fixes': [量级纠错记录], 'suspects': [改不掉的可疑点],
         'match': {'name': 用在档案里的名字, 'index': 认领到的下标,
                   'candidates': [候选…], 'auto': bool}}

    ``me_name`` 给了就按姓名自动认领；认不出（或给了 ``me_index``）
    交给界面手动选。**绝不猜**——认错了整份报告的数据就是别人的。
    """
    from . import groupstat, shared
    from . import conduct as _conduct

    members, meta = shared.parse_workbook(path_or_bytes)
    fixes = shared.correct_magnitudes(members)
    suspects = shared.suspect_points(members)

    # ---- 认领"我的数据"
    auto = False
    idx = None
    candidates = []
    if me_index is not None and 0 <= me_index < len(members):
        idx = int(me_index)
    elif me_name:
        idx, candidates = shared.match_member(members, me_name)
        auto = idx is not None
    if idx is None:
        candidates = candidates or list(range(len(members)))

    defaults = _conduct._deep_default()
    base_cfg = dict(base_cfg or default_config())
    out_members, results = [], []
    for i, m in enumerate(members):
        data = shared.to_data(m, {'_defaults': defaults})
        cfg = copy.deepcopy(base_cfg)
        # 共享表里有室温/气压，覆盖 cfg 里的封面值（各人自己的实验条件）
        if _isfinite(m.get('room_temp')):
            cfg['room_temp'] = m['room_temp']
        if _isfinite(m.get('pressure')):
            cfg['pressure'] = m['pressure']
        cfg['data_dir'] = '(共享数据表)'
        an = Analysis(cfg)
        an.data = data
        an.data_dir = '(共享数据表)'
        an.data_path = None
        try:
            an.compute()
        except Exception as exc:                      # noqa: BLE001
            # 某一个成员的数据坏了不该让整份组内统计失败
            an.warnings.append('该成员数据无法计算：%s' % exc)
        if progress:
            progress('%d/%d %s' % (i + 1, len(members), m['name']))
        rec = dict(no=m['no'], name=m['name'], is_me=(i == idx),
                   analysis=an,
                   lam={k: v for k, v in (an.fits or {}).items()},
                   lam_hac=(an.esa or {}).get('lam_inf'),
                   sigma_hac=(an.esa or {}).get('sigma'),
                   kmean=an.kmean, kfit=an.kfit)
        out_members.append(rec)
        results.append(dict(no=m['no'], name=m['name'], fits=an.fits or {},
                            lam_hac=rec['lam_hac'], sigma_hac=rec['sigma_hac'],
                            kmean=an.kmean, kfit=an.kfit))

    group = groupstat.group_analysis(results, me_index=idx)
    result = {
        'ok': True,
        'members': out_members,
        'group': group,
        'meta': meta,
        'fixes': fixes,
        'suspects': suspects,
        'match': {'name': me_name, 'index': idx, 'auto': auto,
                  'candidates': candidates,
                  'candidate_names': [shared.member_names(members)[i]
                                      for i in candidates]},
    }
    # 把共享结果挂到**本人**那个 Analysis 上，报告就能直接取用：
    #   an.shared = {..., 'group': …, 'members': …, 'fixes': …}
    # 只挂本人那份，避免"我的报告里混进别人的组内统计"这种混淆。
    if idx is not None and 0 <= idx < len(out_members):
        me_an = out_members[idx]['analysis']
        me_an.shared = result
    return result


def _isfinite(v):
    try:
        return v is not None and float(v) == float(v)
    except (TypeError, ValueError):
        return False
