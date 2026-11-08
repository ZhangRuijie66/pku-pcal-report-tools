# -*- coding: utf-8 -*-
"""紫外可见吸收光谱仪搭建实验 —— 数据读取与计算内核。

数据来源
--------
课程光谱仪软件导出的 txt，四列制表符分隔：

    index    original    background    difference

· ``original``   —— CCD 原始计数（含暗电流）
· ``background`` —— 软件当前使用的暗背景（可能与本次积分的暗背景不一致）
· ``difference`` —— ``original - background``；本工具一律用它当光强信号

仪器参数（自建光谱仪，元件参数见讲义附录 1）：

· CCD 3648 像素，波长范围随 CCD 位置改变；
· 光栅 600  groove/mm，闪耀波长 500 nm；
· 氘灯 DD2.5A 特征谱线 238.30 / 485.82 / 581.39 / 656.06 nm（用于标定）。

计算链
------
    标定（氘灯三条线 → λ = a·pixel + b）
      → A(λ) = lg(I0/I)（I0 为同条件乙醇空白）
      → 平滑（移动平均）
      → 线性基线（在吸收带两侧取两个锚点）
      → Voigt 分峰拟合（1~2 个组元 + 线性基线）→ 总峰位置 λmax 与吸光度 A
      → ε = A/(c·b)
      → Beer-Lambert 线性拟合（只取线性区，图上仍画出全部数据点）
      → 一维势箱模型验证
"""
from __future__ import annotations

import os
import re

import numpy as np

# 氘灯（DD2.5A）的特征谱线；汞灯备用（讲义里也给了）
DEUTERIUM_LINES = (485.82, 581.39, 656.06)
DEUTERIUM_LINES_ALL = (238.30, 485.82, 581.39, 656.06)
MERCURY_LINES = (253.7, 404.7, 435.8, 546.1, 577.0, 579.0)

# 一维势箱：λ(nm) = K·L(nm)²/(2n+1)，K = 8·m_e·c/h
BOX_K = 3297.8

# 移动平均窗口（数据点）。1 = 不做平滑：吸收光谱用原始数据直接拟合，
# 平滑会把峰顶压平、把 λmax 拉偏（A4 的 A 差 0.0023、B2 差 0.0046）。
DEFAULT_SMOOTH = 1
DEFAULT_STRAY = 0.0         # 杂散光占入射光强的比例（0 = 不校正）
PATH_LENGTH_CM = 1.00       # 比色皿光程

# 分子登记表
#   conc  —— 该分子在「其余分子吸收光谱」表里使用的浓度（μmol·L⁻¹）
#   i     —— 一维势箱模型里 C-C=C 基团的个数（A 组 1~4；B 组给的是范围）
#   band  —— 主吸收带所在波长范围（nm），用于基线锚点与寻峰
MOLECULES = {
    'A1': dict(name='3,3′-二乙基硫菁碘盐', short='硫菁', conc=10.0, group='A', i=1,
               band=(380, 520), structure='结构A1.png', source='氘灯'),
    'A2': dict(name='3,3′-二乙基噻碳菁碘化物', short='噻碳菁', conc=5.0, group='A', i=2,
               band=(480, 650), structure='结构A2.png', source='卤钨灯'),
    'A3': dict(name='3,3′-二乙基硫二羰花青碘', short='二羰花青', conc=5.0, group='A', i=3,
               band=(540, 740), structure='结构A3.png', source='卤钨灯'),
    'A4': dict(name='3,3′-二乙基硫杂三羰花青碘化物', short='三羰花青', conc=3.0, group='A', i=4,
               band=(620, 860), structure='结构A4.png', source='卤钨灯'),
    'B1': dict(name='β-胡萝卜素', short='β-胡萝卜素', conc=10.0, group='B', i=(10, 11),
               band=(380, 540), structure='结构B1.png', source='氘灯'),
    'B2': dict(name='2,6-二甲基-2,4,6-辛三烯', short='辛三烯', conc=30.0, group='B', i=(2, 3),
               band=(250, 360), structure='结构B2.png', source='氘灯'),
}

# 三次标定：每次的默认线性系数来自操作者 Origin 工程里保存的拟合结果，
# 作为「先验」；工具会在先验附近重新找峰并重算，偏差过大时退回先验。
CALIBRATIONS = [
    dict(key='d1_long', label='长波范围（第一周 10-14）', day=1, short='第一周长波',
         file='2026-10-14 & 17-01-51-氘灯.txt',
         prior=(0.12586983766424498, 421.9949599219326)),
    dict(key='d2_long', label='长波范围（第二周 10-21）', day=2, short='第二周长波',
         file='2026-10-21 & 13-36-23-1到3的校准.txt',
         prior=(0.12568477103070347, 422.34476038618209)),
    dict(key='d2_short', label='短波范围（第二周 10-21）', day=2, short='第二周短波',
         file='4\\2026-10-21 & 13-44-43-4的校准.txt',
         prior=(0.12758568846992188, 258.30852586769021)),
]

# 测量登记表。key 唯一；mol 指向 MOLECULES；series 标记用途。
#   sample / blank 均为相对于数据目录的路径
A3_OFF = '2\\2026-10-21 & 12-56-02-A3-0.txt'      # A3 浓度系列的空白（乙醇）
SAMPLES = [
    # ---- 第一周：A4
    dict(key='A4', mol='A4', kind='molecule', day=1, cal='d1_long', conc=3.0,
         sample='2026-10-14 & 17-05-15-A4-3.txt',
         blank='2026-10-14 & 17-11-53-A4-乙醇.txt', source='卤钨灯'),
    # ---- 第二周：A3 浓度系列（文件夹 2，长积分）
    dict(key='A3c0.5', mol='A3', kind='conc', day=2, cal='d2_long', conc=0.5,
         sample='2\\2026-10-21 & 12-29-42-A3-0.5.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c1', mol='A3', kind='conc', day=2, cal='d2_long', conc=1.0,
         sample='2\\2026-10-21 & 12-33-43-A3-1.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c5', mol='A3', kind='conc', day=2, cal='d2_long', conc=5.0,
         sample='2\\2026-10-21 & 12-36-40-A3-5.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c10', mol='A3', kind='conc', day=2, cal='d2_long', conc=10.0,
         sample='2\\2026-10-21 & 12-40-17-A3-10.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c20', mol='A3', kind='conc', day=2, cal='d2_long', conc=20.0,
         sample='2\\2026-10-21 & 12-43-5-A3-20.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c20b', mol='A3', kind='conc_rep', day=2, cal='d2_long', conc=20.0,
         sample='2\\2026-10-21 & 12-45-38-A3-20-2.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c50', mol='A3', kind='conc', day=2, cal='d2_long', conc=50.0,
         sample='2\\2026-10-21 & 12-49-34-A3-50.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c50b', mol='A3', kind='conc_rep', day=2, cal='d2_long', conc=50.0,
         sample='2\\2026-10-21 & 12-51-12-A3-50-2.txt', blank=A3_OFF, source='卤钨灯'),
    dict(key='A3c5b', mol='A3', kind='conc_rep', day=2, cal='d2_long', conc=5.0,
         sample='2\\2026-10-21 & 13-02-28-A3-5-2.txt', blank=A3_OFF, source='卤钨灯'),
    # ---- 第二周：A3 光源对比（卤钨 + 氘灯）
    dict(key='A3_DW', mol='A3', kind='source', day=2, cal='d2_long', conc=5.0,
         sample='3\\2026-10-21 & 13-06-53-A3-5-D+W.txt',
         blank='3\\2026-10-21 & 13-11-41-A3-0-D+W.txt', source='卤钨灯+氘灯'),
    # ---- 第二周：A2
    dict(key='A2', mol='A2', kind='molecule', day=2, cal='d2_long', conc=5.0,
         sample='3\\2026-10-21 & 13-21-06-A2-5.txt',
         blank='3\\2026-10-21 & 13-23-50-A2-0.txt', source='卤钨灯'),
    dict(key='A2b', mol='A2', kind='molecule_rep', day=2, cal='d2_long', conc=5.0,
         sample='3\\2026-10-21 & 13-31-52-A2-5-2.txt',
         blank='3\\2026-10-21 & 13-23-50-A2-0.txt', source='卤钨灯'),
    # ---- 第二周：短波段三种分子
    dict(key='A1', mol='A1', kind='molecule', day=2, cal='d2_short', conc=10.0,
         sample='4\\2026-10-21 & 13-49-27-A1.txt',
         blank='4\\2026-10-21 & 14-03-45-乙醇.txt', source='氘灯'),
    dict(key='B1', mol='B1', kind='molecule', day=2, cal='d2_short', conc=10.0,
         sample='4\\2026-10-21 & 13-54-44-B1.txt',
         blank='4\\2026-10-21 & 14-03-45-乙醇.txt', source='氘灯'),
    dict(key='B1b', mol='B1', kind='molecule_rep', day=2, cal='d2_short', conc=10.0,
         sample='4\\2026-10-21 & 13-56-47-B1-2.txt',
         blank='4\\2026-10-21 & 14-03-45-乙醇.txt', source='氘灯'),
    dict(key='B1c', mol='B1', kind='molecule_rep', day=2, cal='d2_short', conc=10.0,
         sample='4\\2026-10-21 & 14-14-51-B1-3.txt',
         blank='4\\2026-10-21 & 14-03-45-乙醇.txt', source='氘灯'),
    dict(key='B2', mol='B2', kind='molecule', day=2, cal='d2_short', conc=30.0,
         sample='4\\2026-10-21 & 14-01-40-B2.txt',
         blank='4\\2026-10-21 & 14-03-45-乙醇.txt', source='氘灯'),
]

# ---------------------------------------------------------------- 数据文件槽位
# 槽位 = **报告真正用到的那条数据**，不是「原始数据文件夹里的每个 txt」。
# 同一个浓度测了两次（A3c5 / A3c5b）时报告只用选中的那一条，
# 所以界面上这个浓度只有一行，不需要也不可能让用户去指定两次。
#
# key 形如：
#   cal:d1_long     标定的光源谱
#   sample:A3c5b    报告采用的样品谱（哪个 key 由「测量选择」决定）
#   blank:b_A3_0    空白谱（多条样品共用同一份空白时只占一个槽位）
SLOT_CAL = 'cal:'
SLOT_SAMPLE = 'sample:'
SLOT_BLANK = 'blank:'

# 报告里除「测量选择」之外还要用的样品：3.2 节光源对比固定对比这两条。
SOURCE_SAMPLE_KEYS = ('A3c5', 'A3_DW')

# 空白文件登记表：SAMPLES 里的 blank 字段按路径匹配到这里，
# 同一份空白被多条样品共用时只出现一次（否则界面上会有十几个重复的下拉框）。
BLANKS = [
    dict(key='b_A4_EtOH', label='A4（第一周）',
         file='2026-10-14 & 17-11-53-A4-乙醇.txt'),
    dict(key='b_A3_0', label='A3 浓度系列',
         file='2\\2026-10-21 & 12-56-02-A3-0.txt'),
    dict(key='b_A3_DW', label='A3 双光源',
         file='3\\2026-10-21 & 13-11-41-A3-0-D+W.txt'),
    dict(key='b_A2_0', label='A2',
         file='3\\2026-10-21 & 13-23-50-A2-0.txt'),
    dict(key='b_EtOH', label='短波段（A1/B1/B2）',
         file='4\\2026-10-21 & 14-03-45-乙醇.txt'),
]


def _norm_key(path):
    """路径比较用的规范形式（Windows 不区分大小写）。"""
    return os.path.normcase(os.path.normpath(str(path or '')))


def _ensure_blanks():
    """SAMPLES 里出现、但 BLANKS 没登记的空白，自动补一条（不让 run 崩）。"""
    known = {_norm_key(b['file']) for b in BLANKS}
    for s in SAMPLES:
        norm = _norm_key(s['blank'])
        if norm in known:
            continue
        key = 'b_' + re.sub(r'\W+', '_', str(s['key']))
        BLANKS.append(dict(key=key, label='%s' % s['key'], file=s['blank']))
        known.add(norm)


_ensure_blanks()
SAMPLES_BY_KEY = {s['key']: s for s in SAMPLES}
BLANKS_BY_KEY = {b['key']: b for b in BLANKS}
_SLOTS = {}


def blank_of_sample(s):
    """样品对应的空白登记项。"""
    norm = _norm_key(s['blank'])
    for b in BLANKS:
        if _norm_key(b['file']) == norm:
            return b
    return None


def used_sample_keys(picks_mol=None, picks_conc=None, extras=None):
    """报告真正会读的样品 key（顺序：浓度系列 → 其余分子 → 光源对比）。"""
    pm = dict(MOLECULE_DEFAULT)
    pm.update({k: v for k, v in (picks_mol or {}).items() if v in MOLECULE_CANDIDATES.get(k, [])})
    pc = dict(CONC_PICK_DEFAULT)
    pc.update({k: v for k, v in (picks_conc or {}).items() if v in CONC_CANDIDATES.get(k, [])})
    out = []

    def add(key):
        if key and key in SAMPLES_BY_KEY and key not in out:
            out.append(key)

    for c in CONC_VALUES:
        add(pc.get(conc_label(c)))
    for code in ('A1', 'A2', 'A3', 'A4', 'B1', 'B2'):
        add(pm.get(code))
    for key in (SOURCE_SAMPLE_KEYS if extras is None else extras):
        add(key)
    return out


def _pick_sig(picks_mol, picks_conc):
    pm = picks_mol or {}
    pc = picks_conc or {}
    return (tuple(sorted(pm.items())), tuple(sorted(pc.items())))


def file_slots(picks_mol=None, picks_conc=None):
    """界面上的槽位清单：标定 → 浓度系列 → 其余分子 → 空白。

    每个浓度、每个分子各**一行**：重复测量里只列「测量选择」当前选中的那一条。
    多条用途指向同一份文件时合并成一行（如 A3 在浓度系列和其余分子里都取 5 μmol/L）。
    """
    sig = _pick_sig(picks_mol, picks_conc)
    if sig in _SLOTS:
        return [dict(s) for s in _SLOTS[sig]]
    pm = dict(MOLECULE_DEFAULT)
    pm.update({k: v for k, v in (picks_mol or {}).items()
               if v in MOLECULE_CANDIDATES.get(k, [])})
    pc = dict(CONC_PICK_DEFAULT)
    pc.update({k: v for k, v in (picks_conc or {}).items()
               if v in CONC_CANDIDATES.get(k, [])})

    out, order = {}, []

    def put(key, kind, group, label, default, note=''):
        if key in out:                       # 同一份文件被多处用到 → 合并标签
            if label not in out[key]['label'].split('、'):
                out[key]['label'] += '、' + label
            return
        out[key] = dict(key=key, kind=kind, group=group, label=label,
                        default=default, note=note)
        order.append(key)

    for c in CALIBRATIONS:
        put(SLOT_CAL + c['key'], 'cal', '标定文件', c['short'], c['file'])
    for c in CONC_VALUES:
        key = pc.get(conc_label(c))
        s = SAMPLES_BY_KEY.get(key)
        if not s:
            continue
        # 标签带测量 key，因为同一个浓度可能测过两次（切换「测量选择」会换文件）
        put(SLOT_SAMPLE + key, 'sample', '浓度系列',
            '%g μmol·L⁻¹' % c, s['sample'],
            note='测量 %s' % key)
    for code in ('A1', 'A2', 'A3', 'A4', 'B1', 'B2'):
        key = pm.get(code)
        s = SAMPLES_BY_KEY.get(key)
        if not s:
            continue
        mol = MOLECULES.get(code) or {}
        put(SLOT_SAMPLE + key, 'sample', '其余分子',
            '%s · %s' % (code, mol.get('short', code)), s['sample'],
            note='测量 %s' % key)
    for key in SOURCE_SAMPLE_KEYS:
        s = SAMPLES_BY_KEY.get(key)
        if not s:
            continue
        put(SLOT_SAMPLE + key, 'sample', '光源对比',
            '光源对比 · %s' % s.get('source', key), s['sample'],
            note='测量 %s' % key)
    # 空白只列「被用到的样品」需要的那几份
    for key in used_sample_keys(pm, pc):
        s = SAMPLES_BY_KEY[key]
        b = blank_of_sample(s)
        if b:
            put(SLOT_BLANK + b['key'], 'blank', '空白文件', b['label'], b['file'])
    rows = [dict(out[k]) for k in order]
    _SLOTS[sig] = rows
    return [dict(s) for s in rows]


def all_slot_keys():
    """所有**可能**出现的槽位（校验 file_map 用，与当前选择无关）。

    file_map 里允许保留「当前没选中」的测量，这样来回切换测量时
    之前指定的文件不会丢。
    """
    keys = {SLOT_CAL + c['key'] for c in CALIBRATIONS}
    keys |= {SLOT_SAMPLE + s['key'] for s in SAMPLES}
    keys |= {SLOT_BLANK + b['key'] for b in BLANKS}
    return keys


def clean_file_map(mapping):
    """只保留合法槽位，值统一成路径字符串（绝对路径原样保留）。"""
    valid = all_slot_keys()
    out = {}
    for key, value in (mapping or {}).items():
        if key not in valid or not isinstance(value, str):
            continue
        value = value.strip().strip('"').strip()
        if not value or len(value) > 1024:
            continue
        out[key] = os.path.normpath(value.replace('/', os.sep))
    return out


# ---------------------------------------------------------------- 模糊匹配
# 别人（或换一天）用同一套光谱仪软件时，文件名只在「时间戳」上不同：
#   2026-10-21 & 12-56-02-A3-0.txt   ←  语义后缀 A3-0
# 甚至会被改成 A3-5(2).txt / A3-5 - 副本.txt。所以匹配以**语义后缀**为主、
# 整名相似度为辅、同目录加成，逐条打分后取最高分。
FUZZY_ACCEPT = 0.80      # ≥ 此分自动采用（界面上标「自动匹配」，可改回）
FUZZY_SUGGEST = 0.45     # ≥ 此分才列进候选下拉框

def _stem_of(rel):
    return os.path.splitext(os.path.basename(str(rel or '')))[0]


_STAMP_RE = re.compile(r'^[\s\d\-_.:/&+]*')
_TAG_TOK_RE = re.compile(r'[A-Za-z]+\d*|\d+|[^\x00-\x7f]')
# 复制/重命名时 Windows 与浏览器自动加的后缀：`- 副本`、` (2)`、`_copy`
_COPY_SUFFIX_RE = re.compile(
    r'(?:\s*-\s*副本|\s*副本|\s*-\s*copy|\s*\(\d{1,2}\)|_\d{1,2}|_copy)+$',
    re.IGNORECASE)


def split_stamp(rel):
    """把文件名拆成（时间戳前缀, 语义后缀）。

    `2026-10-21 & 12-56-02-A3-0` → (`2026-10-21 & 12-56-02-`, `A3-0`)；
    没有时间戳的名字（如 `氘灯标定`）整串都算语义后缀。
    复制产生的 `- 副本` / `(2)` 后缀先剥掉，否则同一份文件会被判成两个。
    """
    stem = _stem_of(rel)
    m = _STAMP_RE.match(stem)
    tag = stem[m.end():].strip(' -_')
    tag = _COPY_SUFFIX_RE.sub('', tag).strip(' -_') or tag
    return stem[:m.end()].strip(), tag or stem


def tag_tokens(tag):
    """语义后缀 → 词元：`A3-5(2)` → ['a3', '5', '2']。

    中文按单字切：词元集合用来惩罚「多/少一个 -数字」这种差别
    （A3-5 与 A3-5-2 是两次不同测量，不能混为一谈）。
    """
    return [m.group(0).lower() for m in _TAG_TOK_RE.finditer(tag or '')]


def _plain(s):
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', str(s or '').lower())


def has_copy_suffix(rel):
    """文件名是否带 `- 副本` / `(2)` / `_copy` 这类复制后缀。"""
    stem = _stem_of(rel)
    return bool(_COPY_SUFFIX_RE.search(split_stamp(rel)[1] or '')) or \
        bool(_COPY_SUFFIX_RE.search(stem) and not _COPY_SUFFIX_RE.sub('', stem) == stem)


def _plain_stem(rel):
    """剥掉时间戳与复制后缀后的纯文本（判等用）。"""
    return _plain(split_stamp(rel)[1])


def match_score(target, cand):
    """target/cand 为相对数据目录的 txt 路径，返回 0~1 的相似度。

    权重之和正好 1.0，且**不提前饱和**：`0.74·语义后缀 + 0.20·整名 +
    0.04·同目录 + 0.02·同时间戳`。留出头寸很关键——同名的 A3-0.5 在
    文件夹 1 和 2 里各有一份（1 是第一批短积分、2 是第二批），
    只有「同目录」这一项能把它们分开；早先写成先算 1.0 再 `min(1.0, …)`
    加分，两者都封顶成 1.0，排序退化成按路径字母序 → 静默选了文件夹 1 的那份。
    """
    import difflib
    t_stamp, t_tag = split_stamp(target)
    c_stamp, c_tag = split_stamp(cand)
    t_norm, c_norm = _plain(t_tag), _plain(c_tag)
    if not t_norm or not c_norm:
        return 0.0

    t_tok, c_tok = set(tag_tokens(t_tag)), set(tag_tokens(c_tag))
    if t_tag and t_tag == c_tag:
        tag_sim = 1.0
    else:
        tag_sim = difflib.SequenceMatcher(None, t_norm, c_norm).ratio()
        if t_tok and c_tok:
            # 词元集合不同（多/少一个浓度或重复序号）要明确扣分
            penalty = 1.0 - len(t_tok & c_tok) / float(max(len(t_tok), len(c_tok)))
            tag_sim *= (1.0 - 0.5 * penalty)
    # 整名相似度：用剥掉时间戳/副本后缀的形式，免得 `(2)` 拖低同一份文件的分数
    full_sim = difflib.SequenceMatcher(
        None, _plain_stem(target), _plain_stem(cand)).ratio()

    score = 0.74 * tag_sim + 0.20 * full_sim
    # 同一子文件夹（文件夹 1/2/3/4 是按测量批次分的）——唯一能分开同名文件的判据
    t_dir = os.path.dirname(os.path.normpath(str(target)))
    c_dir = os.path.dirname(os.path.normpath(str(cand)))
    if os.path.normcase(t_dir) == os.path.normcase(c_dir) and t_dir not in ('', '.'):
        score += 0.04
    # 时间戳完全一致（同一批数据里只是改名）
    if t_stamp and t_stamp == c_stamp:
        score += 0.02
    return max(0.0, min(1.0, score))


def _index_files(data_dir):
    """数据目录里的全部 txt（相对路径），按路径排序。"""
    if not data_dir or not os.path.isdir(data_dir):
        return []
    out = []
    for path in spectrum_files(data_dir):
        try:
            out.append(os.path.relpath(path, data_dir))
        except ValueError:                 # 不同盘符
            out.append(os.path.basename(path))
    return out


def suggest_files(target, files, top=5):
    """给一个目标文件名挑候选：[(score, rel), …]，按分数降序。"""
    scored = []
    for rel in files:
        s = match_score(target, rel)
        if s >= FUZZY_SUGGEST:
            scored.append((round(float(s), 4), rel))
    # 分数高的在前；同分时优先不带「副本/(2)」的原件，再按路径
    scored.sort(key=lambda x: (-x[0], has_copy_suffix(x[1]), x[1]))
    # 同一份文件的原件与副本各留一条，别让下拉框被 5 个 `(2)(3)(4)` 副本占满
    seen, out = set(), []
    for s, rel in scored:
        key = (_plain_stem(rel), has_copy_suffix(rel))
        if key in seen:
            continue
        seen.add(key)
        out.append((s, rel))
        if len(out) >= top:
            break
    return out


def fuzzy_match(default_rel, data_dir, files=None):
    """给缺失的默认文件找个替身；返回 (rel, score) 或 (None, 0)。"""
    files = _index_files(data_dir) if files is None else files
    if not files:
        return None, 0.0
    best, best_score = None, 0.0
    for s, rel in suggest_files(default_rel, files, top=1):
        best, best_score = rel, s
    return best, best_score


def resolve_slots(file_map=None, data_dir='', fuzzy=True,
                  picks_mol=None, picks_conc=None):
    """槽位 → 绝对路径；返回 (paths, missing, detail)。

    只解析当前「测量选择」下**报告真正会读**的那几条数据：
    同一浓度的两次测量只要求一条，所以界面上每个浓度只有一行。

    解析顺序：① 用户映射里的路径 ② 登记的默认路径 ③ 模糊匹配。

    ③ 只在「文件确实不在」时才做，且：
      · 分数 ≥ FUZZY_ACCEPT 自动采用，并在 detail 里标 ``fuzzy``，
        界面据此显示「自动匹配到 xxx.txt」，用户不满意可以改；
      · 分数不够就退回进 ``missing``，但把候选一并带回去，界面上一键采用。

    ``missing`` 的每一项都带 ``suggestions``：宁可整份计算明确报错说清缺哪一个，
    也不要静默退回默认文件——那样报告里的数字会和界面上的选择不一致。
    """
    fm = clean_file_map(file_map)
    base = data_dir or ''
    files = _index_files(base) if fuzzy else []
    paths, missing, detail = {}, [], {}
    for slot in file_slots(picks_mol, picks_conc):
        key = slot['key']
        default_rel = slot['default']
        mapped = fm.get(key)
        target_rel = mapped or default_rel
        path = target_rel if os.path.isabs(target_rel) else os.path.join(base, target_rel)
        path = os.path.normpath(path)
        entry = dict(key=key, label=slot['label'], kind=slot['kind'],
                     group=slot['group'], default=default_rel,
                     requested=target_rel, overridden=bool(mapped),
                     path=path, rel=None, score=None, status='default',
                     suggestions=[])
        if os.path.isfile(path):
            entry['rel'] = target_rel if not os.path.isabs(target_rel) else None
            entry['status'] = 'manual' if mapped else 'default'
            paths[key] = path
            detail[key] = entry
            continue

        # ---- 文件不在：先按「请求的名字」，再按「默认的名字」做模糊匹配
        cand_rel, cand_score = None, 0.0
        for probe in ([target_rel, default_rel] if mapped else [default_rel]):
            if os.path.isabs(probe):
                probe = os.path.basename(probe)
            rel, score = fuzzy_match(probe, base, files)
            if rel and score > cand_score:
                cand_rel, cand_score = rel, score
        entry['suggestions'] = [
            dict(rel=rel, score=s, path=os.path.normpath(os.path.join(base, rel)))
            for s, rel in suggest_files(
                os.path.basename(target_rel) if os.path.isabs(target_rel) else target_rel,
                files)]
        if cand_rel and cand_score >= FUZZY_ACCEPT:
            full = os.path.normpath(os.path.join(base, cand_rel))
            entry.update(path=full, rel=cand_rel, score=cand_score, status='fuzzy')
            paths[key] = full
            detail[key] = entry
            continue
        entry['score'] = cand_score or None
        entry['status'] = 'ambiguous' if entry['suggestions'] else 'missing'
        paths[key] = path                 # 保留原路径，报错时好说明找的是什么
        missing.append(entry)
        detail[key] = entry
    return paths, missing, detail


class DataFilesMissing(RuntimeError):
    """有槽位对应的数据文件不存在。"""

    def __init__(self, missing):
        self.missing = list(missing or [])
        shown = ['%s → %s' % (m['label'], os.path.basename(m.get('path') or ''))
                 for m in self.missing[:4]]
        more = '' if len(self.missing) <= 4 else '…（共 %d 个）' % len(self.missing)
        hint = ''
        fuzzy = [m for m in self.missing if m.get('suggestions')]
        if fuzzy:
            hint = '（%d 个缺失项找到了相近文件，可在「数据文件映射」里一键采用）' % len(fuzzy)
        elif not any(m.get('overridden') for m in self.missing):
            hint = '（可在「数据文件映射」里逐个挑，或点「自动匹配文件」）'
        super().__init__('缺少 %d 个数据文件：%s%s%s。请检查「数据目录」或「数据文件映射」。'
                         % (len(self.missing), '；'.join(shown), more, hint))


# ---------------------------------------------------------------- 单个文件
def read_single(path):
    """读一个 txt 供界面单独查看；错误信息要能直接给用户看。"""
    if not os.path.isfile(path):
        raise ValueError('文件不存在：%s' % path)
    try:
        return load_spectrum(path)
    except ValueError:
        raise ValueError('不是光谱仪导出的四列 txt（index / original / '
                         'background / difference）：%s' % os.path.basename(path))


def single_peak_info(spec, cal=None, window=9):
    """单个谱的最强点：pixel、强度、以及（给了标定时）波长。"""
    y = np.asarray(spec['difference'], float)
    idx = np.asarray(spec['index'], float)
    if not len(y):
        return dict(n=0, pixel=float('nan'), intensity=float('nan'),
                    lam=float('nan'), imin=float('nan'), imax=float('nan'))
    sm = _moving_average(y, window)
    i = int(np.argmax(sm))
    info = dict(n=int(len(y)), pixel=float(idx[i]), intensity=float(y[i]),
                imin=float(np.nanmin(y)), imax=float(np.nanmax(y)),
                lam=float('nan'))
    if cal:
        info['lam'] = float(cal['a'] * idx[i] + cal['b'])
    return info


def smooth(y, window):
    """带镜像填充的移动平均（对外接口，绘图用）。"""
    return _moving_average(y, window)


# ---------------------------------------------------------------- 测量选择
# 同一个样品/浓度如果测了多次，用「选择模块」决定报告里用哪一条。
# 下面是每个槽位的候选测量；默认一律取候选里的**最后一次**（用户 2026-10-21 指定），
# 界面上可以逐项改成第一次/第二次。
CONC_VALUES = [0.5, 1.0, 5.0, 10.0, 20.0, 50.0]      # 浓度系列（μmol·L⁻¹）

CONC_CANDIDATES = {
    '0.5': ['A3c0.5'],
    '1': ['A3c1'],
    '5': ['A3c5', 'A3c5b'],
    '10': ['A3c10'],
    '20': ['A3c20', 'A3c20b'],
    '50': ['A3c50', 'A3c50b'],
}

MOLECULE_CANDIDATES = {
    'A1': ['A1'],
    'A2': ['A2', 'A2b'],
    'A3': ['A3c5', 'A3c5b'],
    'A4': ['A4'],
    'B1': ['B1', 'B1b', 'B1c'],
    'B2': ['B2'],
}

# 默认选择：每个槽位取候选里的最后一条
CONC_PICK_DEFAULT = {c: CONC_CANDIDATES[c][-1] for c in CONC_CANDIDATES}
MOLECULE_DEFAULT = {code: MOLECULE_CANDIDATES[code][-1] for code in MOLECULE_CANDIDATES}

# Beer-Lambert 拟合默认用哪几个浓度（线性区）
BEER_CONC_DEFAULT = [0.5, 1.0, 5.0, 10.0]

# 兼容旧接口
BEER_DEFAULT = [CONC_PICK_DEFAULT['%g' % c] for c in BEER_CONC_DEFAULT]
CONC_KEYS = [CONC_PICK_DEFAULT['%g' % c] for c in CONC_VALUES]


def conc_label(value):
    """浓度槽位的键：0.5 → '0.5'、5.0 → '5'。"""
    return '%g' % value


def pick_choices():
    """给界面用的候选清单：{槽位: [sample key, ...]}，按测量时间先后排好。"""
    return {
        'conc': {conc_label(c): list(CONC_CANDIDATES[conc_label(c)]) for c in CONC_VALUES},
        'mol': {code: list(MOLECULE_CANDIDATES[code]) for code in MOLECULE_CANDIDATES},
    }


# ---------------------------------------------------------------- 数据读取
def load_spectrum(path):
    """读一个软件导出的 txt，返回 dict（index / original / background / difference）。"""
    rows = []
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        text = fh.read()
    for ln in text.splitlines():
        parts = ln.split('\t')
        if len(parts) < 4:
            parts = ln.split()
        if len(parts) < 4:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])))
        except ValueError:
            continue
    if not rows:
        raise ValueError('无法识别的数据文件：%s' % path)
    a = np.array(rows, dtype=float)
    return dict(path=path, index=a[:, 0], original=a[:, 1],
                background=a[:, 2], difference=a[:, 3])


# 明显不是光谱数据的扩展名：扫目录时按后缀直接跳过，省掉一次读盘。
# 注意**不要**把 .dat/.csv/.asc/无后缀 列进来——那些要按内容判断（换了命名
# 习惯的导出文件正是靠内容识别才能进下拉框）。
_NON_DATA_EXT = (
    '.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt',
    '.zip', '.rar', '.7z', '.png', '.jpg', '.jpeg', '.gif', '.bmp',
    '.py', '.js', '.html', '.json', '.md', '.exe', '.dll', '.log',
)


def spectrum_files(data_dir, recursive=True):
    """扫描数据目录里的 txt（按路径排序）。

    只按 `.txt` 后缀收会漏东西：光谱仪导出的文件换了命名习惯、或者被
    手动重命名成 `.TXT`/`.dat`/无后缀之后，就不出现在下拉框里了，用户
    只能看到「没找到」。所以这里改成**按内容判断**：只要是四列数值
    （index / original / background / difference）能解析，就当作候选。

    探测有成本，所以只在「后缀不是 .txt」时才去读文件头几行；`.txt`
    一律直接收（那是绝大多数情况，也是原来的行为）。
    """
    out = []

    def _walk(d):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return
        for n in names:
            p = os.path.join(d, n)
            if os.path.isdir(p):
                if recursive:
                    _walk(p)
                continue
            low = n.lower()
            if low.endswith('.txt'):
                out.append(p)
            else:
                # 非 .txt：明显是文档/表格的先按扩展名挡掉（省一次读盘），
                # 其余（.dat/.csv/.asc/无后缀/任意后缀）都**验内容**——
                # 只要真是四列数值就收，这样重命名过的导出文件也不会漏。
                if low.endswith(_NON_DATA_EXT):
                    continue
                if is_spectrum_file(p):
                    out.append(p)

    _walk(data_dir)
    return out


def is_spectrum_file(path, ext_ok=True):
    """这个文件看起来是不是光谱仪导出的四列数据？

    `ext_ok` 只为让调用方能跳过明显非数据的扩展名（.pdf/.xlsx 之类），
    真正的判据始终是内容：至少 3 行、每行能切出 ≥4 个浮点数。
    """
    if not ext_ok:
        return False
    if os.path.splitext(path)[1].lower() in _NON_DATA_EXT:
        return False
    try:
        if os.path.getsize(path) > 64 * 1024 * 1024:      # 太大，不像是光谱
            return False
        rows = 0
        with open(path, 'r', encoding='utf-8-sig', errors='replace') as fh:
            for line in fh:
                s = line.strip()
                if not s:
                    continue
                parts = s.replace(',', ' ').split()
                if len(parts) < 4:
                    return False
                try:
                    [float(x) for x in parts[:4]]
                except ValueError:
                    return False
                rows += 1
                if rows >= 3:                              # 三行就够判断了
                    return True
        return False
    except OSError:
        return False


# ---------------------------------------------------------------- 标定
def _moving_average(y, window):
    """带镜像填充的移动平均，避免两端被零拉低。"""
    y = np.asarray(y, dtype=float)
    w = int(window)
    if w <= 1 or w > len(y):
        return y.copy()
    pad = w // 2
    yp = np.concatenate([y[pad:0:-1], y, y[-2:-pad - 2:-1]])
    k = np.ones(w) / w
    out = np.convolve(yp, k, mode='valid')
    if len(out) < len(y):
        out = np.concatenate([out, [out[-1]] * (len(y) - len(out))])
    return out[:len(y)]


def _parabolic_center(y, i, half=3):
    """在极值索引 i 附近用抛物线拟合求亚像素中心。"""
    n = len(y)
    lo, hi = max(0, i - half), min(n, i + half + 1)
    xs = np.arange(lo, hi, dtype=float)
    ys = y[lo:hi]
    if len(xs) < 3:
        return float(i)
    A = np.vstack([np.ones_like(xs), xs, xs ** 2]).T
    try:
        coef, *_ = np.linalg.lstsq(A, ys, rcond=None)
    except np.linalg.LinAlgError:
        return float(i)
    c = coef[2]
    if abs(c) < 1e-12:
        return float(i)
    x0 = -coef[1] / (2 * c)
    if not (lo - 1 <= x0 <= hi):
        return float(i)
    return float(x0)


def calibrate(spec, prior=None, lines=DEUTERIUM_LINES, search_px=45):
    """从氘灯（或汞灯）谱图找特征线，线性拟合 λ = a·pixel + b。

    prior=(a, b) 给出先验线性系数，用来把寻峰窗口限制在 ±search_px 像素内，
    避免在噪声里挑错峰。返回的 'ok'=False 时调用方应退回先验。
    """
    d = spec['difference'].astype(float)
    idx = spec['index'].astype(float)
    sm = _moving_average(d, 31)
    sm = sm - np.median(sm)
    pts = []
    if prior:
        a0, b0 = prior
        for lam in lines:
            px = (lam - b0) / a0
            w = int(search_px)
            lo = int(max(0, round(px) - w))
            hi = int(min(len(sm) - 1, round(px) + w))
            if hi <= lo + 2:
                continue
            seg = sm[lo:hi + 1]
            i = lo + int(np.argmax(seg))
            c = _parabolic_center(sm, i)
            pts.append((1.0 + c, lam))          # index 列从 1 开始
    else:
        # 没有先验：取全局最突出的三个峰，按候选组合拟合
        import itertools
        from scipy.signal import find_peaks
        pk, prop = find_peaks(sm, prominence=np.max(sm) * 0.03, distance=15)
        cand = sorted(pk.tolist(), key=lambda i: -sm[i])[:10]
        best = None
        for combo in itertools.combinations(cand, 3):
            xs = np.array([1.0 + c for c in combo])
            A = np.vstack([xs, np.ones(3)]).T
            coef, *_ = np.linalg.lstsq(A, np.asarray(lines), rcond=None)
            pred = A @ coef
            ss = np.sum((np.asarray(lines) - pred) ** 2)
            sst = np.sum((np.asarray(lines) - np.mean(lines)) ** 2)
            r2 = 1 - ss / sst
            if best is None or r2 > best[0]:
                best = (r2, coef, xs)
        if best:
            coef = best[1]
            pts = [(x, lam) for x, lam in zip(best[2], lines)]

    if len(pts) < 2:
        if prior:
            return dict(ok=False, a=prior[0], b=prior[1], sigma_a=0.0, sigma_b=0.0,
                        r2=0.0, points=[], n=0, fallback=True)
        raise ValueError('标定失败：找不到足够的特征峰')

    xs = np.array([p[0] for p in pts], dtype=float)
    ys = np.array([p[1] for p in pts], dtype=float)
    A = np.vstack([xs, np.ones_like(xs)]).T
    coef, res, *_ = np.linalg.lstsq(A, ys, rcond=None)
    pred = A @ coef
    n = len(xs)
    if n >= 3:
        s2 = np.sum((ys - pred) ** 2) / (n - 2)
        s = np.sqrt(max(s2, 0.0))
        sxx = np.sum((xs - xs.mean()) ** 2)
        sigma_a = s / np.sqrt(sxx) if sxx > 0 else 0.0
        sigma_b = s * np.sqrt(1.0 / n + xs.mean() ** 2 / sxx) if sxx > 0 else 0.0
        sst = np.sum((ys - ys.mean()) ** 2)
        r2 = 1 - np.sum((ys - pred) ** 2) / sst if sst > 0 else 1.0
    else:
        sigma_a = sigma_b = 0.0
        r2 = 1.0
    out = dict(ok=True, a=float(coef[0]), b=float(coef[1]),
               sigma_a=float(sigma_a), sigma_b=float(sigma_b), r2=float(r2),
               points=[(float(p[0]), float(p[1])) for p in pts], n=n,
               fallback=False)
    # 与先验偏差过大 → 认为寻峰失败
    if prior and out['ok']:
        da = abs(out['a'] - prior[0]) / abs(prior[0])
        db = abs(out['b'] - prior[1])
        if da > 0.03 or db > 15:
            out.update(ok=False, fallback=True, a=prior[0], b=prior[1])
    return out


def to_wavelength(cal, index=None, n=3648):
    idx = np.arange(1, n + 1, dtype=float) if index is None else np.asarray(index, float)
    return cal['a'] * idx + cal['b']


# ---------------------------------------------------------------- 吸光度
def absorbance_curve(sample, blank, cal, smooth_window=DEFAULT_SMOOTH,
                     stray=0.0, n=None):
    """A(λ) = lg(I0/I)；stray>0 时按「杂散光占入射光强的比例」扣底。

    返回 dict(lam, A_raw, A_smooth, A_raw_plain, A_smooth_plain, I, I0)：
    · ``*_plain`` 是完全不扣杂散光的原始吸光度（作图定性比较用）；
    · 不带 plain 的版本按 stray 扣底（定量计算用）。
    """
    I = sample['difference'].astype(float)
    I0 = blank['difference'].astype(float)
    m = min(len(I), len(I0))
    I, I0 = I[:m], I0[:m]
    lam = to_wavelength(cal, sample['index'][:m])
    with np.errstate(divide='ignore', invalid='ignore'):
        A_plain = np.log10(I0 / I)
        if stray and stray > 0:
            S = stray * I0
            A = np.log10((I0 - S) / (I - S))
        else:
            A = A_plain.copy()
    A = np.where(np.isfinite(A), A, np.nan)
    A_plain = np.where(np.isfinite(A_plain), A_plain, np.nan)
    A_sm = np.where(np.isfinite(A),
                    _moving_average(np.nan_to_num(A, nan=0.0), smooth_window), np.nan)
    A_sm0 = np.where(np.isfinite(A_plain),
                     _moving_average(np.nan_to_num(A_plain, nan=0.0), smooth_window), np.nan)
    return dict(lam=lam, A_raw=A, A_smooth=A_sm,
                A_raw_plain=A_plain, A_smooth_plain=A_sm0, I=I, I0=I0)


def baseline_line(lam, A, anchors):
    """在 anchors 两个窗口里各取中位 A，连成直线。

    anchors = ((lo1, hi1), (lo2, hi2))，单位 nm。
    返回 (k, b, A_corr)；A_corr = A - (k·λ + b)。
    """
    def _med(lo, hi):
        m = np.isfinite(A) & (lam >= lo) & (lam <= hi)
        if not np.any(m):
            return np.nan
        return float(np.median(A[m]))

    (lo1, hi1), (lo2, hi2) = anchors
    x1 = (lo1 + hi1) / 2.0
    x2 = (lo2 + hi2) / 2.0
    y1, y2 = _med(lo1, hi1), _med(lo2, hi2)
    if not (np.isfinite(y1) and np.isfinite(y2)) or x2 == x1:
        k, b = 0.0, 0.0
    else:
        k = (y2 - y1) / (x2 - x1)
        b = y1 - k * x1
    A_corr = A - (k * lam + b)
    return k, b, A_corr


def default_anchors(band, pad=80, width=25):
    """按吸收带自动给基线锚点：带外两侧各一个窗口。"""
    lo, hi = band
    lo1 = max(240.0, lo - pad)
    lo2 = max(240.0, lo - pad + width)
    hi1 = hi + pad - width
    hi2 = hi + pad
    return ((lo1, lo2), (hi1, hi2))


def find_peak(lam, A, band, half_px=2):
    """在 band 内找 A 的极大点；用抛物线插值给出亚像素 λmax。

    ⚠ 只作为 Voigt 拟合失败时的兜底。吸收峰的 λmax / A 以 voigt_fit 的
    总拟合曲线极大值为准（见 analysis.run），抛物线寻峰会被噪声带偏。
    """
    m = np.isfinite(A) & (lam >= band[0]) & (lam <= band[1])
    if not np.any(m):
        return nan_peak()
    idx = np.where(m)[0]
    j = idx[int(np.argmax(A[idx]))]
    i = int(j)
    lam_pk = float(lam[i])
    a_pk = float(A[i])
    if 1 <= i < len(A) - 1 and np.isfinite(A[i - 1]) and np.isfinite(A[i + 1]):
        y0, y1, y2 = A[i - 1], A[i], A[i + 1]
        denom = (y0 - 2 * y1 + y2)
        if abs(denom) > 1e-12:
            d = 0.5 * (y0 - y2) / denom
            if abs(d) <= 1.0:
                lam_pk = float(lam[i] + d * (lam[i + 1] - lam[i]))
                a_pk = float(y1 - 0.25 * (y0 - y2) * d)
    return dict(index=i, lam=lam_pk, A=a_pk)


def nan_peak():
    return dict(index=-1, lam=float('nan'), A=float('nan'))


# ---------------------------------------------------------------- Voigt 分峰
def _voigt_shape(x, amp, center, sigma, gamma):
    """峰高为 amp 的 Voigt 线形（面积归一的 voigt_profile 再按峰高归一）。"""
    from scipy.special import voigt_profile
    sigma = max(abs(float(sigma)), 1e-3)
    gamma = max(abs(float(gamma)), 1e-3)
    prof = voigt_profile(np.asarray(x, float) - center, sigma, gamma)
    peak = voigt_profile(0.0, sigma, gamma)
    return amp * prof / max(peak, 1e-30)


def voigt_fwhm(sigma, gamma):
    """Voigt 线形的半高全宽（近似公式，Olivero & Longbothum）。"""
    fg = 2.0 * sigma * np.sqrt(2 * np.log(2))
    fl = 2.0 * gamma
    return 0.5346 * fl + np.sqrt(0.2166 * fl ** 2 + fg ** 2)


def _half_width(x, y, i, base):
    amp = y[i] - base
    half = base + amp / 2.0
    left = i
    while left > 0 and y[left] > half:
        left -= 1
    right = i
    while right < len(y) - 1 and y[right] > half:
        right += 1
    return max(x[right] - x[left], 2.0)


def _voigt_model(xx, params, deg, n, x0):
    out = np.zeros_like(xx, dtype=float)
    for d in range(deg + 1):
        out = out + params[d] * ((xx - x0) / 200.0) ** d
    for k in range(n):
        off = deg + 1 + 4 * k
        out = out + _voigt_shape(xx, params[off], params[off + 1],
                                 params[off + 2], params[off + 3])
    return out


def _voigt_fit_n(x, y, band, n, deg):
    from scipy.optimize import curve_fit
    x0 = 0.5 * (band[0] + band[1])
    # 吸收带里有一千多个像素，拟合用 200 个左右的点就够，速度差一个量级
    step = max(1, len(x) // 200)
    xs, ys = x[::step], y[::step]
    i = int(np.argmax(ys))
    base = float(np.percentile(np.r_[ys[:4], ys[-4:]], 30))
    fw = _half_width(xs, ys, i, base)
    a0 = max(ys[i] - base, 1e-3)
    c0 = xs[i]
    best = None
    starts = (0.0,) if n == 1 else (-1.0, 1.0)
    for sh in starts:
        p0 = [base] + [0.0] * deg
        lo = [base - 0.6] + [-0.6] * deg
        hi = [base + 0.6] + [0.6] * deg
        for k in range(n):
            cc = c0 if k == 0 else c0 + sh * fw
            amp = a0 if k == 0 else 0.25 * a0
            p0 += [amp, cc, fw / 2.4, fw / 2.4]
            lo += [0.0, band[0] - 30.0, 0.3, 0.02]
            hi += [a0 * 4.0, band[1] + 30.0, 150.0, 150.0]
        try:
            popt, _ = curve_fit(lambda xx, *p: _voigt_model(xx, p, deg, n, x0),
                                xs, ys, p0=p0, bounds=(lo, hi), maxfev=20000)
        except Exception:      # noqa: BLE001  拟合不收敛就换初始值
            continue
        pred = _voigt_model(x, popt, deg, n, x0)
        sst = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - float(np.sum((y - pred) ** 2)) / sst if sst > 0 else 0.0
        if best is None or r2 > best['r2']:
            peaks = []
            for k in range(n):
                off = deg + 1 + 4 * k
                amp, cen, sig, gam = popt[off:off + 4]
                peaks.append(dict(amp=float(amp), center=float(cen),
                                  sigma=float(sig), gamma=float(gam),
                                  fwhm=float(voigt_fwhm(sig, gam))))
            peaks.sort(key=lambda p: -p['amp'])
            best = dict(r2=r2, popt=np.asarray(popt, float), peaks=peaks,
                        deg=deg, n=n, x0=x0)
    return best


def voigt_fit(lam, A, band, n_peaks='auto', deg=1):
    """Voigt 分峰拟合：A(λ) = Σ Voigt(λ) + 低阶基线。

    n_peaks = 1 / 2 / 'auto'：先拟合 1 个峰，若 R² 仍差且第二个组元明显，再试 2 个峰。
    返回的 ``lam_max``/``A_max`` 取自**总拟合曲线**的极大值（不是单个组元的峰高），
    这样它才与实测吸收峰的 λmax、A 对应。
    """
    lam = np.asarray(lam, float)
    A = np.asarray(A, float)
    m = np.isfinite(A) & (lam >= band[0]) & (lam <= band[1])
    x, y = lam[m], A[m]
    if len(x) < 30:
        return None
    # 扣杂散光后如果带内缺了一大片（NaN），拟合会在缺口之间“飞掉”，直接放弃
    span = (lam <= band[1]) & (lam >= band[0])
    if span.sum() and len(x) / float(span.sum()) < 0.75:
        return None
    if isinstance(n_peaks, str):
        auto = True
        n_try = [1, 2]
    else:
        auto = False
        n_try = [int(n_peaks)]
    best = None
    prev = None
    for n in n_try:
        if len(x) < 6 + 4 * n:
            break
        res = _voigt_fit_n(x, y, band, n, deg)
        if res is None:
            continue
        if prev is None:
            prev = res
            best = res
        if auto and n == 2 and prev is not None:
            prev_peak = max(p['amp'] for p in prev['peaks'])
            if (res['r2'] - prev['r2'] > 0.008
                    and res['peaks'][0]['amp'] > 0.05 * max(prev_peak, 1e-9)
                    and abs(res['peaks'][0]['center'] - res['peaks'][1]['center']) >= 8.0):
                best = res
            else:
                best = prev
    if best is None:
        return None

    grid = np.linspace(band[0], band[1], 800)
    total = _voigt_model(grid, best['popt'], best['deg'], best['n'], best['x0'])
    if not np.all(np.isfinite(total)):
        return None
    # 拟合曲线不能明显超出实测范围（防止拟合在数据缺口处发散）
    if total.max() > y.max() * 1.3 + 0.15 or total.min() < y.min() - 0.5:
        return None
    k = int(np.argmax(total))
    comps = []
    for kk in range(best['n']):
        off = best['deg'] + 1 + 4 * kk
        p = best['popt'][off:off + 4]
        comps.append(_voigt_shape(grid, *p))
    out = dict(
        lam=x, A=y, peaks=best['peaks'], r2=best['r2'], n=best['n'],
        deg=best['deg'], popt=best['popt'], x0=best['x0'],
        grid=grid, total=total, components=comps,
        lam_max=float(grid[k]), A_max=float(total[k]),
        baseline=_voigt_model(grid, np.r_[best['popt'][:best['deg'] + 1],
                                          np.zeros(4 * best['n'])],
                              best['deg'], 0, best['x0']),
    )
    return out


def voigt_eval(fit, x):
    """在任意 x 上计算分峰拟合的总曲线。"""
    if not fit:
        return np.zeros_like(np.asarray(x, float))
    return _voigt_model(np.asarray(x, float), fit['popt'], fit['deg'], fit['n'],
                        fit['x0'])


def molar_extinction(A, conc_umol, path_cm=PATH_LENGTH_CM):
    """ε = A/(c·b)，c 由 μmol·L⁻¹ 换成 mol·L⁻¹，返回 L·mol⁻¹·cm⁻¹。"""
    if not np.isfinite(A) or not conc_umol:
        return float('nan')
    return A / (conc_umol * 1e-6 * path_cm)


# ---------------------------------------------------------------- 线性拟合
def line_fit(x, y):
    """最小二乘 y = k x + b，返回斜率/截距及其标准误差与 R²。

    ⚠ 先剔掉含 NaN/Inf 的点：`np.linalg.lstsq` 遇到 NaN 会抛
    `LinAlgError: SVD did not converge`（本模块是全仓唯一没做掩码的
    line_fit，其余模块的版本都有 isfinite 过滤）。
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 2:
        return dict(k=float('nan'), b=float('nan'), sigma_k=float('nan'),
                    sigma_b=float('nan'), r2=float('nan'), n=n)
    A = np.vstack([x, np.ones_like(x)]).T
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    pred = A @ coef
    ss = np.sum((y - pred) ** 2)
    sst = np.sum((y - y.mean()) ** 2)
    # y 全相同时 sst == 0，此时 R² 没有定义（原来返回 1.0，报告会显示
    # 「完美拟合」而斜率实际为 0），改成 nan。
    r2 = 1 - ss / sst if sst > 0 else float('nan')
    if n > 2:
        s2 = ss / (n - 2)
        s = np.sqrt(max(s2, 0.0))
        sxx = np.sum((x - x.mean()) ** 2)
        sigma_k = s / np.sqrt(sxx) if sxx > 0 else float('nan')
        sigma_b = s * np.sqrt(1.0 / n + x.mean() ** 2 / sxx) if sxx > 0 else float('nan')
    else:
        sigma_k = sigma_b = float('nan')
    return dict(k=float(coef[0]), b=float(coef[1]), sigma_k=float(sigma_k),
                sigma_b=float(sigma_b), r2=float(r2), n=n)


# ---------------------------------------------------------------- 一维势箱
def particle_in_box(lambdas, a_values=(0, 2, 4, 6, 8, 10)):
    """A 组（Ai：i 个 C-C=C + 2 个芳香基团）的一维势箱拟合。

    L = i·x + 2y，N = 2i + 2a，λ_i = K·L²/(2i+2a+1)。
    用 A1 (i=1) 与 A4 (i=4) 解出 x、y，再预测 A2 (i=2)、A3 (i=3)。

    lambdas = {'A1': λ1, 'A4': λ4, ...}（nm）
    """
    l1 = lambdas.get('A1')
    l4 = lambdas.get('A4')
    rows = []
    for a in a_values:
        if not (l1 and l4 and np.isfinite(l1) and np.isfinite(l4)):
            rows.append(dict(a=a, x=float('nan'), y=float('nan'),
                             lam2=float('nan'), lam3=float('nan')))
            continue
        u = np.sqrt(l1 * (2 * a + 3) / BOX_K)      # x + 2y
        v = np.sqrt(l4 * (2 * a + 9) / BOX_K)      # 4x + 2y
        x = (v - u) / 3.0
        y = (u - x) / 2.0
        lam2 = BOX_K * (2 * x + 2 * y) ** 2 / (2 * a + 5)
        lam3 = BOX_K * (3 * x + 2 * y) ** 2 / (2 * a + 7)
        rows.append(dict(a=a, x=float(x), y=float(y),
                         lam2=float(lam2), lam3=float(lam3)))
    return rows


def box_length(x, i_units):
    """B 组：给定每个 C-C=C 的箱长贡献 x 与基团数（可给范围），返回 L 范围。"""
    lo, hi = (i_units if isinstance(i_units, (tuple, list)) else (i_units, i_units))
    return lo * x, hi * x


def box_lambda(L_nm, n_elec):
    """λ(nm) = K·L²/(2n+1)，n_elec 为 π 电子数。"""
    return BOX_K * L_nm ** 2 / (n_elec + 1)
