# -*- coding: utf-8 -*-
"""数据目录与数据文件的**可移植定位**。

解决的问题（换电脑 / 换学年 / 别人拿去用）：

1. **默认数据目录不能写死**。以前各模块要么默认 ``None``（打开后一片空白，
   必须自己点「选择文件夹」），要么默认到某台机器上的课程原始数据目录。
2. **文件名带时间戳，换一天就全变**。光谱仪/课程软件导出的名字形如
   ``2026-10-21 & 12-56-02-A3-0.txt``，把路径写死在代码里撑不过一次重测。
3. **文件多的时候要能找到**。一个学期的数据可能有几百个文件，界面上要能
   按关键字过滤。

本模块只做「定位与匹配」，不碰具体实验的语义；实验相关的候选目录/文件名
由各模块自己传进来。配套的前端组件在 ``web_files.js``，HTTP 端点在各模块的
``server.py`` 里接。

设计口径（与 ``紫外光谱工具/pcal/uv.py`` 已有的实现保持一致，那边是
2026-11-06 落地并逐位验证过的）：

    score = 0.74·语义后缀 + 0.20·整名 + 0.04·同目录 + 0.02·同时间戳

**权重之和必须正好 1.0 且不能提前饱和**——紫外光谱踩过 P0 级静默错数：
先算分再 ``min(1.0, score + 同目录分)`` 会把同目录加成吃掉，于是文件夹 ``1/``
与 ``2/`` 里的同名文件并列，排序退化成按路径字母序，静默选了错的那份，
报告数字全错而不报错。
"""
from __future__ import annotations

import difflib
import json
import os
import re

# ---------------------------------------------------------------- 常量
#: ≥ 此分自动采用（界面上标「自动匹配」，用户可改回）
FUZZY_ACCEPT = 0.80
#: ≥ 此分才列进候选
FUZZY_SUGGEST = 0.45

#: 视为「数据文件」的后缀（列目录时用）
DATA_EXTS = ('.csv', '.txt', '.xlsx', '.xls', '.xlsm', '.json', '.dat', '.tsv')

#: 找候选目录时最多往下走几层（学期数据常按 天/组 分子文件夹）
MAX_DEPTH = 4
#: 单个目录最多列多少个文件（防止把上千个文件塞进前端）
MAX_FILES = 4000


# ---------------------------------------------------------------- 套件根
def suite_root(tool_root):
    """工具目录的上一级 = 套件根（可移植包解压根 / 仓库根）。"""
    return os.path.dirname(os.path.abspath(tool_root))


def find_data_dir(tool_root, saved='', extra=(), tool_subdirs=()):
    """按优先级推一个**一定存在**的数据目录。

    参数
    ----
    tool_root : 工具目录（``os.path.join(ROOT, ...)`` 里的 ROOT）
    saved     : settings.json / profile.json 里记住的目录（存在才沿用）
    extra     : 该实验专用的候选（相对套件根或绝对路径）
    tool_subdirs : 相对工具目录的候选（如 ``('data', '样例数据')``）

    顺序：记住的 → 套件根/数据 → 各 extra → 工具子目录 → 工具目录本身。
    **最后一档保证返回一个存在的目录**，换机器不会抛 FileNotFoundError。
    """
    tool_root = os.path.abspath(tool_root)

    saved = (saved or '').strip().strip('"')
    if saved and os.path.isdir(saved):
        return saved

    suite = suite_root(tool_root)
    cands = [os.path.join(suite, '数据')]
    for item in extra or ():
        cands.append(item if os.path.isabs(item) else os.path.join(suite, item))
    for sub in tool_subdirs or ():
        cands.append(os.path.join(tool_root, sub))

    for path in cands:
        if path and os.path.isdir(path):
            return os.path.abspath(path)
    return tool_root


def describe_dir(path):
    """界面上显示用的目录描述：绝对路径 + 是否套件内的相对位置。"""
    path = os.path.abspath(path) if path else ''
    if not path:
        return {'path': '', 'exists': False, 'count': 0}
    return {
        'path': path,
        'exists': os.path.isdir(path),
        'count': len(list_data_files(path, limit=MAX_FILES + 1)) if os.path.isdir(path) else 0,
    }


# ---------------------------------------------------------------- 列文件
def list_data_files(data_dir, exts=DATA_EXTS, limit=MAX_FILES, recurse=True,
                    max_depth=MAX_DEPTH):
    """列出数据目录里的数据文件（**相对路径**，正斜杠分隔，按路径排序）。

    相对路径是刻意的：界面用它当「槽位映射」的值，换机器/搬家后只要文件名
    结构不变就还能匹配上；绝对路径只在真正读文件时拼。
    """
    data_dir = str(data_dir or '')
    if not data_dir or not os.path.isdir(data_dir):
        return []
    exts = tuple(e.lower() for e in (exts or DATA_EXTS))
    base_depth = data_dir.rstrip('\\/').count(os.sep)
    out = []
    for root, dirs, files in os.walk(data_dir):
        dirs[:] = sorted(d for d in dirs
                         if not d.startswith('.') and d != '__pycache__')
        depth = root.count(os.sep) - base_depth
        if depth >= max_depth:
            dirs[:] = []
        for fn in sorted(files):
            if not fn.lower().endswith(exts):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, data_dir).replace('\\', '/')
            out.append(rel)
            if len(out) >= limit:
                return out
        if not recurse:
            break
    return out


def resolve_rel(data_dir, rel):
    """相对路径 → 绝对路径（拒绝穿越到数据目录外面）。"""
    data_dir = os.path.abspath(str(data_dir or ''))
    if not data_dir:
        return ''
    target = os.path.normpath(os.path.join(data_dir, str(rel or '').replace('/', os.sep)))
    root = os.path.normpath(data_dir) + os.sep
    if not (target + os.sep).startswith(root) and target != os.path.normpath(data_dir):
        return ''
    return target


# ---------------------------------------------------------------- 模糊匹配
_STAMP_RE = re.compile(r'^[\s\d\-_.:/&+]*')
_TAG_TOK_RE = re.compile(r'[A-Za-z]+\d*|\d+|[^\x00-\x7f]')
#: 明确的复制/重命名后缀：`- 副本`、`副本`、`- copy`、`(2)`。
#: 这些**无歧义**——`(2)` 不会是数据语义的一部分。
_COPY_SUFFIX_RE = re.compile(
    r'(?:\s*-\s*副本|\s*副本|\s*-\s*copy|\s*\(\d{1,2}\))+$',
    re.IGNORECASE)

#: 尾号 `_数字` **有歧义**，默认不剥。
#:
#: `氘灯_2.txt` 是复制品，但电化学的 `N2_1 / N2_2 / N2_5` 是**三个不同扫速**
#: （0.1/0.2/0.5 V·s⁻¹）——剥成 `N2` 之后三个槽位同分并列，会互抢同一份文件，
#: 报告里的峰电流与电化学活性面积全错，而界面上看不出任何区别。
#: 这类「静默选错数据文件」是本项目最难发现的错误类别，所以默认宁可不剥：
#: 不剥的代价只是复制品评分略低（退成候选，用户点一下即可），可控。
_COPY_TAIL_NUM_RE = re.compile(r'_\d{1,2}$')


def _stem_of(rel):
    return os.path.splitext(os.path.basename(str(rel or '')))[0]


def split_stamp(rel, strip_tail_number=False):
    """把文件名拆成（时间戳前缀, 语义后缀）。

    ``2026-10-21 & 12-56-02-A3-0`` → (``2026-10-21 & 12-56-02-``, ``A3-0``)；
    没有时间戳的名字整串都算语义后缀。复制产生的 ``- 副本`` / ``(2)`` 先剥掉，
    否则同一份文件会被判成两个。

    ``strip_tail_number``：是否把尾号 ``_2`` 也当复制后缀剥掉。**默认关闭**，
    因为 ``N2_1 / N2_2 / N2_5`` 这类尾号有语义（不同扫速/不同浓度），
    剥掉会让多个槽位抢同一份文件（见 ``_COPY_TAIL_NUM_RE``）。
    """
    stem = _stem_of(rel)
    m = _STAMP_RE.match(stem)
    tag = stem[m.end():].strip(' -_')
    tag = _COPY_SUFFIX_RE.sub('', tag).strip(' -_') or tag
    if strip_tail_number:
        stripped = _COPY_TAIL_NUM_RE.sub('', tag).strip(' -_')
        tag = stripped or tag
    return stem[:m.end()].strip(), tag or stem


def tag_tokens(tag):
    """语义后缀 → 词元：``A3-5(2)`` → ``['a3', '5', '2']``。

    词元集合用来惩罚「多/少一个 -数字」这种差别
    （``A3-5`` 与 ``A3-5-2`` 是两次不同测量，不能混为一谈）。
    """
    return [m.group(0).lower() for m in _TAG_TOK_RE.finditer(tag or '')]


def _plain(s):
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', str(s or '').lower())


def _plain_stem(rel):
    return _plain(split_stamp(rel)[1])


def match_score(target, cand):
    """两个相对路径的相似度 0~1。

    权重之和正好 1.0，且**不提前饱和**：``0.74·语义后缀 + 0.20·整名 +
    0.04·同目录 + 0.02·同时间戳``。同目录这一项是分开「文件夹 1/ 与 2/ 里的
    同名文件」的唯一依据，所以绝不能让总分先被截到 1.0 再相加。
    """
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
            penalty = 1.0 - len(t_tok & c_tok) / float(max(len(t_tok), len(c_tok)))
            tag_sim *= (1.0 - 0.5 * penalty)
    # 整名相似度用剥掉时间戳/副本后缀的形式，免得 `(2)` 拖低同一份文件的分数
    full_sim = difflib.SequenceMatcher(
        None, _plain_stem(target), _plain_stem(cand)).ratio()

    score = 0.74 * tag_sim + 0.20 * full_sim
    t_dir = os.path.dirname(os.path.normpath(str(target)))
    c_dir = os.path.dirname(os.path.normpath(str(cand)))
    if os.path.normcase(t_dir) == os.path.normcase(c_dir) and t_dir not in ('', '.'):
        score += 0.04
    if t_stamp and t_stamp == c_stamp:
        score += 0.02
    return max(0.0, min(1.0, score))


def rank_candidates(target, files, top=6, min_score=FUZZY_SUGGEST):
    """给一个「默认文件名」找候选，按分数降序。

    返回 ``[{'rel':…, 'score':…, 'auto':bool, 'suggest':bool, 'why':…}]``。
    """
    out = []
    for rel in files or ():
        score = match_score(target, rel)
        if score <= 0:
            continue
        out.append({
            'rel': rel,
            'score': round(score, 4),
            'auto': score >= FUZZY_ACCEPT,
            'suggest': score >= min_score,
            'why': _reason(target, rel, score),
        })
    out.sort(key=lambda d: (-d['score'], d['rel']))
    return out[:top] if top else out


def _reason(target, cand, score):
    """一句话说明为什么匹配（给界面做提示，免得用户猜）。"""
    if os.path.basename(str(target)) == os.path.basename(str(cand)):
        return '文件名相同'
    t_dir = os.path.dirname(os.path.normpath(str(target)))
    c_dir = os.path.dirname(os.path.normpath(str(cand)))
    if t_dir != c_dir and _plain_stem(target) == _plain_stem(cand):
        return '同名文件（在不同文件夹）'
    t_stamp, t_tag = split_stamp(target)
    c_stamp, c_tag = split_stamp(cand)
    if t_tag and t_tag == c_tag:
        return '语义后缀相同'
    if t_stamp and t_stamp == c_stamp:
        return '同一时间戳'
    return '相似度 %.0f%%' % (score * 100)


def auto_match(target, files):
    """最高分若 ≥ FUZZY_ACCEPT 就自动采用，否则返回 ``None``。"""
    ranked = rank_candidates(target, files, top=2)
    if ranked and ranked[0]['auto']:
        return ranked[0]['rel']
    return None


# ---------------------------------------------------------------- 搜索
def search_files(files, query, limit=200):
    """在相对路径列表里按关键字过滤（给「文件较多时能搜索」用）。

    排序：完全包含子串的靠前，其次是**按子序列**命中（``a3c5`` 能命中
    ``A3-5-...``），最后是模糊相似度。空查询返回前 ``limit`` 项。
    """
    files = list(files or ())
    q = _plain(query)
    if not q:
        return files[:limit]

    exact, subseq, fuzzy = [], [], []
    for rel in files:
        hay = _plain(rel)
        if q in hay:
            # 越短的名字越贴题（A3-5.txt 比 2026-10-21...-A3-5-副本.txt 好）
            exact.append((len(hay), rel))
            continue
        # 子序列：查询的字符按顺序出现即算命中
        it = iter(hay)
        if all(ch in it for ch in q):
            subseq.append((len(hay), rel))
            continue
        ratio = difflib.SequenceMatcher(None, q, hay).ratio()
        if ratio >= 0.5:
            fuzzy.append((ratio, rel))

    exact.sort()
    subseq.sort()
    fuzzy.sort(reverse=True)
    out = [r for _, r in exact] + [r for _, r in subseq] + [r for _, r in fuzzy]
    return out[:limit]


# ---------------------------------------------------------------- 草稿
def dump_index(data_dir, files=None):
    """给前端一次拿全：目录 + 文件清单（够大时前端自己做过滤）。"""
    files = list_data_files(data_dir) if files is None else list(files)
    return {
        'dir': os.path.abspath(data_dir) if data_dir else '',
        'exists': bool(data_dir) and os.path.isdir(data_dir),
        'files': files,
        'total': len(files),
    }


# ---------------------------------------------------------------- 控制台输出
def safe_print(*args, **kwargs):
    """打印，但**绝不因为编码问题抛异常**。

    这个项目要在 Windows 的 GBK 控制台里跑（双击、`cmd`、计划任务）。
    自检脚本里的 `⚠`、`·`、`Δ`、`α` 这些字符编不出来会直接
    `UnicodeEncodeError` 把整个 `--test` 打断——而它只是打印一句提示。
    统一走这里：编不出来就替换成 `?`，流程继续。

    用法与 `print` 一致。
    """
    import sys
    out = kwargs.pop('file', None) or sys.stdout
    if out is None:                       # pythonw 下 stdout 是 None
        return
    sep = kwargs.pop('sep', ' ')
    end = kwargs.pop('end', '\n')
    text = sep.join(str(a) for a in args) + end
    try:
        out.write(text)
    except UnicodeEncodeError:
        enc = getattr(out, 'encoding', None) or 'ascii'
        try:
            out.write(text.encode(enc, 'replace').decode(enc, 'replace'))
        except Exception:                 # noqa: BLE001
            pass
    except (OSError, ValueError):
        pass
    try:
        out.flush()
    except Exception:                     # noqa: BLE001
        pass


if __name__ == '__main__':                      # 手测：python dataloc.py <目录>
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(json.dumps(dump_index(d), ensure_ascii=False, indent=2)[:3000])
