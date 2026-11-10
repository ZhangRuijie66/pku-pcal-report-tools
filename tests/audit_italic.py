# -*- coding: utf-8 -*-
"""正斜体**双向**审计：既查「该正体却斜体」，也查「该斜体却正体」。

## 为什么需要它

`tests/check_italic.py` 只查一个方向（斜体用错），而且只认拉丁字母。
2026-11-10 用户报告「正斜体又有问题」时，check_italic 报「共 0 处」，
真实缺陷却有三类，它一类都覆盖不到：

| 缺陷 | 为什么 check_italic 看不到 |
| --- | --- |
| `α–t` 的 α 排成正体 | 只查「斜体用错」，不查「正体用错」 |
| 表 3「线性化关系」列整块正体 | 那一列是数据单元格，脚本只看 run 不看语义 |
| `c(H⁺)` 的 H 排成斜体 | 只认 `[A-Za-z]{2,}` 整词，单字母元素符号不判 |

## 判据（GB 3102 / ISO 80000）

* 量符号（拉丁单字母、小写希腊字母、ΛΞΠΣΥΦΨΩ）→ **斜体**
* 化学元素符号与化学物种（H、O、Na、H⁺、O₂）→ **正体**
* 单位、函数名（lg/ln/exp）、多人名与软件名 → **正体**
* 上下标里的数字与说明文字（suc、Ni、1M）→ **正体**；
  单字母变量下标（V、p、l）→ **斜体**

用法：python audit_italic.py <docx> [-v]
"""
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'

GREEK_LOWER = 'αβγδεζηθικλμνξοπρστυφχψω'
#: 作量符号的大写希腊字母（Δ 是算符，正体，不在此列）
GREEK_UPPER_QUANTITY = 'ΛΞΠΣΥΦΨΩ'

#: 化学元素（用于识别元素符号 / 离子）
ELEMENTS = frozenset('''H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc
Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag
Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta
W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es
Fm Md No Lr'''.split())

#: 单位（正体）。单字母单位只在明确是单位时才判——多数单字母既是单位也是变量，
#: 所以那些（m、s、K、C、N、A、V、W、J…）**只在紧跟数字或右括号时**才算单位，
#: 由上下文处理；这里放不会误伤的。
UNITS_MULTI = frozenset('''mol mmol μmol nmol kJ MJ cal kPa MPa hPa
mL μL kg mg μg cm mm nm dm km μm pm ms min Hz rpm'''.split())
UNITS_SINGLE = frozenset('Lgl')          # 升、克、升（小写 l）

#: 函数名（正体）
FUNCS = frozenset('''lg ln log exp sin cos tan sinh cosh tanh arcsin arccos
arctan max min det lim'''.split())

#: 明确该正体的多人名/软件名/编号前缀
UPRIGHT_WORDS = frozenset('''Voigt DTDC DTDCI DiSC CAS Alfa Aesar ChemicalBook
Polariputer WXG Origin Excel Word Matlab Python AR GR xlsx csv txt docx
included fit data'''.split())


def _is_italic(rpr):
    """是否斜体。

    ⚠ python-docx 给「显式不斜体」写的是 ``<w:i w:val="0"/>`` —— 元素**存在**
    但不斜。只判「元素是否存在」会把正体 run 全当斜体（2026-11-10 写这个
    脚本时就栽过一次，35 处"问题"里有一半是假的）。
    """
    if rpr is None:
        return False
    i = rpr.find(W + 'i')
    if i is None:
        return False
    return i.get(W + 'val') not in ('0', 'false', 'off')


def _runs(p):
    """产出 (text, italic, is_math, vert)。"""
    for r in p.findall('.//' + W + 'r'):
        txt = ''.join(x.text or '' for x in r.findall(W + 't'))
        if not txt:
            continue
        rpr = r.find(W + 'rPr')
        vert = None
        if rpr is not None:
            va = rpr.find(W + 'vertAlign')
            if va is not None:
                vert = va.get(W + 'val')
        yield txt, _is_italic(rpr), False, vert
    for mr in p.iter(M + 'r'):
        txt = ''.join(x.text or '' for x in mr.findall(M + 't'))
        if not txt:
            continue
        sty = mr.find('.//' + M + 'sty')
        plain = sty is not None and sty.get(M + 'val') in ('p', 'b')
        yield txt, not plain, True, None


def _para_text(p):
    return ''.join(t.text or '' for t in p.findall('.//' + W + 't'))


def _is_ion(s, next_text):
    """元素符号 + 电荷/下标：H⁺、Na⁺、O₂。"""
    m = re.fullmatch(r'([A-Z][a-z]?)', s)
    if not m or m.group(1) not in ELEMENTS:
        return False
    nxt = (next_text or '').strip()[:1]
    return nxt in ('+', '−', '-') or nxt.isdigit()


def classify(text, italic, vert, next_text, prev_text=''):
    """返回 (类型, 说明) 或 None。

    刻意保守：**只在语义明确时才报**。单字母既是单位又是变量（m、s、l、K），
    光看 run 判不出，误报比漏报更糟——用户会因为"报了一堆假的"而不再信它。
    所以：
      · 单位只认多字母（mol、kPa、nm…）和紧跟数字/括号时的单字母；
      · 单字母默认按量符号（斜体）处理；
      · 化学物种只认「元素符号 + 电荷/数字下标」这种铁证。
    """
    s = text.strip()
    if not s:
        return None
    core = s.strip('()（）[]【】,，.。;；:： ')
    if not core:
        return None

    # ---------- 上下标 ----------
    if vert is not None:
        if re.fullmatch(r'[A-Za-z]', core):
            # ⚠ 下标里的 m 几乎总是「摩尔」的意思（χ_m、M_m、Δ_vap H_m），
            # 而不是变量。只在**明确是元素符号**时才要求正体，其余一律
            # 按「变量下标 → 斜体」处理，避免把 χ_m 的 m 报成错。
            if core == 'm':
                return None
            if core in ELEMENTS and core in 'HCNOS':
                return ('下标元素符号应正体', '%r 作下标表示物种，应正体' % s) \
                    if italic else None
            if italic:
                return None                      # 变量下标，斜体正确
            return ('下标变量应斜体', '%r 是变量下标，应斜体' % s)
        if re.fullmatch(r'\d+[A-Za-z]{0,2}', core):
            return ('下标编号应正体', '%r 是编号下标，应正体' % s) if italic else None
        if re.fullmatch(r'[A-Za-z]{2,}', core):
            if italic and core.lower() not in FUNCS:
                return ('下标说明文字应正体', '%r 应正体' % s)
        return None

    # ---------- 希腊字母 ----------
    if core in GREEK_LOWER:
        return ('小写希腊字母应斜体', '%r 是变量，应斜体' % s) if not italic else None
    if core in GREEK_UPPER_QUANTITY:
        return ('大写希腊字母应正体', '%r 应正体' % s) if italic else None
    if core == 'Δ':
        return ('Δ 应正体', 'Δ 是算符') if italic else None

    # ---------- 多字母单词 ----------
    if re.fullmatch(r'[A-Za-z]{2,}', core):
        if italic and (core in UPRIGHT_WORDS or core.lower() in FUNCS
                       or core in UNITS_MULTI):
            return ('单词/单位/函数应正体', '%r 应正体' % s)
        return None

    # ---------- 单字母 ----------
    if re.fullmatch(r'[A-Za-z]', core):
        # 变量符号白名单优先判「该斜体」：这些字母在任何报告里都是量符号。
        # 先判它们，避免被下面的单位/元素规则抢走（m、l、s 都是既像单位
        # 又像变量的字母，只能靠上下文；这里按「报告里实际用法」定）。
        if core in 'VpPTrRkKcCnNxXyYzZ':
            return ('变量应斜体', '%r 是量符号，应斜体' % s) if not italic else None
        if core in UNITS_SINGLE:
            return ('单位应正体', '%r 是单位' % s) if italic else None
        # 元素符号 + 电荷/下标 → 化学物种，正体
        if _is_ion(core, next_text):
            return ('化学物种应正体', '%r 是元素符号/离子，应正体' % s) \
                if italic else None
        # 其余单字母按量符号处理（斜体）——这是报告里的主流用法
        return ('变量应斜体', '%r 是量符号，应斜体' % s) if not italic else None

    return None


def _plain_runs(p):
    """段落里的**普通文本** run（跳过 m:oMath 内部）。

    ⚠ 公式对象必须整块跳过：Word 公式里每个字符都是一个 ``m:r``，
    逐个 run 判正斜体会得到几百条假问题（实测紫外光谱报告报出 90+ 条，
    全是公式内部的单字符）。公式的正斜体由 omml.py 生成，
    另有 mathcheck 脚本负责；这里只管普通文本。

    ElementTree 没有 parent 指针，所以先收集公式内 w:r 的元素 id。
    """
    inside = set()
    for om in p.iter(M + 'oMath'):
        for r in om.iter(W + 'r'):
            inside.add(id(r))
    for r in p.iter(W + 'r'):
        if id(r) in inside:
            continue
        txt = ''.join(x.text or '' for x in r.findall(W + 't'))
        if not txt:
            continue
        rpr = r.find(W + 'rPr')
        vert = None
        if rpr is not None:
            va = rpr.find(W + 'vertAlign')
            if va is not None:
                vert = va.get(W + 'val')
        yield txt, _is_italic(rpr), vert


def audit(path):
    z = zipfile.ZipFile(path)
    doc = ET.fromstring(z.read('word/document.xml'))
    body = doc.find('.//' + W + 'body')
    problems = []
    for pi, p in enumerate(body.iter(W + 'p')):
        para = _para_text(p)
        runs = list(_plain_runs(p))
        for k, (text, italic, vert) in enumerate(runs):
            nxt = runs[k + 1][0] if k + 1 < len(runs) else ''
            prev = runs[k - 1][0] if k > 0 else ''
            res = classify(text, italic, vert, nxt, prev)
            if res:
                problems.append((pi, res[0], text.strip(), res[1], para[:70]))
    return problems


def main():
    path = sys.argv[1]
    verbose = '-v' in sys.argv
    problems = audit(path)
    print('=== 正斜体问题：%d 处 ===' % len(problems))
    by_kind = {}
    for pi, kind, s, why, ctx in problems:
        by_kind.setdefault(kind, []).append((pi, s, ctx))
    for kind, items in sorted(by_kind.items()):
        print('\n[%s] %d 处' % (kind, len(items)))
        for pi, s, ctx in items[:12]:
            print('   p%-3d %-14r %s' % (pi, s, ctx[:60] if verbose else ''))
        if len(items) > 12:
            print('   … 还有 %d 处' % (len(items) - 12))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
