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


# ---------------------------------------------------------------- 语义匹配
#: 每个槽位**真正在读什么**：体系族 + 区分该族内各份文件的那一个判据。
#:
#: 扫速 ``scan``：N₂ 那组的三份文件靠扫速区分（0.1 / 0.2 / 0.5 V·s⁻¹）；
#: 搅拌 ``cond``：O₂ 那组的三份靠搅拌条件区分（快速 / 低速 / 静止）；
#: MeOH 只有一个，族名本身就够。
SLOT_SPEC = {
    'file_n2_blank': {'family': 'n2', 'scan': 0.1},
    'file_n2_02': {'family': 'n2', 'scan': 0.2},
    'file_n2_05': {'family': 'n2', 'scan': 0.5},
    'file_o2_fast': {'family': 'o2', 'cond': 'fast'},
    'file_o2_slow': {'family': 'o2', 'cond': 'slow'},
    'file_o2_still': {'family': 'o2', 'cond': 'still'},
    'file_meoh': {'family': 'meoh'},
}

#: 体系关键词 → 族。顺序即优先级，**长的写前面**（``氮气`` 先于 ``氮``）。
_FAMILY_ALIAS = (
    ('meoh', ('甲醇', 'ch3oh', 'methanol', 'meoh')),
    ('n2', ('氮气', '氮', 'n2', 'n₂', 'nitrogen', '空白', 'blank')),
    ('o2', ('氧气', '氧', 'o2', 'o₂', 'oxygen', 'orr')),
)

#: 搅拌条件词 → 条件代号。``不搅拌`` 类**必须排在** ``高速/低速`` 之前判，
#: 否则「不搅拌」会被「搅拌」这一族吃掉，和「快速搅拌」同族同分。
_STIR_ALIAS = (
    ('still', ('不搅', '无搅', '未搅', '静止', '静置', 'still', 'static', 'nostir')),
    ('fast', ('快速', '高速', '强搅', '快搅', '剧烈', 'fast', 'strong')),
    ('slow', ('低速', '慢速', '缓慢', '弱搅', 'slow', 'weak', 'gentle')),
)

#: 取扫速线索前先剥掉的族关键词：否则 ``N2`` 里的 ``2`` 会被当成 0.2 V·s⁻¹。
_FAMILY_STRIP_RE = re.compile(
    r'(氮气|氮|氧气|氧|甲醇|ch3oh|methanol|meoh|nitrogen|n2|o2|orr)', re.IGNORECASE)

#: 本实验出现过的扫速（V·s⁻¹）；尾号 ``1/2/5`` 分别对应它们。
_SCAN_CHOICES = (0.1, 0.2, 0.5)


def _name_form(rel):
    """别名匹配用的名字：basename 去扩展名、去复制后缀、小写、去空白。

    **不剥时间戳前缀**——这一步只在需要时做。剥前缀的正则会吃掉开头的数字，
    而 ``0.2V.txt`` 这种名字的全部信息正是开头的数字（见 :func:`slot_tail`）。
    """
    base = os.path.splitext(os.path.basename(str(rel or '')))[0]
    base = _COPY_TAIL_RE.sub('', base).strip(' -_') or base
    return re.sub(r'\s+', '', base.lower())


def _scan_from_name(form):
    """文件名里的扫速线索；没有就 ``None``。

    认三种写法：``0.2``（直接写）、``200mV``、尾号 ``1/2/5``（= 0.1/0.2/0.5）。
    2025 参照数据是 ``N2_1/N2_2/N2_5``、用户今年的数据是 ``氮气1/2/5``，
    两种命名都是把扫速编进尾号。
    """
    text = _FAMILY_STRIP_RE.sub('', str(form or ''))

    def pick(v):
        for cand in _SCAN_CHOICES:
            if abs(v - cand) <= 0.011:
                return cand
        return None

    m = re.search(r'(?<![\d.])(0\.\d{1,2})(?![\d])', text)      # 0.2
    if m:
        got = pick(float(m.group(1)))
        if got:
            return got
    m = re.search(r'(\d{2,3})\s*mv', text)                      # 200mV
    if m:
        got = pick(float(m.group(1)) / 1000.0)
        if got:
            return got
    m = re.search(r'(\d{1,3})\s*$', text)                       # 尾号 10 → 0.1
    if m:
        got = pick(float(m.group(1)) / 100.0)
        if got:
            return got
    m = re.search(r'(?<![\d.])(\d)(?![\d.])', text)             # 尾号 1/2/5
    if m:
        return pick(float(m.group(1)) / 10.0)
    return None


def semantic_profile(rel):
    """文件名 → 语义画像 ``{'family','scan','cond',…}``。

    现实里 CHI 的文件名是使用者自己起的，中文命名极普遍：用户今年的数据是
    ``氮气1/氮气2/氮气5``、``快速搅拌/低速搅拌/不搅拌``、``CH3OH``，而槽位默认
    名是 ``N2_1 / O2_slow / MeOH``。纯字符串相似度只有 0.11~0.25，
    **七个槽位全部匹配不上**，「一键自动匹配」一个都填不进去。
    """
    form = _name_form(rel)
    prof = {'family': None, 'family_hit': '', 'scan': None, 'scan_src': '',
            'cond': None, 'cond_hit': ''}
    for fam, words in _FAMILY_ALIAS:
        hit = next((w for w in words if w in form), None)
        if hit:
            prof['family'], prof['family_hit'] = fam, hit
            break
    for cond, words in _STIR_ALIAS:
        hit = next((w for w in words if w in form), None)
        if hit:
            prof['cond'], prof['cond_hit'] = cond, hit
            break
    if prof['family'] is None and prof['cond']:
        # 只有 O₂ 那组做搅拌条件（N₂ 饱和实验全程静置），所以「搅拌」两个字
        # 本身就是 O₂ 这一组的标志。用户那份 `低速搅拌.txt` 就没写「氧气」。
        prof['family'], prof['family_hit'] = 'o2', prof['cond_hit']
    if prof['family'] == 'n2':
        # N₂ 组靠扫速区分，搅拌条件不参与（文件名叫「氮气不搅拌」也不影响）
        prof['cond'], prof['cond_hit'] = None, ''
        prof['scan'] = _scan_from_name(form)
        prof['scan_src'] = '文件名' if prof['scan'] else ''
    return prof


def build_semantic_index(data_dir, files):
    """``{相对路径: 语义画像}``；对 N₂ 组的文件额外读 CHI 文件头核对扫速。

    文件头里的 ``Scan Rate (V/s)`` 是仪器写下的**硬证据**：文件名可能叫
    ``氮气1`` 也可能叫 ``第一次``，但扫速骗不了人。读不出来（不是 CHI 格式、
    文件被占用）就退回文件名线索，绝不因此拒绝匹配。
    """
    index = {}
    for rel in files or ():
        prof = semantic_profile(rel)
        if prof['family'] == 'n2' and data_dir:
            params = {}
            try:
                params = echem.peek_params(_abs_in(data_dir, rel))
            except (OSError, ValueError):
                params = {}
            v = params.get('scan_rate')
            if v and v == v:                      # 排除 nan
                prof['scan'] = round(float(v), 4)
                prof['scan_src'] = 'CHI 文件头 Scan Rate'
        index[rel] = prof
    return index


def slot_score(key, probe, rel, index=None):
    """一个（槽位, 文件）的综合匹配度 → ``{'score','why','conflict'}``。

    三条判定，按证据强度从硬到软：

    1. **语义硬冲突**（``conflict``）：文件属于另一族，或族内判别量对不上
       （扫速 ≠ 该槽位要求的扫速、搅拌条件不符）。这时**字符串再像也不能自动
       采用**——一份 0.5 V·s⁻¹ 的数据填进 0.2 的槽位，报告里峰电流与活性面积
       全错，界面上却显示「匹配 95%」。
    2. **语义命中**：族对 + 判别量对 → 0.95，可直接自动采用。
    3. **只有族对**（缺判别线索）→ 0.55，进候选但不够自动采用，让用户挑。
       没有语义信息时退回 :func:`dataloc.match_score` 的纯字符串相似度。
    """
    from . import dataloc
    spec = SLOT_SPEC.get(key) or {}
    prof = (index or {}).get(rel) or semantic_profile(rel)
    str_s = dataloc.match_score(probe, rel) if probe else 0.0
    want_fam = spec.get('family')
    fam = prof.get('family')

    if want_fam and fam and fam != want_fam:
        return {'score': min(str_s, 0.5), 'conflict': True,
                'why': '是「%s」组的数据，不是这一组' % _FAMILY_LABEL.get(fam, fam)}
    if not want_fam or not fam:
        return {'score': str_s, 'why': '', 'conflict': False}

    why = '文件名含「%s」' % prof.get('family_hit')
    base = 0.55

    want_scan = spec.get('scan')
    if want_scan is not None:
        got = prof.get('scan')
        if got is None:
            return {'score': base, 'conflict': False,
                    'why': why + '，但看不出扫速'}
        if abs(got - want_scan) > 1e-6:
            return {'score': min(str_s, 0.5), 'conflict': True,
                    'why': '扫速 %.3g V·s⁻¹ ≠ 本槽位要求的 %.3g' % (got, want_scan)}
        src = prof.get('scan_src') or '文件名'
        return {'score': 0.95, 'conflict': False,
                'why': '%s，按%s判为扫速 %.3g V·s⁻¹' % (why, src, got)}

    want_cond = spec.get('cond')
    if want_cond is not None:
        got = prof.get('cond')
        if got is None:
            return {'score': base, 'conflict': False,
                    'why': why + '，但看不出搅拌条件'}
        if got != want_cond:
            return {'score': min(str_s, 0.5), 'conflict': True,
                    'why': '搅拌条件是「%s」，不是本槽位要的「%s」'
                           % (_COND_LABEL.get(got, got), _COND_LABEL.get(want_cond))}
        return {'score': 0.95, 'conflict': False,
                'why': '文件名为「%s」，搅拌条件「%s」'
                       % (prof.get('cond_hit') or '', _COND_LABEL[want_cond])}

    # meoh：族唯一，命中即可
    return {'score': 0.95, 'conflict': False, 'why': why}


_FAMILY_LABEL = {'n2': 'N₂ 饱和', 'o2': 'O₂ 还原', 'meoh': '甲醇氧化'}
_COND_LABEL = {'fast': '快速搅拌', 'slow': '低速搅拌', 'still': '不搅拌/静止'}


def _rank_for_slot(key, probe, files, index=None):
    """某个槽位的候选列表（分数降序）：语义判别 + 字符串相似度取长补短。

    返回 ``(best_rel, best_score, why, suggestions, tie)``。

    ``tie=True`` 表示**最高分有并列的不同文件**——这时绝不按路径字母序默选一份
    （那就是本项目反复踩过的「静默选错数据文件」），交给调用方判成多候选。

    为什么不能只用 ``dataloc.rank_candidates``：它的字符串口径会把 ``N2_1`` 与
    ``N2_2`` 判成 0.56（尾号被算成"多一个字符"），而这两份是**不同扫速**的数据。
    所以尾巴完全一致在这里算强证据（提到 0.80），但语义硬冲突优先。
    """
    from . import dataloc
    tail = slot_tail(probe)
    rows = []
    for f in files:
        d = slot_score(key, probe, f, index)
        s = d['score']
        if s <= 0:
            continue
        why = d['why']
        if tail and slot_tail(f) == tail and not d['conflict']:
            # 尾巴完全一致：强证据。但**有语义冲突时不许提分**，
            # 否则改名成 N2_5 的 0.5 V·s⁻¹ 数据会顶替 0.2 V·s⁻¹ 的槽位。
            if s < dataloc.FUZZY_ACCEPT:
                s = max(s, dataloc.FUZZY_ACCEPT)
            why = why or '文件名尾部一致（%s）' % tail
        rows.append({'rel': f, 'score': round(min(s, 1.0), 4), 'why': why})
    if not rows:
        ranked = dataloc.rank_candidates(probe, files, top=6)
        return (None, 0.0, '没有相近的文件名',
                [{'rel': c['rel'], 'score': c['score']} for c in ranked], False)

    # 同分时优先路径短的（不带子目录）、再按路径；并列另行标记
    rows.sort(key=lambda d: (-d['score'], len(d['rel']), d['rel']))
    tie = len(rows) > 1 and abs(rows[0]['score'] - rows[1]['score']) < 1e-6
    top = rows[0]
    return top['rel'], top['score'], top['why'], rows[:6], tie


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
    # 语义索引（含 CHI 文件头里的扫速）只建一次，七个槽位共用
    index = build_semantic_index(data_dir, files) if has_dir else {}

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
            # 名字命中就一定要用（用户明确选过，或是他自己起的默认名），
            # 但如果 CHI 文件头的扫速与该槽位要求的不符，要**说一声**：
            # 把 0.5 V·s⁻¹ 的数据改名成 N2_2.txt 是很自然的事，报告里
            # 峰电流-扫速关系就会有一条完全错位的点，而界面上看不出任何异常。
            entry['mismatch'] = _header_mismatch(key, entry.get('rel'), entry['path'])
            detail[key] = entry
            continue

        if not has_dir:
            entry['why'] = '数据目录不存在'
            detail[key] = entry
            continue

        # ② 模糊匹配：先按登记的名字试，再按默认名字试（映射被改坏时仍能救回来）。
        #    打分走 slot_score：语义（族 + 扫速/搅拌）优先，字符串相似度兜底。
        best, best_score, best_why, best_sugg, tie = None, 0.0, '', [], False
        for probe in ([requested, default] if requested != default else [default]):
            probe_base = os.path.basename(probe) if os.path.isabs(probe) else probe
            rel, score, why, sugg, tied = _rank_for_slot(key, probe_base, files, index)
            if sugg and not entry['suggestions']:
                entry['suggestions'] = sugg
            if rel and score > best_score:
                best, best_score, best_why, tie = rel, score, why, tied
        entry['score'] = best_score or None
        entry['why'] = best_why or '没有相近的文件名'
        if best and best_score >= dataloc.FUZZY_ACCEPT and not tie:
            entry['path'] = _abs_in(data_dir, best)
            entry['rel'] = best
            entry['status'] = 'pending-fuzzy'          # 下面统一分配后再定稿
            pending.append((best_score, key))
        else:
            entry['status'] = 'ambiguous' if entry['suggestions'] else 'missing'
            entry['path'] = _abs_in(data_dir, requested)   # 报错时好说清找的是什么
            if tie:
                entry['why'] = '有多个文件同样匹配（%s），请手动指定' % (
                    '、'.join(x['rel'] for x in entry['suggestions'][:3]))
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


def _header_mismatch(key, rel, path):
    """登记的文件已命中，但 CHI 文件头与槽位要求不符时返回一句说明，否则 ``''``。

    只对**有硬判据**的槽位做（扫速系列）；搅拌条件文件头里没有，只能靠文件名。
    这是告知性检查，不改变槽位状态——用户明确登记的文件永远优先使用。
    """
    want = (SLOT_SPEC.get(key) or {}).get('scan')
    if want is None or not path:
        return ''
    try:
        got = echem.peek_params(path).get('scan_rate')
    except (OSError, ValueError):
        return ''
    if not got or got != got:                      # None 或 nan
        return ''
    if abs(float(got) - want) <= 1e-6:
        return ''
    return ('文件 %s 的 CHI 文件头写的是扫描速率 %.3g V·s⁻¹，'
            '而本槽位应为 %.3g V·s⁻¹' % (rel or os.path.basename(path), got, want))


def unresolvable_slots(detail):
    """状态不是 default/manual/fuzzy 的槽位（计算时读不到文件的那几个）。"""
    return [v for k, v in (detail or {}).items()
            if v.get('status') not in ('default', 'manual', 'fuzzy')]


#: 用户从「文件清单」里点一行时，分数低于此值就不替他决定，让他自己挑。
#: 比 ``dataloc.FUZZY_SUGGEST``(0.45) 低——那是「值不值得列进候选」的门槛，
#: 这里是「敢不敢替你填」的门槛，两个问题不一样：鼠标点下去是明确的意图，
#: 只是不知道该填哪一格，所以宁可按最高分填、并在提示里写清匹配度让他核对。
ASSIGN_MIN_SCORE = 0.30


def rank_slots_for_file(rel, cfg, detail=None):
    """反查：用户点了文件 ``rel``，最该填给哪几个槽位（按分数降序）。

    解决的是 **「点击选择」全部派给第一个槽位** 的 bug（2026-11-09 用户报：
    「点击之后只会把数据派给 N₂ 空白」）。

    根因：前端原来的 ``assignToSlot()`` 只在每个槽位的 ``suggestions`` 里找这个
    文件。而 ``suggestions`` 是 ``resolve_slots`` **只在登记的文件名找不到时**
    才填的（见该函数 ② 分支），七个槽位全部 ``status='default'`` 时人人都是
    空数组 → 所有候选同分 0 → ``sc > bestScore`` 一次都不成立，``bestKey``
    停在遍历的第一个槽位 = ``file_n2_blank``（「N₂ 空白」）。于是点哪个文件都
    落到同一格，看起来「只会派给 N₂ 空白」。

    正确做法是**用与自动匹配完全同一套规则正向打分**：拿文件去比每个槽位的
    目标文件名（``slot_tail`` 优先，再退 ``dataloc.match_score``），谁分高给谁。
    这样界面上手动点选与「一键自动匹配」的判定口径一致，不会互相矛盾。

    返回 ``[{'key', 'label', 'score', 'why', 'current'}, …]``（分数降序）。
    空列表表示这份文件与任何槽位都不像，调用方应提示用户自己挑。
    """
    from . import dataloc
    rel = str(rel or '').strip().replace('\\', '/')
    if not rel:
        return []
    cfg = cfg or default_config()
    detail = detail or {}
    out = []
    for key, label, _why in FILE_SLOTS:
        requested, default = slot_target(cfg, key)
        probe = os.path.basename(requested) if os.path.isabs(requested) else requested
        # 与 _rank_for_slot / resolve_slots **完全同一条打分路径**：
        # 语义判别（族 + 扫速/搅拌，含 CHI 文件头）优先，字符串相似度兜底。
        scored = slot_score(key, probe, rel)
        score, why = scored['score'], scored['why']
        if scored['conflict']:
            why = '不匹配：' + why
        elif not why:
            tail = slot_tail(probe)
            if tail and slot_tail(rel) == tail:
                score = max(score, dataloc.FUZZY_ACCEPT)
                why = '文件名尾部一致（%s）' % tail
            else:
                why = ('文件名相同' if os.path.basename(probe) == os.path.basename(rel)
                       else '相似度 %.0f%%' % (score * 100))
        entry = detail.get(key) or {}
        out.append({
            'key': key,
            'label': label,
            'score': round(score, 4),
            'why': why,
            # 这个槽位**当前**登记的是哪个文件（前端据此说「原来是 X」）
            'current': entry.get('rel') or '',
        })
    out.sort(key=lambda d: (-d['score'], d['key']))
    return out


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
            if slot.get('mismatch'):
                # 名字命中但文件头对不上：不拦，但必须说清，否则表 1 会有一条错位点
                self.warnings.append('「%s」%s，请核对是否选错了文件。'
                                     % (_slot_label(key), slot['mismatch']))
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

        # 2) 表1：含氧物种脱附峰（负扫/还原支，CHI 峰分析给出的相对基线峰高）
        for rate_label, key in echem.SCAN_RATES:
            f = self.files.get(key)
            if f is None:
                continue
            pk = self._oxide_peak(f)
            self.table1.append(dict(v=f.v, label=rate_label, **(pk or {})))
        self.table1.sort(key=lambda r: r['v'])

        # 3) 铂电化学活性面积（0.1 V·s⁻¹，氧化支上的氢脱附峰）
        #    段号按电位方向自动判定：Init P/N = P 的数据氧化支在 S5 而不是 S6。
        s6 = blank.oxidative_seg()
        base_cfg = cfg.get('esa_baseline_uA')
        baseline = (_num(base_cfg, None) * 1e-6 if base_cfg not in (None, '')
                    else echem.auto_dl_baseline(s6, dl_lo, dl_hi))
        A = echem.integrate_peak(s6[:, 0], s6[:, 1], esa_lo, esa_hi, baseline)
        Q = A / v_blank if v_blank else float('nan')
        area_cm2 = Q / echem.Q_H_MLAYER if np.isfinite(Q) else float('nan')
        self.esa = dict(A=A, Q=Q, baseline=baseline, lo=esa_lo, hi=esa_hi,
                        area_cm2=area_cm2, area_mm2=area_cm2 * 1e2,
                        v=v_blank, seg=blank.pos_seg)

        # 4) O₂ 系列：还原支叠加 + ORR 起始电位
        b5 = blank.reductive_seg()
        b6 = blank.oxidative_seg()
        self.o2 = {}
        for cond, key, label in echem.O2_CONDITIONS:
            f = self.files.get(key)
            if f is None:
                continue
            E5, d5, d5s = echem.diff_vs_blank(f.reductive_seg(), b5, w)
            self.o2[cond] = dict(label=label, file=f.name, v=f.v,
                                 E5=E5, d5=d5, d5s=d5s,
                                 cycle=f.cycle())
        if 'slow' in self.o2:
            E5, d5s = self.o2['slow']['E5'], self.o2['slow']['d5s']
            # 起始还原电位 = 还原电流**开始出现**的地方。还原电流朝哪个方向
            # 偏，取决于 CHI 的 Polarity（cathodic_sign）。写死 'above' 时，
            # 极性反了的数据会得到 nan（整条曲线的差值全在阈值的另一侧）。
            cath = blank.cathodic_sign
            red_dir = 'above' if cath > 0 else 'below'
            e_red, _ = echem.first_crossing(E5, d5s, thr, red_dir,
                                            e_lo=0.0, e_hi=1.05)
            # 氧化支上还原电流消失的电势：同一条低速搅拌曲线。
            # 注意这里量的**还是还原电流**（只是换了扫描方向），所以判据方向
            # 与上面一致，不能取反——取反会让 2025 数据的 0.595 V 变成 nan。
            E6, _d6, d6s = echem.diff_vs_blank(self.files['o2_slow'].oxidative_seg(),
                                               b6, w)
            e_ox, _ = echem.last_crossing(E6, d6s, thr, direction=red_dir,
                                          e_lo=0.0, e_hi=0.95)
            self.orr = dict(onset_red=e_red, onset_ox=e_ox, threshold=thr,
                            E5=E5, d5=d5s, d5_raw=d5, cycle=self.o2['slow']['cycle'],
                            cathodic_sign=cath)
        else:
            self.orr['onset_red'] = float('nan')
            self.warnings.append('缺少 O₂ 低速搅拌数据，无法确定 ORR 起始还原电位')

        # 5) 甲醇：氧化支 MOR 起始电位
        me = self.files.get('meoh')
        if me is not None:
            E6m, d6m, d6ms = echem.diff_vs_blank(me.oxidative_seg(), b6, w)
            # 甲醇氧化是**阳极**过程，符号与阴极电流相反；极性反了的数据
            # 写死 'below' 会直接得到 nan（整条曲线都在阈值的另一侧）。
            anodic_dir = 'below' if blank.cathodic_sign > 0 else 'above'
            e_mor, _ = echem.first_crossing(E6m, d6ms, thr, anodic_dir,
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
        """负扫段上含氧物种还原峰：取 CHI 峰分析里 Ep 最接近 0.45 V 的那个。

        ⚠️ 段号**不再写死 S5**：CHI 的 ``Init P/N`` 决定段序，2025 数据是 N
        （还原支在 S5），用户 2026-11-11 那批是 P（还原支在 S6）。写死 S5 时
        那批数据的三行全是 nan，而界面上没有任何异常提示。
        """
        for seg_no in (f.neg_seg, f.neg_seg - 2, f.neg_seg - 4):
            if seg_no < 1:
                continue
            lst = f.peaks.get(seg_no) or []
            cand = [p for p in lst if 0.2 <= p['Ep'] <= 0.7]
            if cand:
                p = min(cand, key=lambda p: abs(p['Ep'] - 0.45))
                # ip 取**正值**（峰高的量值）：CHI 的 ip 带阴极符号，
                # Polarity 一反就成了负数，表 1 里印出负峰电流会让人以为数据坏了。
                return dict(Ep=p['Ep'], ip=abs(p['ip']), seg=seg_no)
        return dict(Ep=float('nan'), ip=float('nan'), seg=0)

    def _slow_seg6(self):
        f = self.files.get('o2_slow')
        return f.oxidative_seg() if f else None

    # ------------------------------------------------------------ 便捷
    def file(self, key):
        return self.files.get(key)
