# -*- coding: utf-8 -*-
"""docx 排版三查：正斜体 / 上下标 / 中英文之间的多余空格。

## 为什么还要再写一个（已有的不够用）

* ``tests/check_italic.py`` 只看**斜体 run**，也就是只能发现
  「把该正体的排成了斜体」。反过来 —— **该斜体却排成正体** —— 它一个都报不出来。
  而用户抓到过的 `注：…量热计常数 W`、标题里的 `W` 全是这一类的漏网。
* ``tests/audit_docx.py`` 有 ``math.italic``，但只认「Λ 在公式里被排成正体」
  这一条特例，正文层的变量正体化同样查不到。
* 中英文之间多余空格（`测得 蔗糖`、`Δ Q = 4.1471 kJ` 之外的 `我们 使用`）两边都没有。

## 三条判据（口径来自 SKILL.md 3.2 与用户 2026-11-04 硬规范）

1. **斜体**：单字母变量、小写希腊字母、作为量符号的大写希腊字母（Λ Ω）
   必须斜体；单位、化学式、函数名（ln/lg/exp/sin…）、说明性下标、
   编号（A3/GPL-3.0）、大写算子希腊字母（Δ Σ ∂）必须正体。
2. **上下标**：``m_{Ni-1}`` 这类必须渲染成真 ``w:vertAlign``；
   文字里残留 ``_{`` / ``^{`` / Unicode 上下标（⁻¹ ² ₃）/ 裸下划线都算错。
3. **空格**：中文与西文/数字之间**不该有空格**（中文排版惯例 + 本报告一直的写法），
   但**西文与西文之间**的空格是正常的（``Δ Q``、``5 X`` 这种量+单位要按规范留）。

用法：
    python check_typesetting.py 报告.docx [报告2.docx ...]
    python check_typesetting.py --dir <目录>
"""
from __future__ import annotations

import re
import sys
import zipfile
from xml.etree import ElementTree as ET

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
NS = {'w': W, 'm': M}


def _q(tag):
    return '{%s}%s' % (W, tag)


# ---------------------------------------------------------------- 词表
GREEK_LOWER = 'αβγδεζηθικλμνξοπρστυφχψω'
GREEK_UPPER = 'ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ'
#: 大写希腊字母里属于**算子**的：必须正体（ISO 80000-2 / 用户明确要求）
GREEK_OPERATORS = set('ΔΣΠ∂∇∏∐')
#: 大写希腊字母里属于**量符号**的：必须斜体（Λ 摩尔电导率、Ω 电阻、Φ 等）
GREEK_QUANTITIES = set('ΛΩΦΓΘΞ')

#: 数学函数名，必须正体
MATH_FUNCS = {'ln', 'lg', 'exp', 'sin', 'cos', 'tan', 'log', 'max', 'min',
              'arcsin', 'arccos', 'arctan', 'sinh', 'cosh', 'tanh', 'lim'}
#: 单位 / 化学式 / 专名，正体正确（小写白名单，避免误报）
UPRIGHT_WORDS = {
    'nm', 'cm', 'mm', 'm', 'km', 'dm', 'Pa', 'kPa', 'MPa', 'mol', 'mmol',
    'μmol', 'mol', 'min', 'ms', 'ns', 'kJ', 'J', 'K', 's', 'h', 'g', 'mg',
    'kg', 'L', 'mL', 'μL', 'V', 'mV', 'A', 'mA', 'Ω', 'S', 'Hz', 'MHz',
    'in', 'at', 'vs', 'of', 'the', 'and',
}
#: 已知误报（斜体其实正确）：一维势箱里 i·x 相乘
KNOWN_FP = {'ix'}

#: 允许保持正体的单字母（单位）。只放**确实该正体**的，别把变量塞进来。
#: 注意拉丁单字母的「该斜体却正体」判据已整体取消（见 check_italic 的注释），
#: 这张表只用于「不一致」判据里排除单位。
UPRIGHT_LETTERS = set('LNMSVWKATJgshm')

#: **明确是变量**的单字母白名单（只收几乎不可能当单位/代号用的）。
#: 这张表存在的原因：一致性判据抓不到「全文从未斜体过一次」的漏网
#: （实测电导率 4.2 节的 `y`、`x` 整段正体，一眼可见但一致性判据沉默）。
#:
#: ⚠ 只收 x / y。**不要**收 c、r、n：
#:   `b 管液面`/`c 管液面`（蒸气压）是**玻璃管标号**，正体正确；
#:   `纯水一行 c = 0`（表面吸附）里的 c 是浓度变量，但同一份报告里
#:   `c 管`那种用法无法与它区分，收进来就是一半误报。
#: 宁可漏报几个，也不要让用户在一屏噪音里挑真问题。
KNOWN_VARIABLES = set('xy')

#: 跟在 SI 词头（μ）后面、构成单位主体的字母串
_SI_UNIT_BODY = {
    'A', 'S', 'F', 'H', 'V', 'W', 'J', 'K', 'm', 'g', 's', 'L', 'l',
    'mol', 'M', 'N', 'Pa', 'Hz', 'C', 'T', 'lx', 'lm', 'Bq', 'Gy', 'Sv',
    'kat', 'rad', 'sr', 'eV',
}

#: 参考文献段落：人名首字母、[M]/[J] 类型标识都该正体
_REFS_RE = re.compile(r'^\s*\[\d+\]|\[(?:M|J|D|C|R|S|N|P|G|Z|A|EB/OL|J/OL)\]')


def _is_refs(ptxt):
    """参考文献段落豁免。

    文献条目里的单字母全是人名首字母与文献类型标识：
        [2] Haynes W M. CRC Handbook…
        [1] …物理化学实验[M]. 北京：…
    `W`/`M`/`D` 这些按规范是正体，报出来纯属噪音。
    """
    return bool(_REFS_RE.search(ptxt))

#: 中文（含常见中文标点）判定
CJK_RE = re.compile(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]')
#: 西文字母 / 数字
LATIN_RE = re.compile(r'[A-Za-z0-9]')


def _runs(p):
    """按顺序产出段落里的 (text, italic, math, script)。

    script ∈ {'', 'sub', 'sup'}；math=True 表示来自 m:r（Word 数学区）。
    """
    out = []
    for node in p.iter():
        tag = node.tag
        if tag == _q('r'):
            text = ''.join(t.text or '' for t in node.findall('w:t', NS))
            if not text:
                continue
            italic = False
            script = ''
            rpr = node.find('w:rPr', NS)
            if rpr is not None:
                i = rpr.find('w:i', NS)
                italic = i is not None and i.get(_q('val')) not in ('0', 'false')
                va = rpr.find('w:vertAlign', NS)
                if va is not None:
                    v = va.get(_q('val'))
                    script = 'sub' if v == 'subscript' else (
                        'sup' if v == 'superscript' else '')
            out.append((text, italic, False, script))
        elif tag == '{%s}r' % M:
            text = ''.join(t.text or '' for t in node.findall('m:t', NS))
            if not text:
                continue
            sty = node.find('.//m:sty', NS)
            plain = sty is not None and sty.get('{%s}val' % M) in ('p', 'b')
            # 数学区里的上下标由 m:sSub/m:sSup 承载，这里不追父子关系，
            # 只标 math=True（区分「数学区默认斜体」与正文 run）
            out.append((text, not plain, True, ''))
    return out


# ================================================================ 1) 正斜体
# ---------------------------------------------------------------- run 序列
def _run_seq(p):
    """把段落拆成字符序列：[(char, italic, math, script, run_index), …]。"""
    seq = []
    ridx = 0
    for node in p.iter():
        tag = node.tag
        if tag == _q('r'):
            text = ''.join(t.text or '' for t in node.findall('w:t', NS))
            if not text:
                continue
            italic = False
            script = ''
            rpr = node.find('w:rPr', NS)
            if rpr is not None:
                i = rpr.find('w:i', NS)
                italic = i is not None and i.get(_q('val')) not in ('0', 'false')
                va = rpr.find('w:vertAlign', NS)
                if va is not None:
                    v = va.get(_q('val'))
                    script = 'sub' if v == 'subscript' else (
                        'sup' if v == 'superscript' else '')
            for ch in text:
                seq.append((ch, italic, False, script, ridx))
            ridx += 1
        elif tag == '{%s}r' % M:
            text = ''.join(t.text or '' for t in node.findall('m:t', NS))
            if not text:
                continue
            sty = node.find('.//m:sty', NS)
            plain = sty is not None and sty.get('{%s}val' % M) in ('p', 'b')
            for ch in text:
                seq.append((ch, not plain, True, '', ridx))
            ridx += 1
    return seq


#: 化学式 / 仪器型号 / 单位组合：这些里的字母整体正体，绝不单独判
_CHEM_TOKEN = re.compile(
    r'(?:[A-Z][a-z]?\d*(?:[A-Z][a-z]?\d*)+)'          # NaCl / H2O / KNO3
    r'|(?:[A-Z][a-z]?\d+)'                             # O2 / N2 / C12
    r'|(?:[A-Z]{2,}[\w\-]*)'                           # DDSJ-307F / HCl
)
#: 单位串：mol·dm−3 / S·m2·mol−1 / μS·cm−1 / kJ·mol−1 …
_UNIT_TOKEN = re.compile(
    r'(?:[a-zA-Zμ]+)·(?:[a-zA-Zμ]+[⁻⁰¹²³⁴⁵⁶⁷⁸⁹−]*)(?:·?[a-zA-Zμ]+[⁻⁰¹²³⁴⁵⁶⁷⁸⁹−]*)*'
)
#: 变量名后紧跟的合法符号（说明它已是完整符号，不是漏斜体）
_SYM_FOLLOW = set('0123456789()（）+-−±.,，。:：;；\'′"')


def _protected_spans(text):
    """算出不该做正斜体判断的字符区间（化学式、单位、人名、型号等）。"""
    spans = []
    for pat in (_CHEM_TOKEN, _UNIT_TOKEN):
        for m in pat.finditer(text):
            spans.append((m.start(), m.end()))
    return spans


def _in_spans(pos, spans):
    return any(a <= pos < b for a, b in spans)


def check_italic(path):
    """返回 (漏斜体, 误斜体)。判据见模块 docstring。"""
    z = zipfile.ZipFile(path)
    doc = ET.fromstring(z.read('word/document.xml'))
    body = doc.find('.//w:body', NS)

    missing = []
    wrong = []

    for p in body.iter(_q('p')):
        ptxt = ''.join(c for c, _i, _m, _s, _r in _run_seq(p))
        if not ptxt.strip() or _is_refs(ptxt):
            continue
        seq = _run_seq(p)
        text = ''.join(c for c, *_ in seq)
        spans = _protected_spans(text)

        # ---- 统计全文里该符号「有没有出现过斜体」，用于一致性判据
        italic_seen = {}
        for idx, (ch, it, math, script, _ri) in enumerate(seq):
            if script:
                continue                     # 下标里的说明文字单独处理
            if ch in GREEK_LOWER or ch in GREEK_QUANTITIES:
                italic_seen.setdefault(ch, False)
                if it:
                    italic_seen[ch] = True
            elif ch.isascii() and ch.isalpha():
                if _isolated_latin(text, idx):
                    italic_seen.setdefault(ch, False)
                    if it:
                        italic_seen[ch] = True

        for idx, (ch, it, math, script, _ri) in enumerate(seq):
            if script or _in_spans(idx, spans):
                continue
            # ---------- 希腊字母（唯一保留的「该斜体却正体」判据）
            #
            # ⚠ 拉丁单字母**不做**这个判断。实测燃烧热会因此报出 41 处噪音：
            #   `0.0103 g` 的 g、`0.71 s` 的 s、`-305.9 J` 的 J 都是单位；
            #   `电极B` 是器件代号（规范明确正体）；
            #   `Qp`/`CV` 是 Q+下标p 被切开，不是孤立单字母。
            # 要可靠地区分「变量 vs 单位 vs 代号」需要一张覆盖全部学科的
            # 词表，做不到就不做 —— 宁可少报，也不要让用户在一屏噪音里
            # 找那几条真问题。拉丁单字母只保留下面「一致性」这一条判据。
            if ch in GREEK_LOWER or ch in GREEK_QUANTITIES:
                if ch == 'Ω' and re.search(r'\d\s*$', text[:idx]):
                    continue                 # 电阻单位 Ω
                if it:
                    continue
                if not _is_standalone_symbol(text, idx):
                    continue
                if italic_seen.get(ch):
                    missing.append(('inconsistent-greek', ch,
                                    text[max(0, idx-30):idx+30]))
                else:
                    missing.append(('greek-upright', ch,
                                    text[max(0, idx-30):idx+30]))
                continue
            # ---------- 拉丁单字母：只报「不一致」，外加一张很小的变量白名单
            if not (ch.isascii() and ch.isalpha()):
                continue
            if not _isolated_latin(text, idx):
                continue
            if ch in UPRIGHT_LETTERS:
                continue
            if not _is_standalone_symbol(text, idx):
                continue
            if it:
                continue
            if italic_seen.get(ch):
                missing.append(('inconsistent-latin', ch,
                                text[max(0, idx-30):idx+30]))
            elif ch in KNOWN_VARIABLES:
                # 白名单里的字母（x/y/r/n…）几乎不可能是单位或器件代号，
                # 出现即应斜体。这是「从未斜体过」那类漏网唯一能可靠抓到的
                # 办法：一致性判据对它无效（全文都没有斜体样本）。
                missing.append(('latin-upright', ch,
                                text[max(0, idx-30):idx+30]))

        # ---------- 误斜体：整词（≥2 字母）不是函数名。
        #
        # ⚠ 这一项的判据必须看**整个词是否统一斜体**，不能只看开头。
        # 实测的误报全部是「变量 + 下标」被拼成整词：`qV`、`msam`、`qd`、
        # `mw`、`Kcell`、`Qp`、`CV` —— 主字母斜体是对的，下标（V/sam/d/w）
        # 按规范是正体或斜体各有规定，整词看起来「全是斜体」其实并不统一。
        # 真正该报的误斜体是 `Voigt`、`mol`、`A3` 这种**整词一致斜体**
        # 而本身又不是变量的情况。
        for idx, (ch, it, math, script, _ri) in enumerate(seq):
            if not it or script or math:
                continue
            m = re.match(r'[A-Za-z]{2,}', text[idx:])
            if not m:
                continue
            if idx > 0 and text[idx-1].isascii() and text[idx-1].isalpha():
                continue
            word = m.group(0)
            end = idx + len(word)
            # 词内所有字符必须**全部**来自斜体 run，才算「整词斜体」
            if not all(seq[k][1] for k in range(idx, end)):
                continue
            # 后面紧跟下标/上标 run → 变量+下标组合，跳过
            follow_script = False
            k = end
            while k < len(seq) and seq[k][0].isspace():
                k += 1
            if k < len(seq) and seq[k][3]:
                follow_script = True
            if follow_script:
                continue
            if word in MATH_FUNCS or word in KNOWN_FP:
                continue
            if re.fullmatch(r'[ij]+', word):
                continue
            # 短组合（≤3 字母、首字母大写或含大小写交替）多为变量+下标，
            # 例如 Qp / Ka / Er / qd / mw —— 不报。
            if len(word) <= 3:
                continue
            wrong.append(('word', word, text[max(0, idx-30):idx+30]))
            break                            # 每段只报一次
    return missing, wrong


def _isolated_latin(text, idx):
    """text[idx] 是否是「孤立」的拉丁字母（左右都不是 ASCII 字母）。"""
    ch = text[idx]
    if not (ch.isascii() and ch.isalpha()):
        return False
    if idx > 0 and text[idx-1].isascii() and text[idx-1].isalpha():
        return False
    if idx + 1 < len(text) and text[idx+1].isascii() and text[idx+1].isalpha():
        return False
    return True


def _is_standalone_symbol(text, idx):
    """该字符是否作为一个**独立符号的头部**出现。

    若它后面紧跟数字/括号/撇号（`C'`、`R1`、`m(`），或前一个字符是数字
    （`10−3` 的 `3` 之类），说明它是某个完整记法的一部分，由相邻字符共同
    表达语义，不单独判正斜体。

    ⚠ 还有一类必须排除：**希腊字母作为词头单位**。
        `μA`（微安）、`μS·cm−1`（微西门子）、`μmol`、`μm`、`μL`
    这里的 μ 是 SI 词头，**必须正体**。实测漏报集中在这些单位上
    （电化学的 `μA`、紫外光谱的 `μmol·L−1`）。
    判据：后面紧跟的字母串本身是已知单位，且不是变量。
    """
    ch = text[idx]
    nxt = text[idx+1] if idx + 1 < len(text) else ''
    prv = text[idx-1] if idx > 0 else ''
    if nxt and nxt in _SYM_FOLLOW:
        return False
    if prv and prv.isdigit():
        return False
    # 词头单位：μ + 单位字母
    if ch == 'μ':
        m = re.match(r'[A-Za-z]+', text[idx+1:])
        if m and m.group(0) in _SI_UNIT_BODY:
            return False
    return True


#: 跟在 SI 词头后面、构成单位主体的字母串
_SI_UNIT_BODY = {
    'A', 'S', 'F', 'H', 'V', 'W', 'J', 'K', 'm', 'g', 's', 'L', 'l',
    'mol', 'M', 'N', 'Pa', 'Hz', 'C', 'T', 'lx', 'lm', 'Bq', 'Gy', 'Sv',
    'kat', 'rad', 'sr', 'eV',
}

# ================================================================ 2) 上下标
#: 文字里残留的上下标标记
_RAW_MARK = re.compile(r'[\w)₂₃₄][_^]\{')
#: Unicode 上下标字符
UNI_SUB = set('₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₔₕₖₗₘₙₚₛₜ')
UNI_SUP = set('⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ')
#: 裸下划线：字母_字母，但不是 _{...} 标记
_BARE_UNDER = re.compile(r'[A-Za-zα-ωΑ-Ω]_[A-Za-z0-9](?!\})')


def check_scripts(path):
    z = zipfile.ZipFile(path)
    doc = ET.fromstring(z.read('word/document.xml'))
    body = doc.find('.//w:body', NS)
    problems = []
    for p in body.iter(_q('p')):
        ptxt = ''.join(t.text or '' for t in p.iter(_q('t')))
        for t in p.iter(_q('t')):
            text = t.text or ''
            if not text:
                continue
            m = _RAW_MARK.search(text)
            if m:
                problems.append(('raw-marker', m.group(0), ptxt[:60]))
            bad = sorted(set(text) & (UNI_SUB | UNI_SUP))
            if bad:
                problems.append(('unicode-script', ''.join(bad), ptxt[:60]))
            m = _BARE_UNDER.search(text)
            if m:
                problems.append(('bare-underscore', m.group(0), ptxt[:60]))
    # 公式区里的 ^ / _ 残留（OMML 没认出来的命令）
    for t in doc.iter('{%s}t' % M):
        text = t.text or ''
        if '\\' in text:
            problems.append(('math-backslash', text.strip()[:30], ''))
    return problems


# ================================================================ 3) 空格
#
# ⚠ 这一项最容易做成噪音。第一版按「中文↔西文相邻且有空格」判定，
# 一份报告报了 187 处，而逐条看下去全是**规范要求的正常空格**：
#
#     3 组 8 号          数字与汉字之间要留空格（GB/T 15834）
#     2.1 仪器和试剂      编号与标题之间
#     KCl 溶液           西文与汉字之间
#     25 ℃               数值与单位
#     NaCl、NaAc、HCl    顿号列举
#
# 用户指的「不必要的空格」是另一类：**两个中文词之间多打了一个空格**，
# 例如 `本实验测得 蔗糖的…`、`我们 使用 了…`。这在中文排版里是明确的错，
# 而且确实是 report.py 里手写字符串时容易多打的。
#
# 所以判据改成：空格两侧**都是汉字**，且不是下列合法情形——
#   · 中文标点之后/之前（、。，；：！？（）「」等本身自带间距）
#   · 一级标题/章节编号形式（数字 空格 汉字 已排除，因为左侧不是汉字）
#
# 这样只会命中「汉字 空格 汉字」这一种真正多余的空格。
_CJK_CHAR = r'\u4e00-\u9fff'
#: 汉字 + 空格 + 汉字；空格限定为半角/全角/NBSP
_HAN_SPACE_HAN = re.compile(
    r'([%s])([ \u3000\u00a0]+)([%s])' % (_CJK_CHAR, _CJK_CHAR))


#: 封面信息表的字段名用空格对齐（`姓    名：`），是模板的排版手法，不是笔误。
#: 命中「汉字+空格+汉字」且整段很短、以冒号结尾的，一律豁免。
_COVER_FIELD_RE = re.compile(r'^[^。，；]{1,12}[：:]\s*$')

#: `摘要 ` / `关键词 ` 这两个标签后的空格是课程模板的既定写法（标签加粗后
#: 与正文之间留一格），报告一直这么排，不算多余空格。
_LABEL_PREFIX_RE = re.compile(r'^(摘要|关键词)\s')


# ---------------------------------------------------------------- 误报豁免
#
# ⚠ 这两类必须排除，否则「漏斜体」全是噪音（实测 16 处里 16 处都是它们）：
#
# 1. **化学式里的单字母**：`O2`/`N2`/`C12H22O11` 里的 O、N、C、H 是元素符号，
#    规范要求化学式**整体正体**。检测器把 `O2 饱和下` 切成 `O` + `2` 两个 run，
#    只看到孤立的 `O` 就报「单字母变量没斜体」。
# 2. **上标引用编号**：`R1−R2` 里的 `1` 其实是 `^{[1]}` 之类被拆开后的残余，
#    或者 `KCl`/`HCl` 之类的化学式片段。
#
# 判据：看这个单字母 run **前后紧邻的字符**。若紧邻的是元素符号/数字
# （O2、C12、H22），或来自已知化学式上下文，就算化学式，豁免。
_CHEM_NEIGHBOR = re.compile(r'(?:[A-Z][a-z]?\d*|[A-Z])$')
#: 常见化学式整体（在一段文字里搜到就说明该段在讲化学式）
_CHEM_IN_TEXT = re.compile(
    r'(?:[A-Z][a-z]?\d+){2,}'          # C12H22O11 / KNO3 / NaCl 这种多段
    r'|[A-Z][a-z]?\d'                   # O2 / N2 / H2O
)


def _is_chem_context(ptxt, letter):
    """该段是否处在化学式语境里（按整段判断，抗 run 切分）。"""
    return bool(_CHEM_IN_TEXT.search(ptxt))


class _RunCtx:
    """给整段做一次 run 序列快照，用来判断「单字母 run 是不是半个符号」。

    ⚠ 这是把误报压下去的关键。`pK_a` 渲染成三个 run：`p`(正体) `K`(斜体)
    `a`(斜体下标)。只看孤立的 `K` 会报「该斜体的单字母却是正体/该正体却斜体」，
    但实际排版完全正确 —— 它是 `pK_a` 的一部分，`p` 本来就该正体。
    同理 `C'空` 里的 `C`、`h_left` 里的 `h`。
    """

    def __init__(self, runs):
        self.runs = runs

    def neighbor_letters(self, idx):
        """取该 run 左右相邻 run 里的字母（判断是否属于同一个符号）。"""
        out = []
        for j in (idx - 1, idx + 1):
            if 0 <= j < len(self.runs):
                txt = self.runs[j][0]
                letters = ''.join(c for c in txt if c.isalpha())
                out.append(letters)
        return out


def _letter_is_chem(text, pos):
    """text[pos] 这个字母是否属于化学式（后面紧跟数字，或前面是大写元素）。"""
    after = text[pos + 1:pos + 3]
    before = text[max(0, pos - 2):pos]
    if re.match(r'^\d', after):
        return True
    if _CHEM_NEIGHBOR.search(before):
        return True
    return False


def check_spaces(path):
    z = zipfile.ZipFile(path)
    doc = ET.fromstring(z.read('word/document.xml'))
    body = doc.find('.//w:body', NS)
    problems = []
    for p in body.iter(_q('p')):
        ptxt = ''.join(t.text or '' for t in p.iter(_q('t'))).strip()
        # 封面字段名（`姓    名：`）是模板对齐手法，豁免
        if _COVER_FIELD_RE.match(ptxt):
            continue
        # `摘要 ` / `关键词 ` 标签后的那一格是模板既定写法，豁免
        body_text = _LABEL_PREFIX_RE.sub('', ptxt)
        skipped = len(ptxt) - len(body_text)
        for t in p.iter(_q('t')):
            text = t.text or ''
            for m in _HAN_SPACE_HAN.finditer(text):
                # 落在标签后那一格里的命中不算
                if skipped:
                    continue
                left, gap, right = m.group(1), m.group(2), m.group(3)
                shown = (left + gap.replace('\u3000', '<全角>')
                         .replace('\u00a0', '<NBSP>').replace(' ', '<空格>')
                         + right)
                problems.append(('汉字 空格 汉字', shown, ptxt[:70]))
    return problems


# ================================================================ 汇总
def audit(path):
    mi, wi = check_italic(path)
    sc = check_scripts(path)
    sp = check_spaces(path)
    return {'missing_italic': mi, 'wrong_italic': wi,
            'scripts': sc, 'spaces': sp}


def main(argv):
    paths = []
    if argv and argv[0] == '--dir':
        import glob
        import os
        base = argv[1]
        for root, _dirs, files in os.walk(base):
            for f in sorted(files):
                if f.endswith('.docx') and not f.startswith('~$'):
                    paths.append(os.path.join(root, f))
    else:
        paths = [a for a in argv if a.endswith('.docx')]
    if not paths:
        print('用法：python check_typesetting.py 报告.docx  或  --dir <目录>')
        return 2
    total = 0
    for path in paths:
        r = audit(path)
        n = sum(len(v) for v in r.values())
        total += n
        print('=' * 74)
        # 报告名统一是「自检报告.docx」，看不出模块；用所在目录名区分
        import os
        parent = os.path.basename(os.path.dirname(path))
        label = parent if parent and parent != '自检报告' else os.path.basename(path)
        print('%s   （%d 处）' % (label, n))
        for key, label in (('wrong_italic', '误斜体（该正体）'),
                           ('missing_italic', '漏斜体（该斜体）'),
                           ('scripts', '上下标'),
                           ('spaces', '中文西文间空格')):
            items = r[key]
            if not items:
                continue
            print('  -- %s：%d 处' % (label, len(items)))
            seen = set()
            for item in items:
                sig = (item[0], item[1])
                if sig in seen:
                    continue
                seen.add(sig)
                print('     %-22s %-10r  %s' % (item[0], item[1], item[2][:50]))
            if len(items) > len(seen):
                print('     …（去重后 %d 种，共 %d 处）' % (len(seen), len(items)))
    print()
    print('合计 %d 处' % total)
    return 0 if total == 0 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))