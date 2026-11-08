# -*- coding: utf-8 -*-
"""循环伏安法解析电极极化 —— 参数模型与一次完整计算。

界面、自检、报告生成都只跟这里的 :class:`Analysis` 打交道：
换参数就重建一个 Analysis 并 ``run()`` 一次，得到全部结果。
"""
from __future__ import annotations

import copy
import os
import re

import numpy as np

from . import echem

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

#: 电化学的候选数据目录（相对套件根）。顺序即优先级，越具体越靠前。
DATA_DIR_CANDIDATES = (
    # 课程原始数据（2025 参照数据；今年做完实验后在界面上改成自己的目录）
    os.path.join('物理化学实验', '物理化学实验', '电化学', 'chi的全部附件20251028'),
    os.path.join('物理化学实验', '物理化学实验', '电化学'),
    '电化学',                                                   # 精简布局
)


def _default_data_dir():
    from . import dataloc
    return dataloc.find_data_dir(_TOOL_DIR, extra=DATA_DIR_CANDIDATES,
                                 tool_subdirs=('样例数据',))


DEFAULT_DATA_DIR = _default_data_dir()

#: 7 个槽位：(配置键, 标签, 用途说明)。界面上的「数据文件映射」按这个顺序排。
FILE_SLOTS = (
    ('file_n2_blank', 'N₂ 空白（0.1 V·s⁻¹，也作扣空白基准）',
     '0.1 V·s⁻¹ 的 N₂ 饱和硫酸 CV，既是扫速系列的一员，也是所有扣空白的基准'),
    ('file_n2_02', 'N₂ 0.2 V·s⁻¹', '扫速系列：用于表 1 的峰电流-扫速关系'),
    ('file_n2_05', 'N₂ 0.5 V·s⁻¹', '扫速系列：用于表 1 的峰电流-扫速关系'),
    ('file_o2_fast', 'O₂ 快速搅拌', '通气 + 搅拌，还原电流最大'),
    ('file_o2_slow', 'O₂ 低速搅拌（ORR/DMFC 用）',
     '仅通气；ORR 起始还原电位与 DMFC 的阴极支都取自这里'),
    ('file_o2_still', 'O₂ 电解质静止', '不通气不搅拌，用来看溶液内 O₂ 耗尽后的极限'),
    ('file_meoh', '甲醇 + 硫酸', 'MOR 起始氧化电位与 DMFC 的阳极支'),
)

#: 槽位默认文件名 -> 配置键（顺序与 echem.DEFAULT_FILES 一致）
SLOT_KEYS = tuple(key for key, _label, _why in FILE_SLOTS)

#: 本实验认的数据后缀。**只有 .txt**：``echem`` 文档写明同目录的
#: ``.csv`` / ``_red.csv`` 是降采样副本、一律不用（以 .txt 为准）。
#: 把 csv 纳入候选会在原文件改名后"自动匹配"到数据不全的副本。
TXT_EXTS = ('.txt',)


# 平滑窗口 / 起始电位判据 / ESA 积分窗口的默认值（都可在界面上改）
DEFAULT_SMOOTH = 9            # 点（1 mV/点 → 9 mV）
DEFAULT_THRESHOLD_UA = 1.0    # μA，起始电位判据：扣空白信号越过该值
ESA_LO = -0.26                # 氢脱附峰积分下限（= Low E）
ESA_HI = 0.15                 # 积分上限（双电层起点）
DL_LO, DL_HI = 0.10, 0.20     # 自动双电层基线的平均窗口
I_MIN = 3e-8                  # DMFC 电流网格下限 A
I_STEP = 5e-8                 # DMFC 电流网格步长 A


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
        # ---- 数据与文件映射
        'data_dir': DEFAULT_DATA_DIR,
        'file_n2_blank': echem.DEFAULT_FILES['n2_blank'],
        'file_n2_02': echem.DEFAULT_FILES['n2_02'],
        'file_n2_05': echem.DEFAULT_FILES['n2_05'],
        'file_o2_fast': echem.DEFAULT_FILES['o2_fast'],
        'file_o2_slow': echem.DEFAULT_FILES['o2_slow'],
        'file_o2_still': echem.DEFAULT_FILES['o2_still'],
        'file_meoh': echem.DEFAULT_FILES['meoh'],
        # ---- 处理参数
        'smooth_window': DEFAULT_SMOOTH,
        'onset_threshold_uA': DEFAULT_THRESHOLD_UA,
        'esa_lo': ESA_LO,
        'esa_hi': ESA_HI,
        'esa_baseline_uA': None,      # None = 自动（双电层窗口平均）
        'dl_lo': DL_LO,
        'dl_hi': DL_HI,
        'i_min_uA': I_MIN * 1e6,      # DMFC 电流网格下限（μA）
        'i_step_uA': I_STEP * 1e6,    # DMFC 电流网格步长（μA）
    }


PERSIST_KEYS = (
    'student_name', 'student_id', 'group', 'group_no', 'date',
    'room_temp', 'pressure', 'data_dir',
    'file_n2_blank', 'file_n2_02', 'file_n2_05',
    'file_o2_fast', 'file_o2_slow', 'file_o2_still', 'file_meoh',
    'smooth_window', 'onset_threshold_uA',
    'esa_lo', 'esa_hi', 'esa_baseline_uA', 'dl_lo', 'dl_hi',
    'i_min_uA', 'i_step_uA',
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


# ---------------------------------------------------------------- 槽位解析
#: 槽位状态：界面上据此标「默认 / 手动指定 / 自动 NN% / 没找到 / 多候选」
SLOT_STATUS = ('default', 'manual', 'fuzzy', 'ambiguous', 'missing')

#: 「复制/重命名」的尾巴：`- 副本`、`(2)`、`_copy`。
#: **刻意不含 `_数字`**——在电化学里 `N2_1 / N2_2 / N2_5` 的 `_1/_2/_5` 是扫速标记
#: （0.1 / 0.2 / 0.5 V·s⁻¹），不是复制产物，剥掉就分不清三份数据了。
_COPY_TAIL_RE = re.compile(
    r'(?:\s*-\s*副本|\s*副本|\s*-\s*copy|\s*\(\d{1,2}\)|_copy)+$', re.IGNORECASE)

#: 时间戳前缀（与 dataloc.split_stamp 同口径：开头的日期/时间/分隔符）
_STAMP_TAIL_RE = re.compile(r'^[\s\d\-_.:/&+]*')


def slot_tail(rel):
    """文件名的**语义尾巴**：剥时间戳前缀与复制后缀，但保留 `_2` 这类尾号。

    `dataloc.split_stamp` 把 ``N2_2`` 尾部的 ``_2`` 当复制后缀剥掉（``A3-5(2)``、
    ``a_2`` 在紫外光谱那边确实是复制产物），于是 ``N2_1 / N2_2 / N2_5`` 的语义
    后缀全都变成 ``N2``、彼此无法区分——三个槽位会同时匹配到同一份数据，报告里
    两条互不相干的曲线用同一份文件算出来，数字全错却不报错。电化学的扫速标记
    正是这个尾号，所以这里单独算一份「不剥 _数字」的尾巴。
    """
    base = os.path.splitext(os.path.basename(str(rel or '')))[0]
    m = _STAMP_TAIL_RE.match(base)
    tail = base[m.end():] if m else base
    tail = tail.strip(' -_')
    tail = _COPY_TAIL_RE.sub('', tail).strip(' -_') or tail
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', tail.lower())


def _rank_for_slot(probe, files):
    """槽位候选：先按「语义尾巴完全一致」定位，再退回共享层的模糊打分。

    返回 ``(best_rel, best_score, why, suggestions)``。

    为什么不能只用 ``dataloc.rank_candidates``：见 :func:`slot_tail`。尾巴一致的
    候选如果只有一个，那就是它；如果有多个（``1/N2_2.txt`` 与 ``2/N2_2.txt``），
    分数会并列，交给调用方判成「多候选」让用户挑——绝不按路径字母序默选一份。
    """
    from . import dataloc
    tail = slot_tail(probe)
    exact = [f for f in files if tail and slot_tail(f) == tail] if tail else []
    if exact:
        scored = [{'rel': f, 'score': round(dataloc.match_score(probe, f), 4)}
                  for f in exact]
        # 同分时优先路径短的（不带子目录）、再按路径；仍然并列就都留着
        scored.sort(key=lambda d: (-d['score'], len(d['rel']), d['rel']))
        return scored[0]['rel'], scored[0]['score'], \
            '文件名尾部一致（%s）' % tail, scored[:6]
    ranked = dataloc.rank_candidates(probe, files, top=6)
    if not ranked:
        return None, 0.0, '没有相近的文件名', []
    return (ranked[0]['rel'], ranked[0]['score'], ranked[0]['why'],
            [{'rel': c['rel'], 'score': c['score']} for c in ranked])


def slot_target(cfg, key):
    """槽位当前登记的**目标文件名**：用户映射优先，否则用默认文件名。"""
    default = echem.DEFAULT_FILES[key.replace('file_', '')]
    return str(cfg.get(key) or default), default


def _abs_in(data_dir, rel):
    return os.path.normpath(rel if os.path.isabs(rel) else os.path.join(data_dir, rel))


def resolve_slots(data_dir, cfg, files=None):
    """7 个槽位 → 解析结果字典（``{槽位键: entry}``），**包含模糊匹配**。

    CHI 工作站导出的文件名每年不同，用户又常把整批文件改成语义化的名字，
    所以「登记的名字找不到」是常态而不是异常：

    * 登记的文件**确实存在** → ``default``（用户没改过）/ ``manual``（用户指定过）；
    * 不在但模糊匹配分数 ``≥ FUZZY_ACCEPT(0.80)`` → 自动采用，状态 ``fuzzy``，
      界面上标「自动 NN%」，用户能一眼看出这份不是他亲手选的；
    * 分数不够 → ``ambiguous``（有 ≥0.45 的候选）或 ``missing``，
      把候选一并带回去，界面上一键采用。

    **只在文件确实不存在时才做模糊匹配**：文件在就一定要用它——否则
    「用户明明选对了、程序却自己换了一份」会让报告数字和界面选择不一致。

    自动采用还要防「一份文件被两个槽位同时抢」：那样报告会用同一份数据算两条
    互不相干的曲线，数字全错却不报错。先按分数从高到低分配，被抢走的槽位
    退回候选列表。

    **候选只认 .txt**：``echem`` 文档写明同目录的 ``.csv`` / ``_red.csv`` 是
    降采样副本、一律不用（以 .txt 为准）。把它们纳入候选会让
    ``N2_1.txt`` 找不到时"自动匹配"到 ``N2_1.csv``——份量少一半的数据，
    算出来的峰电流和面积全错，界面上却显示匹配度 94%。
    """
    from . import dataloc
    data_dir = str(data_dir or '')
    has_dir = bool(data_dir) and os.path.isdir(data_dir)
    if files is None:
        files = list(dataloc.list_data_files(data_dir, exts=TXT_EXTS)) if has_dir else []
    else:
        files = [f for f in files if str(f).lower().endswith(TXT_EXTS)]

    detail, pending = {}, []
    for key in SLOT_KEYS:
        requested, default = slot_target(cfg, key)
        entry = {'key': key, 'requested': requested, 'default': default,
                 'rel': None, 'path': None, 'score': None,
                 'status': 'missing', 'suggestions': [], 'why': ''}

        # ① 登记的名字直接命中（echem.resolve_file 会先按相对路径再按 basename 找）
        path = echem.resolve_file(data_dir, requested) if has_dir else None
        if path:
            entry.update(path=os.path.normpath(path),
                         rel=requested if not os.path.isabs(requested) else None,
                         status='default' if requested == default else 'manual')
            detail[key] = entry
            continue

        if not has_dir:
            entry['why'] = '数据目录不存在'
            detail[key] = entry
            continue

        # ② 模糊匹配：先按登记的名字试，再按默认名字试（映射被改坏时仍能救回来）
        best, best_score, best_why, best_sugg = None, 0.0, '', []
        for probe in ([requested, default] if requested != default else [default]):
            probe_base = os.path.basename(probe) if os.path.isabs(probe) else probe
            rel, score, why, sugg = _rank_for_slot(probe_base, files)
            if sugg and not entry['suggestions']:
                entry['suggestions'] = sugg
            if rel and score > best_score:
                best, best_score, best_why = rel, score, why
        entry['score'] = best_score or None
        entry['why'] = best_why or '没有相近的文件名'
        if best and best_score >= dataloc.FUZZY_ACCEPT:
            entry['path'] = _abs_in(data_dir, best)
            entry['rel'] = best
            entry['status'] = 'pending-fuzzy'          # 下面统一分配后再定稿
            pending.append((best_score, key))
        else:
            entry['status'] = 'ambiguous' if entry['suggestions'] else 'missing'
            entry['path'] = _abs_in(data_dir, requested)   # 报错时好说清找的是什么
        detail[key] = entry

    # ③ 自动采用按分数从高到低分配，一份文件只归一个槽位
    taken = {}
    for score, key in sorted(pending, reverse=True):
        entry = detail[key]
        rel = entry['rel']
        if rel in taken:
            entry['status'] = 'ambiguous'
            entry['rel'] = None
            entry['path'] = _abs_in(data_dir, entry['requested'])
            entry['why'] = '候选文件已被「%s」占用' % dict(
                (k, lb) for k, lb, _w in FILE_SLOTS)[taken[rel]]
            continue
        taken[rel] = key
        entry['status'] = 'fuzzy'
    return detail


def unresolvable_slots(detail):
    """状态不是 default/manual/fuzzy 的槽位（计算时读不到文件的那几个）。"""
    return [v for k, v in (detail or {}).items()
            if v.get('status') not in ('default', 'manual', 'fuzzy')]


#: 槽位配置键 -> 显示名（告警里用）
_SLOT_LABELS = dict((key, label) for key, label, _why in FILE_SLOTS)


def _slot_label(key):
    """``'n2_blank'`` -> 界面上的中文槽位名。"""
    return _SLOT_LABELS.get(key, key)


def _num(v, default=0.0):
    try:
        if v in (None, ''):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


class Analysis:
    """一次完整的实验数据处理。"""

    def __init__(self, config):
        self.cfg = copy.deepcopy(config) if config else default_config()
        self.files = {}          # key -> CvFile
        self.slots = {}          # 'file_xxx' -> 槽位解析结果（含模糊匹配状态）
        self.warnings = []
        self.table1 = []
        self.esa = {}
        self.o2 = {}
        self.orr = {}
        self.mor = {}
        self.dmfc = {}

    # ------------------------------------------------------------ 主流程
    def run(self):
        cfg = self.cfg
        data_dir = cfg.get('data_dir') or DEFAULT_DATA_DIR
        self.data_dir = data_dir
        self.warnings = []

        w = int(_num(cfg.get('smooth_window'), DEFAULT_SMOOTH))
        thr = _num(cfg.get('onset_threshold_uA'), DEFAULT_THRESHOLD_UA) * 1e-6
        esa_lo = _num(cfg.get('esa_lo'), ESA_LO)
        esa_hi = _num(cfg.get('esa_hi'), ESA_HI)
        dl_lo = _num(cfg.get('dl_lo'), DL_LO)
        dl_hi = _num(cfg.get('dl_hi'), DL_HI)
        i_min = _num(cfg.get('i_min_uA'), I_MIN * 1e6) * 1e-6
        i_step = _num(cfg.get('i_step_uA'), I_STEP * 1e6) * 1e-6

        # 1) 读文件
        #    槽位解析含模糊匹配：登记的文件名找不到时，若候选分数 ≥0.80 自动采用
        #    （CHI 导出的文件名每年都变），并**明确告警**——报告里的数字与界面上
        #    显示的映射必须是同一份文件，不能让用户以为用的是默认名字。
        self.slots = resolve_slots(data_dir, cfg)
        for key in ('n2_blank', 'n2_02', 'n2_05',
                    'o2_fast', 'o2_slow', 'o2_still', 'meoh'):
            slot = self.slots.get('file_' + key) or {}
            status = slot.get('status')
            if status == 'fuzzy':
                self.warnings.append(
                    '「%s」的数据文件 %s 不在，已自动改用 %s（匹配度 %.0f%%，依据：%s）。'
                    '如不对，请在「数据文件映射」里改。'
                    % (_slot_label(key), slot['requested'], slot['rel'],
                       (slot['score'] or 0) * 100, slot.get('why') or ''))
            elif status in ('ambiguous', 'missing'):
                hint = ''
                if slot.get('suggestions'):
                    hint = '；找得到相近的：%s' % '、'.join(
                        x['rel'] for x in slot['suggestions'][:3])
                self.warnings.append('找不到数据文件：%s（在 %s 下）%s'
                                     % (slot['requested'], data_dir, hint))
                continue
            if not slot.get('path'):
                self.warnings.append('找不到数据文件：%s（在 %s 下）'
                                     % (slot['requested'], data_dir))
                continue
            try:
                self.files[key] = echem.load_cv(slot['path'])
            except (OSError, ValueError, IndexError) as exc:
                self.warnings.append('读取 %s 失败：%s' % (slot['path'], exc))
        if 'n2_blank' not in self.files:
            self.warnings.append('缺少空白 CV（N₂ 饱和硫酸，0.1 V·s⁻¹），无法扣空白')
            return self

        blank = self.files['n2_blank']
        v_blank = blank.v

        # 2) 表1：含氧物种脱附峰（负扫 S5，CHI 峰分析给出的相对基线峰高）
        for rate_label, key in echem.SCAN_RATES:
            f = self.files.get(key)
            if f is None:
                continue
            pk = self._oxide_peak(f)
            self.table1.append(dict(v=f.v, label=rate_label, **(pk or {})))
        self.table1.sort(key=lambda r: r['v'])

        # 3) 铂电化学活性面积（0.1 V·s⁻¹，S6 正扫氢脱附峰）
        s6 = blank.seg(6)
        base_cfg = cfg.get('esa_baseline_uA')
        baseline = (_num(base_cfg, None) * 1e-6 if base_cfg not in (None, '')
                    else echem.auto_dl_baseline(s6, dl_lo, dl_hi))
        A = echem.integrate_peak(s6[:, 0], s6[:, 1], esa_lo, esa_hi, baseline)
        Q = A / v_blank if v_blank else float('nan')
        area_cm2 = Q / echem.Q_H_MLAYER if np.isfinite(Q) else float('nan')
        self.esa = dict(A=A, Q=Q, baseline=baseline, lo=esa_lo, hi=esa_hi,
                        area_cm2=area_cm2, area_mm2=area_cm2 * 1e2,
                        v=v_blank)

        # 4) O₂ 系列：还原支（S5）叠加 + ORR 起始电位
        b5 = blank.seg(5)
        b6 = blank.seg(6)
        self.o2 = {}
        for cond, key, label in echem.O2_CONDITIONS:
            f = self.files.get(key)
            if f is None:
                continue
            E5, d5, d5s = echem.diff_vs_blank(f.seg(5), b5, w)
            self.o2[cond] = dict(label=label, file=f.name, v=f.v,
                                 E5=E5, d5=d5, d5s=d5s,
                                 cycle=f.cycle())
        if 'slow' in self.o2:
            E5, d5s = self.o2['slow']['E5'], self.o2['slow']['d5s']
            e_red, _ = echem.first_crossing(E5, d5s, thr, 'above',
                                            e_lo=0.0, e_hi=1.05)
            # 氧化支（S6 正扫）上还原电流消失的电势：用同一条低速搅拌曲线
            E6, _d6, d6s = echem.diff_vs_blank(self.files['o2_slow'].seg(6),
                                               b6, w)
            e_ox, _ = echem.last_crossing(E6, d6s, thr, e_lo=0.0, e_hi=0.95)
            self.orr = dict(onset_red=e_red, onset_ox=e_ox, threshold=thr,
                            E5=E5, d5=d5s, d5_raw=d5, cycle=self.o2['slow']['cycle'])
        else:
            self.orr['onset_red'] = float('nan')
            self.warnings.append('缺少 O₂ 低速搅拌数据，无法确定 ORR 起始还原电位')

        # 5) 甲醇：氧化支（S6）MOR 起始电位
        me = self.files.get('meoh')
        if me is not None:
            E6m, d6m, d6ms = echem.diff_vs_blank(me.seg(6), b6, w)
            e_mor, _ = echem.first_crossing(E6m, d6ms, thr, 'below',
                                            e_lo=-0.10, e_hi=0.60)
            self.mor = dict(onset=e_mor, threshold=thr,
                            E6=E6m, d6=d6ms, d6_raw=d6m, cycle=me.cycle())
        else:
            self.mor['onset'] = float('nan')
            self.warnings.append('缺少甲醇 CV 数据，无法确定 MOR 起始氧化电位')

        # 6) DMFC：扣空白 ORR（还原支）与 MOR（氧化支）量值曲线 → 极化 + 功率
        if np.isfinite(self.orr.get('onset_red', float('nan'))) and \
           np.isfinite(self.mor.get('onset', float('nan'))):
            orr_E = self.orr['E5']
            orr_i = np.abs(self.orr['d5'])
            mor_E = self.mor['E6']
            mor_i = np.abs(self.mor['d6'])
            # 只保留各自起始电位以内的工作区，且沿扫描方向截到电流峰顶
            # （主峰之后的下降沿若混进插值，E_cell 会在假交点提前变负）
            orr_m = (orr_E <= self.orr['onset_red'] + 0.02) & (orr_E >= -0.26)
            mor_m = (mor_E >= self.mor['onset'] - 0.02) & (mor_E <= 0.60)
            orr_E, orr_i = echem.rising_segment(orr_E[orr_m], orr_i[orr_m],
                                                tol=0.05e-6)
            mor_E, mor_i = echem.rising_segment(mor_E[mor_m], mor_i[mor_m],
                                                tol=0.05e-6)
            # 电流网格下限取两支路的最小电流（低于它插值会钳位，
            # 在 P–E 图上画出一段竖直假线）
            i_lo = max(i_min, float(np.min(orr_i)), float(np.min(mor_i)))
            res = echem.dmfc_curves(orr_E, orr_i, mor_E, mor_i,
                                    i_min=i_lo, i_step=i_step)
            if res is None:
                self.warnings.append('DMFC 工作区为空：请检查起始电位判据与平滑窗口')
            else:
                self.dmfc = res
        else:
            self.warnings.append('ORR / MOR 起始电位不齐，跳过 DMFC 计算')

        return self

    # ------------------------------------------------------------ 辅助
    def _oxide_peak(self, f):
        """负扫段（S5）上含氧物种还原峰：取 CHI 峰分析里 Ep 最接近 0.45 V 的那个。"""
        for seg_no in (5, 3, 1):
            lst = f.peaks.get(seg_no) or []
            cand = [p for p in lst if 0.2 <= p['Ep'] <= 0.7]
            if cand:
                p = min(cand, key=lambda p: abs(p['Ep'] - 0.45))
                return dict(Ep=p['Ep'], ip=p['ip'], seg=seg_no)
        return dict(Ep=float('nan'), ip=float('nan'), seg=0)

    def _slow_seg6(self):
        f = self.files.get('o2_slow')
        return f.seg(6) if f else None

    # ------------------------------------------------------------ 便捷
    def file(self, key):
        return self.files.get(key)
