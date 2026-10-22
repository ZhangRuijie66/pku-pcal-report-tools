# -*- coding: utf-8 -*-
"""
极简 LaTeX -> OMML（Office Math Markup Language）转换器。

只覆盖物理化学实验报告所需的数学子集：
    花括号分组、上下标、\\frac、\\sqrt、\\sum、\\int、\\left\\right 定界符、
    希腊字母、常见算子与关系符、\\text{...}、\\mathrm{...}、\\;\\,\\ 间距、\\cdot \\times。

生成的是 Word 原生公式（可在 Word 中双击编辑），而不是图片或纯文本。
"""
from __future__ import annotations

import re

from xml.sax.saxutils import escape

M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

# ---------------------------------------------------------------- 符号表
GREEK = {
    r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ', r'\delta': 'δ', r'\Delta': 'Δ',
    r'\epsilon': 'ε', r'\varepsilon': 'ε', r'\zeta': 'ζ', r'\eta': 'η', r'\theta': 'θ',
    r'\Theta': 'Θ', r'\iota': 'ι', r'\kappa': 'κ', r'\lambda': 'λ', r'\Lambda': 'Λ',
    r'\mu': 'μ', r'\nu': 'ν', r'\xi': 'ξ', r'\pi': 'π', r'\Pi': 'Π', r'\rho': 'ρ',
    r'\sigma': 'σ', r'\Sigma': 'Σ', r'\tau': 'τ', r'\upsilon': 'υ', r'\phi': 'φ',
    r'\varphi': 'φ', r'\Phi': 'Φ', r'\chi': 'χ', r'\psi': 'ψ', r'\Psi': 'Ψ',
    r'\omega': 'ω', r'\Omega': 'Ω',
}

SYMBOLS = {
    r'\cdot': '⋅', r'\times': '×', r'\div': '÷', r'\pm': '±', r'\mp': '∓',
    r'\le': '≤', r'\leq': '≤', r'\ge': '≥', r'\geq': '≥', r'\ne': '≠', r'\neq': '≠',
    r'\approx': '≈', r'\equiv': '≡', r'\propto': '∝', r'\infty': '∞',
    r'\rightarrow': '→', r'\to': '→', r'\leftarrow': '←', r'\Rightarrow': '⇒',
    r'\partial': '∂', r'\nabla': '∇', r'\prime': '′',
    r'\ldots': '…', r'\cdots': '⋯', r'\dots': '…',
    r'\degree': '°', r'\circ': '∘', r'\angle': '∠',
    r'\sum': '∑', r'\prod': '∏', r'\int': '∫',
    r'\lbrack': '[', r'\rbrack': ']', r'\{': '{', r'\}': '}',
    r'\%': '%', r'\&': '&', r'\#': '#', r'\_': '_',
    r'\quad': '\u2003', r'\qquad': '\u2003\u2003',
    r'\;': '\u2009', r'\:': '\u2005', r'\,': '\u2006', r'\!': '',
    r'\\': '\u2003\u2003',          # 换行符在单行公式里当作宽间隔
}

RELATION_OPS = set('=<>≤≥≠≈≡∝→←⇒+-±∓⋅×÷')
BINARY_FUNCS = ('sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'log', 'ln', 'exp',
                'sinh', 'cosh', 'tanh', 'lim', 'max', 'min')

# 公式里的正斜体：拉丁字母与小写希腊字母是变量（斜体，走 Word 数学区默认），
# 大写希腊字母按 ISO 80000-2 用正体（Δ、Σ 不斜）。
_GREEK_UPPER = set('ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ')


def _math_sty(c):
    """数学 run 的字体样式：'i'（斜体，即不写 m:sty，用 Word 默认）/ 'p'（正体）。"""
    if not c.isalpha():
        return 'p'
    return 'p' if c in _GREEK_UPPER else 'i'

# ---------------------------------------------------------------- 化学式
# 元素符号（长的放前面，保证贪婪匹配正确）
_ELEMENTS = [e.strip() for e in (
    'He|Li|Be|Ne|Na|Mg|Al|Si|Cl|Ar|Ca|Sc|Ti|Cr|Mn|Fe|Co|Ni|Cu|Zn|Ga|Ge|As|Se|Br|'
    'Kr|Rb|Sr|Zr|Nb|Mo|Ru|Rh|Pd|Ag|Cd|In|Sn|Sb|Te|Xe|Cs|Ba|La|Ce|Pt|Au|Hg|Pb|Bi|'
    'H|B|C|N|O|F|P|S|K|V|Y|I|W|U').split('|')]
_ELEMENTS.sort(key=len, reverse=True)          # 长符号优先
_NUM_RE = re.compile(r'\d+(?:\.\d+)?')
_SUB_RE = re.compile(r'_\{([0-9]+)\}')


def _match_element(s, i):
    for e in _ELEMENTS:
        if s.startswith(e, i):
            return e
    return None


def _scan_chem(s, i):
    """
    从 s[i:] 尝试扫描一个化学式，返回结束位置或 None。

    语法： [系数]{元素}[_{下标}] 或 [系数](基团) 重复；至少出现一次“元素_下标”。
    注意每个 token 都必须真的吃进字符，否则像 'C_{12}...+' 里的 '+' 会被当成系数。
    """
    n = len(s)
    j = i
    saw_sub = False
    while j < n:
        start = j
        if s[j] == '(':
            k = s.find(')', j)
            if k < 0:
                return None
            j = k + 1
            continue
        el = _match_element(s, j)
        if el is None:
            m = _NUM_RE.match(s, j)          # 系数必须后面紧跟元素或括号
            if not m:
                break
            k = m.end()
            if k >= n or (_match_element(s, k) is None and s[k] != '('):
                break
            j = k
            continue
        j += len(el)
        sm = _SUB_RE.match(s, j)
        if sm:
            j = sm.end()
            saw_sub = True
        if j == start:
            break
    if j <= i or not saw_sub:
        return None
    return j


def _is_chem_span(s, i):
    """s[i:] 开头是否是一段化学式；返回结束下标或 None。"""
    if i > 0 and (s[i - 1].isalnum() or s[i - 1] in '_}{'):
        return None
    end = _scan_chem(s, i)
    if end is None:
        return None
    # 结尾不能把后面的公式命令截断（例如 C_{12}H_{22}O_{11}(s) 后的 + 没问题，
    # 但 'T' 后面紧跟字母就不该被当成元素）
    if end < len(s) and s[end] == '_':
        return None
    return end


def _chem_parts(formula):
    """
    把一个化学式片段拆成 [(元素, 下标或None)]，整体正体。
    下标必须挂在元素符号上（C_{12} 而不是 空的_{12}）。
    """
    parts = []
    i = 0
    n = len(formula)
    while i < n:
        m = _NUM_RE.match(formula, i)
        if m:
            parts.append((m.group(0), None))          # 化学计量系数
            i = m.end()
            continue
        if formula[i] == '(':
            j = formula.find(')', i)
            j = n - 1 if j < 0 else j
            parts.append((formula[i:j + 1], None))
            i = j + 1
            continue
        el = _match_element(formula, i)
        if el:
            i += len(el)
            sm = _SUB_RE.match(formula, i)
            sub = sm.group(1) if sm else None
            if sm:
                i = sm.end()
            parts.append((el, sub))
            continue
        parts.append((formula[i], None))
        i += 1
    return parts


def _braces_balanced(s):
    """s 里的花括号是否配对（用来判断能否在这里切开 tex / chem 片段）。"""
    depth = 0
    i = 0
    while i < len(s):
        c = s[i]
        if c == '\\':
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def to_omml_body(latex):
    """
    把 LaTeX 转成 oMath 内部 XML 片段（不带 <m:oMath> 外壳）。

    化学式（如 C_{12}H_{22}O_{11}、H_{2}O）会整段按正体排版，
    下标数字也用正体——这是化学式的标准写法。

    ⚠️ 切分 tex / chem 片段时必须检查花括号是否配对：像
    `\\frac{m}{M(KNO_{3})}` 这种，若在 `KNO_{3}` 处切开，前一段
    `\\frac{m}{M(` 的第二个花括号就没闭合，分母会被截断成 `M(`，
    剩下的 `KNO_{3})` 掉到分数线外面（真实踩过）。
    切不了就整段交给解析器，解析器自己认得化学式。
    """
    pieces = []
    pos = 0
    i = 0
    while i < len(latex):
        end = _is_chem_span(latex, i)
        if end and end > i and _braces_balanced(latex[pos:i]):
            if i > pos:
                pieces.append(('tex', latex[pos:i]))
            pieces.append(('chem', latex[i:end]))
            i = end
            pos = end
            continue
        i += 1
    if pos < len(latex):
        pieces.append(('tex', latex[pos:]))
    if not any(k == 'chem' for k, _ in pieces):
        pieces = [('tex', latex)]

    out = []
    for kind, seg in pieces:
        if kind == 'chem':
            for text, sub in _chem_parts(seg):
                if sub:
                    out.append(_s_sub(_mrun(text, 'p'), _mrun(sub, 'p')))
                else:
                    out.append(_mrun(text, 'p'))
            continue
        # 再按“单位”切段：单位用正体，其余照常按变量解析
        for sub_seg, is_unit in _upright_units(seg):
            if is_unit:
                _append_unit(out, sub_seg)
                continue
            p = _Parser(sub_seg)
            guard = 0
            while not p.eof():
                before = p.i
                out.append(p.parse_unit().xml)
                if p.i == before:
                    p.i += 1
                guard += 1
                if guard > 200000:
                    raise RuntimeError('OMML 解析超出步数上限：' + sub_seg[:120])
    return ''.join(out)


def _append_unit(out, text):
    """写出一段单位，整体正体。上下标要挂在单位符号上（K^{-1} 而不是 空的^{-1}）。"""
    i = 0
    n = len(text)
    while i < n:
        if text.startswith('\\cdot', i):
            out.append(_mrun('\u22c5', 'p'))
            i += 5
            continue
        if text.startswith('\\times', i):
            out.append(_mrun('\u00d7', 'p'))
            i += 6
            continue
        if text.startswith('\\,', i) or text.startswith('\\ ', i):
            out.append(_mrun('\u2009', 'p'))
            i += 2
            continue
        if text.startswith('\u22c5', i) or text.startswith('\u00b7', i):
            out.append(_mrun('\u22c5', 'p'))
            i += 1
            continue
        m = re.match(r'([A-Za-z]+|\([a-z]+\))', text[i:])
        if m:
            run = _mrun(m.group(1), 'p')
            i += m.end()
            # 紧跟的上下标直接挂到单位符号上（K^{-1} 而不是 空的^{-1}）
            m2 = re.match(r'(?:\^\{[^}]*\}|_\{[^}]*\})+', text[i:])
            if m2:
                for op, arg in re.findall(r'(\^|_)\{([^}]*)\}', m2.group(0)):
                    if op == '^':
                        run = _s_sup(run, _mrun(arg, 'p'))
                    else:
                        run = _s_sub(run, _mrun(arg, 'p'))
                i += m2.end()
            out.append(run)
            continue
        out.append(_mrun(text[i], 'p'))
        i += 1

# 单字母变量默认斜体（Word 数学区默认即斜体，函数名/单位用正体）
UPRIGHT_FUNCS = set(BINARY_FUNCS) | {'mol', 'g', 'mL', 'K', 's', 'J', 'kJ', 'Pa', 'kPa'}


# 公式里每个数学 run 的显式字号：五号 = 10.5 pt = 21 半磅，与正文一致。
# 不写的话公式继承 docDefaults（模板里恰好也是 21），写死可以避免换了模板以后
# 公式比正文大的情况。
_SZ = '<w:sz w:val="21"/><w:szCs w:val="21"/>'


def _mrun(text, sty='i'):
    """一个数学 run。sty: 'i' 斜体(默认), 'p' 正体。"""
    if text == '':
        return ''
    rpr = ''
    if sty == 'p':
        rpr = ('<m:rPr><m:sty m:val="p"/></m:rPr>'
               '<w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/>'
               + _SZ + '</w:rPr>')
    else:
        rpr = ('<w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/>'
               + _SZ + '</w:rPr>')
    return '<m:r>%s<m:t xml:space="preserve">%s</m:t></m:r>' % (rpr, escape(text))


class _Node:
    """把 OMML 片段按 变量/算子 分组，供上下标判定使用。"""

    def __init__(self, xml, is_atom=False, is_op=False):
        self.xml = xml
        self.is_atom = is_atom
        self.is_op = is_op


def _frac(num, den):
    return ('<m:f><m:fPr><m:ctrlPr><w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/>'
            '<w:i/></w:rPr></m:ctrlPr></m:fPr>'
            '<m:num>%s</m:num><m:den>%s</m:den></m:f>' % (num, den))


def _rad(inner):
    return ('<m:rad><m:radPr><m:degHide m:val="1"/>'
            '<m:ctrlPr><w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/><w:i/></w:rPr></m:ctrlPr>'
            '</m:radPr><m:deg/><m:e>%s</m:e></m:rad>' % inner)


def _s_sub(base, sub):
    return ('<m:sSub><m:sSubPr><m:ctrlPr><w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/>'
            '<w:i/></w:rPr></m:ctrlPr></m:sSubPr>'
            '<m:e>%s</m:e><m:sub>%s</m:sub></m:sSub>' % (base, sub))


def _upright_xml(xml):
    """把一段 oMath 片段里的变量 run 改成正体（<m:sty m:val="p"/>）。"""
    if '<m:rPr>' in xml:
        # 已有 rPr：把斜体去掉，补上正体
        xml = re.sub(r'<m:rPr>(?!<m:sty)', '<m:rPr><m:sty m:val="p"/>', xml)
        xml = xml.replace('<m:sty m:val="i"/>', '<m:sty m:val="p"/>')
        return xml
    return xml.replace('<m:r>', '<m:r><m:rPr><m:sty m:val="p"/></m:rPr>')


# 说明性下标白名单：多字母元素符号 / 英文缩写，按排版规范用正体。
# 单字母下标（V、c、m、p、r、w、H、C、N、O…）在数学语境里都是变量本身，保持斜体；
# 化学式里的单字母元素走 _CHEM_PAT 专门通道，不受这里影响。
UPRIGHT_SUBSCRIPTS = {
    # 多字母元素符号
    'Ni', 'Fe', 'Cu', 'Zn', 'Al', 'Ca', 'Mg', 'Na', 'Cl', 'Br', 'Ag', 'Pt', 'Hg', 'Pb',
    # 英文缩写
    'cot', 'tot', 'sam', 'Ni-1', 'Ni-2', 'max', 'min', 'out', 'in',
}


def _sub_is_upright(sub_xml):
    """下标是说明性文字（元素符号 / 缩写）时用正体，是变量时保持斜体。"""
    if '<m:sSub>' in sub_xml or '<m:frac' in sub_xml:
        return False
    txt = ''.join(re.findall(r'<m:t[^>]*>([^<]*)</m:t>', sub_xml)).strip()
    if not txt:
        return False
    if txt in UPRIGHT_SUBSCRIPTS:
        return True
    # 例如 m_{cot} 展开后可能带空格
    compact = txt.replace(' ', '')
    return compact in UPRIGHT_SUBSCRIPTS


# 简单下标（只有字母/数字/连字符/加号）：可以逐块决定正斜体。
#   V     -> 斜体（变量本身）
#   sam   -> 正体（说明性缩写）
#   Ni-1  -> 正体（元素符号 + 编号）
#   V-Ni  -> 斜体的 V + 正体的 Ni
_SIMPLE_SUB_RE = re.compile(r'^[A-Za-z0-9+\- ]+$')
_SUB_CHUNK_RE = re.compile(r'[A-Za-z]+|\d+|[^A-Za-z\d]+')


def _simple_sub_xml(txt):
    """把简单下标逐块排成正/斜体；不是简单下标时返回 None。"""
    if not txt or not _SIMPLE_SUB_RE.match(txt):
        return None
    out = []
    for m in _SUB_CHUNK_RE.finditer(txt):
        s = m.group(0)
        if not s.strip():
            continue
        sty = 'i' if (s.isalpha() and len(s) == 1) else 'p'
        out.append(_mrun(s, sty))
    return ''.join(out) or None


# ---------------------------------------------------------------- 单位
# 单位按排版规范要用正体；这里列出本报告会用到的单位符号。
_UNIT_MULTI = ('mol', 'kJ', 'Pa', 'kPa', 'MPa', 'mL', 'kg', 'min', 'cal', 'atm')
# 单字母单位。只收不会与常用物理量变量混淆的：
# 不收 V/W/N/C/A（既可能是单位也可能是变量），也不收 k/c（可能是变量）。
_UNIT_SINGLE = {'J', 'g', 'K', 's', 'm', 'L', 'h', 'l', 'N', 'A'}
_UNIT_TAIL = re.compile(r'(?:\^\{[^}]*\}|_\{[^}]*\})*')
# 状态符号 (s) (l) (g) (aq)
_STATE = ('(s)', '(l)', '(g)', '(aq)')


def _unit_token(s, i):
    """s[i:] 开头是否是一个单位符号；返回长度或 0。"""
    for u in _UNIT_MULTI:
        if s.startswith(u, i):
            # 后面必须紧跟分隔符 / 上下标 / 行尾，避免把 'molten' 之类切开
            k = i + len(u)
            if k >= len(s) or s[k] in ' \t\\^_.,;)}+-=·':
                return len(u)
    if i < len(s) and s[i] in _UNIT_SINGLE:
        k = i + 1
        if k >= len(s) or s[k] in ' \t\\^_.,;)}+-=·':
            return 1
    return 0


_MATH_SEP = ' \t\\'


def _prev_char(s, i):
    """i 之前第一个有意义的字符（跳过空格和 LaTeX 转义用的反斜杠）。"""
    for k in range(i - 1, -1, -1):
        if s[k] not in _MATH_SEP:
            return s[k]
    return None


def _unit_run(s, i, prev):
    """
    判断 s[i:] 开头是否是一串带单位的量（单位符号、\\cdot 连接、可带上下标）。

    prev —— 前一个有意义字符，用于区分变量与单位：
            前面是数字 / 右括号时，单字母按单位处理
            （如 0.0023 K、mol^{-1}、(g·K)^{-1}）。
    """
    if not _unit_token(s, i):
        return 0
    if not (prev and (prev.isdigit() or prev in ')}]')):
        return 0
    j = i
    n = len(s)
    pieces = 0
    while j < n:
        start = j
        if s.startswith(_STATE, j):
            for st in _STATE:
                if s.startswith(st, j):
                    j += len(st)
                    break
            m = _UNIT_TAIL.match(s, j)
            j = m.end()
            pieces += 1
            continue
        # 括号包起来的复合单位，如 (g\cdot K)^{-1}
        if s[j] == '(':
            k = s.find(')', j)
            if k > j:
                j = k + 1
                m = _UNIT_TAIL.match(s, j)
                j = m.end()
                pieces += 1
                continue
        ln = _unit_token(s, j)
        if ln:
            j += ln
            m = _UNIT_TAIL.match(s, j)
            j = m.end()
            pieces += 1
            continue
        if s.startswith('\\cdot', j) or s.startswith('\\times', j) or s[j] == '·':
            j += 1 if s[j] == '·' else (5 if s.startswith('\\cdot', j) else 6)
            continue
        if s[j] in ' \t':
            j += 1
            continue
        if s.startswith('\\,', j) or s.startswith('\\ ', j):
            j += 2
            continue
        if s[j] == '\\':
            break
        if j == start:
            break
    if pieces == 0:
        return 0
    # 结尾去掉尾随空格
    while j > i and s[j - 1] in ' \t':
        j -= 1
    return j - i


def _upright_units(s):
    """把字符串里的单位片段标出来，返回 [(片段, 是否单位)]。"""
    out = []
    buf = []
    i = 0
    n = len(s)
    while i < n:
        prev = _prev_char(s, i)
        ln = _unit_run(s, i, prev)
        if ln > 0:
            if buf:
                out.append((''.join(buf), False))
                buf = []
            out.append((s[i:i + ln], True))
            i += ln
            continue
        buf.append(s[i])
        i += 1
    if buf:
        out.append((''.join(buf), False))
    return out


def _s_sup(base, sup):
    return ('<m:sSup><m:sSupPr><m:ctrlPr><w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/>'
            '<w:i/></w:rPr></m:ctrlPr></m:sSupPr>'
            '<m:e>%s</m:e><m:sup>%s</m:sup></m:sSup>' % (base, sup))


def _s_subsup(base, sub, sup):
    return ('<m:sSubSup><m:sSubSupPr><m:ctrlPr><w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/>'
            '<w:i/></w:rPr></m:ctrlPr></m:sSubSupPr>'
            '<m:e>%s</m:e><m:sub>%s</m:sub><m:sup>%s</m:sup></m:sSubSup>' % (base, sub, sup))


def _delim(inner, beg='(', end=')'):
    return ('<m:d><m:dPr><m:begChr m:val="%s"/><m:endChr m:val="%s"/>'
            '<m:ctrlPr><w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/><w:i/></w:rPr></m:ctrlPr>'
            '</m:dPr><m:e>%s</m:e></m:d>' % (escape(beg), escape(end), inner))


class _Parser:
    def __init__(self, src):
        self.s = src
        self.i = 0

    def eof(self):
        return self.i >= len(self.s)

    def peek(self, n=1):
        return self.s[self.i:self.i + n]

    # -------------------------------------------------- 分组
    def parse_group(self, stop=None):
        """返回 _Node 列表；保证每轮循环都向前推进。"""
        parts = []
        while not self.eof() and not self.at_stop(stop):
            before = self.i
            parts.append(self.parse_unit())
            if self.i == before:
                self.i += 1          # 保险：绝不允许零推进
        return parts

    def at_stop(self, stop):
        if self.eof():
            return True
        c = self.s[self.i]
        if c == '}':
            return True
        return bool(stop) and c in stop

    def read_braced(self):
        """读取 { ... } 或单个 token，返回 _Node 列表。"""
        if self.peek() == '{':
            self.i += 1
            parts = self.parse_group(stop='}')
            if self.peek() == '}':
                self.i += 1
            return parts
        return [self.parse_unit()]

    def read_braced_xml(self):
        """读取 { ... } 或单个 token，返回 XML 字符串（含整体上下标）。"""
        return self.attach_scripts(
            _Node(''.join(p.xml for p in self.read_braced()), is_atom=True)).xml

    def attach_scripts(self, node):
        """反复吸收紧随其后的 ^ / _ 标记。"""
        while not self.eof() and self.peek() in ('^', '_'):
            mark = self.s[self.i]
            self.i += 1
            start = self.i
            operand = _Node(''.join(p.xml for p in self.read_braced()), is_atom=True)
            if mark == '^':
                node = _Node(_s_sup(node.xml, operand.xml), is_atom=True)
            else:
                raw = self.s[start:self.i]
                if raw.startswith('{') and raw.endswith('}'):
                    raw = raw[1:-1]
                sub_xml = _simple_sub_xml(raw)
                if sub_xml is None:
                    sub_xml = operand.xml
                    if _sub_is_upright(sub_xml):
                        sub_xml = _upright_xml(sub_xml)
                node = _Node(_s_sub(node.xml, sub_xml), is_atom=True)
        return node

    # -------------------------------------------------- 单元
    def parse_unit(self):
        """解析一个原子，并把紧随其后的上下标吸收进来。"""
        c = self.s[self.i]
        if c in ' \t':
            # LaTeX 数学模式下裸露的空格一律忽略（要空格得写 '\ '）。
            # 之前把它保留成窄空格，结果 '\Delta Q' 会排成 "Δ Q"、
            # '\Delta\Delta T' 排成 "ΔΔ T"、'g\cdot mol' 排成 "g ⋅ mol"。
            while self.i < len(self.s) and self.s[self.i] in ' \t':
                self.i += 1
            return _Node('', is_atom=True)
        if c == '{':
            return self.attach_scripts(
                _Node(self.read_braced_xml(), is_atom=True))
        if c == '\\':
            return self.attach_scripts(self.parse_command())
        if c == '^' or c == '_':
            # 无基底的上下标（罕见），按空基底处理
            self.i += 1
            return _Node('', is_atom=True)
        # 化学式（KNO_{3}、H_{2}O…）整段正体；必须放在"普通字符"之前，
        # 否则 \frac{m}{M(KNO_{3})} 这种括号里的化学式会被当成变量排成斜体。
        if c.isascii() and c.isupper():
            end = _is_chem_span(self.s, self.i)
            if end and end > self.i:
                seg = self.s[self.i:end]
                self.i = end
                xml = ''.join(
                    _s_sub(_mrun(t, 'p'), _mrun(sb, 'p')) if sb else _mrun(t, 'p')
                    for t, sb in _chem_parts(seg))
                return self.attach_scripts(_Node(xml, is_atom=True))
        # 普通字符
        self.i += 1
        return self.attach_scripts(
            _Node(_mrun(c, _math_sty(c)), is_atom=True, is_op=c in RELATION_OPS))

    def parse_command(self):
        rest = self.s[self.i:]
        # 空格类命令要优先处理：'\\ '（反斜杠+空格）是 LaTeX 的显式空格，
        # 而 '\\\\' 在单行公式里当作宽间隔；两者都不能走符号表。
        nxt = rest[1:2]
        if nxt in (' ', '\t'):
            self.i += 2
            while not self.eof() and self.s[self.i] in ' \t':
                self.i += 1
            return _Node(_mrun('\u2009', 'p'), is_atom=True)
        if nxt == '\\':
            self.i += 2
            return _Node(_mrun('\u2003\u2003', 'p'), is_atom=True)

        # 先匹配最长命令名
        name = None
        for tbl in (GREEK, SYMBOLS):
            for k in tbl:
                if rest.startswith(k) and (name is None or len(k) > len(name)):
                    name = k
        for k in ('\\frac', '\\dfrac', '\\sqrt', '\\text', '\\mathrm', '\\operatorname',
                  '\\left', '\\right'):
            if rest.startswith(k) and (name is None or len(k) > len(name)):
                name = k
        if name is None:
            self.i += 1
            return _Node(_mrun(rest[0], 'p'), is_atom=True)
        self.i += len(name)

        if name in (r'\frac', r'\dfrac'):
            num = self.read_braced_xml()
            den = self.read_braced_xml()
            return _Node(_frac(num, den), is_atom=True)
        if name == r'\sqrt':
            return _Node(_rad(self.read_braced_xml()), is_atom=True)
        if name in (r'\text', r'\mathrm', r'\operatorname'):
            txt = self.s[self.i:]
            if txt.startswith('{'):
                depth = 0
                j = 0
                for j, ch in enumerate(txt):
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            break
                content = txt[1:j]
                self.i += j + 1
            else:
                content = txt[:1]
                self.i += 1
            return _Node(_mrun(content, 'p'), is_atom=True)
        if name == r'\left':
            beg = self.s[self.i]
            self.i += 1
            # 读到对应的 \right
            depth = 0
            j = self.i
            inner_parts = []
            while j < len(self.s):
                if self.s.startswith(r'\right', j):
                    if depth == 0:
                        break
                    depth -= 1
                if self.s.startswith(r'\left', j):
                    depth += 1
                j += 1
            seg = self.s[self.i:j]
            self.i = j + len(r'\right')
            end = self.s[self.i] if not self.eof() else ')'
            self.i += 1
            inner = to_omml_body(seg)
            if beg in ('.',):
                return _Node(_delim(inner, '', end), is_atom=True)
            if end in ('.',):
                return _Node(_delim(inner, beg, ''), is_atom=True)
            return _Node(_delim(inner, beg, end), is_atom=True)
        if name == r'\right':
            return _Node('', is_atom=True)
        if name in GREEK:
            return _Node(_mrun(GREEK[name], 'i' if name[1:].islower() else 'p'),
                         is_atom=True, is_op=False)
        if name in SYMBOLS:
            val = SYMBOLS[name]
            return _Node(_mrun(val, 'p') if val else '', is_atom=True,
                         is_op=val in RELATION_OPS)
        if name in UPRIGHT_FUNCS:
            return _Node(_mrun(name[1:], 'p'), is_atom=True)
        return _Node(_mrun(name[1:], 'p'), is_atom=True)


def to_omml(latex, display=False):
    """返回完整的 <m:oMath>（行内）或 <m:oMathPara>（独立公式行）XML。"""
    body = to_omml_body(latex)
    omath = '<m:oMath>%s</m:oMath>' % body
    if display:
        return ('<m:oMathPara><m:oMathParaPr><m:jc m:val="center"/></m:oMathParaPr>'
                '<m:oMath>%s</m:oMath></m:oMathPara>' % body)
    return omath
