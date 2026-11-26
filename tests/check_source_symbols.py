# -*- coding: utf-8 -*-
"""静态检查：`pcal/report.py` 里**纯字符串参数**中的量符号。

## 为什么要在源码层查，而不是只查 docx

2026-11-26 那次体检，11 份报告查出 57 处正斜体错误，**根因只有一条**：

```python
rb.para('因为 Λm∞ 是外推得到的量')                    # ✗ 整串正体
rb.para(['因为 ', ('t', 'Λ_{m}^{∞}', ITALIC), ' 是…'])  # ✓ 拆片段
```

`docxkit._emit_text()` 只对**斜体片段内部**再细分「拉丁字母/小写希腊字母
斜体、Δ/Σ/数字正体」；传给 `para()`/`heading()`/`caption()` 的**纯字符串
一律按正体排**。所以只要希腊字母或量符号写进了纯字符串，就一定是错的。

查 docx 能发现这些错，但要先跑完整报告生成（几十秒/份），而且
**同一个错误写法在 11 个模块里反复出现**。静态检查 0.1 秒就能定位到行号。

## 判据（只报高置信的）

1. 出现在 `rb.para(...)` / `rb.heading(...)` / `rb.caption(...)` /
   `rb.table(...)` 的**字符串字面量**里（片段列表里的 `('t', …)` 除外）；
2. 该字面量里含**小写希腊字母**（αβγ…ω），或**量符号大写希腊字母**
   （Λ Ω Φ），且不在下列豁免里：
   - 单位串：`S·m⁻¹`、`mol·dm⁻³`、`μS·cm⁻¹`
   - SI 词头单位：`μA`、`μmol`、`μm`
   - 电阻单位 Ω（前面是数字）
   - 化学式里的字母（不涉及希腊字母，无需处理）
3. 拉丁单字母**不查**（单位 g/s/J、器件代号 B、`Qp` 拆分等噪音太大，
   实测燃烧热会报 41 处假阳性）。

用法：
    python tests/check_source_symbols.py            # 查全部 11 个工具
    python tests/check_source_symbols.py 电导率工具   # 只查一个
"""
from __future__ import annotations

import ast
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GREEK_LOWER = 'αβγδεζηθικλμνξοπρστυφχψω'
#: 作量符号时才该斜体的大写希腊字母（Δ Σ ∂ 是算子，正体正确，不在表里）
GREEK_QUANT = 'ΛΩΦΓΘΞ'

#: 这些调用会把字符串参数**原样**排成正体。
#:
#: ⚠ **不含 `equation`**：`rb.equation()` 的参数是 LaTeX，交给 `omml.py`
#: 转成 Word 原生公式，正斜体由 OMML 层自己判定（`_math_sty`：拉丁字母与
#: 小写希腊字母斜体、Δ/Σ/∂ 与数字正体）。把 equation 也算进来会报出
#: 偶极矩 25 处假阳性（`\frac{ε_{1}-1}{ε_{1}+2}` 这类完全正确）。
#: 公式层的正斜体由 `tests/audit_docx.py` 的 math.italic / math.upright 覆盖。
TARGET_CALLS = {'para', 'heading', 'caption', 'add_rich_text'}

#: 单位串：含 · 或后面紧跟单位字母的，整段豁免
_UNIT_RE = re.compile(
    r'(?:[μa-zA-Z]+)·(?:[a-zA-Zμ]+[⁻⁰¹²³⁴⁵⁶⁷⁸⁹−]*)+'
)
#: SI 词头 + 单位（μA / μmol / μm / μS）
_SI_PREFIX_RE = re.compile(r'μ(?:A|S|F|H|V|W|J|K|m|g|s|L|l|mol|M|N|Pa|Hz|C|T)')
#: 数字后面的 Ω 是电阻单位，正体正确
_OHM_UNIT_RE = re.compile(r'\d\s*Ω|%[sdf]\s*Ω|平均\s*%[sdf]\s*Ω')

#: 化合物名里的希腊字母前缀（β-胡萝卜素、α-萘酚、γ-丁内酯…）：
#: 这是 IUPAC 命名的一部分，**正体**正确，不能当量符号斜体。
_CHEM_GREEK_PREFIX_RE = re.compile(
    r'[αβγδεζηθικλμνξοπρστυφχψω]-[\u4e00-\u9fff]+')


def _strip_protected(text):
    """把豁免片段抹成等长空白，避免它们触发误报。"""
    out = text
    for pat in (_UNIT_RE, _SI_PREFIX_RE, _OHM_UNIT_RE, _CHEM_GREEK_PREFIX_RE):
        out = pat.sub(lambda m: ' ' * len(m.group(0)), out)
    return out


def _string_nodes(call):
    """取出这个调用里**会按正体排**的字符串字面量节点。

    两种情况都要报（2026-11-26 第二轮补的，第一轮漏了第二种）：

    a) 直接传字符串：``rb.para('...ε...')``
    b) **片段列表里的裸字符串**：``rb.para(['...ε...', ('t','ε',ITALIC)])``
       —— 只有 ``('t', 文本, {italic})`` 这种元组里的文本才由样式控制；
       列表里直接写的 str 仍然是「普通文本片段」，同样整段正体。
       紫外光谱 26 处漏检全部属于这一类：静态检查报 0 处，docx 却有 26 处。

    ``('t', 'ε', ITALIC)`` 这种元组里的字符串**不报**（斜体由 ITALIC 控制）。
    """
    out = []
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.append(arg)                       # a) 纯字符串参数
        elif isinstance(arg, ast.JoinedStr):
            out.append(arg)
        elif isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod):
            left = arg.left
            if isinstance(left, ast.Constant) and isinstance(left.value, str):
                out.append(left)
        elif isinstance(arg, (ast.List, ast.Tuple)):
            for elt in arg.elts:
                # b) 片段列表里的裸字符串
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    out.append(elt)
                elif isinstance(elt, ast.JoinedStr):
                    out.append(elt)
                elif isinstance(elt, ast.BinOp) and isinstance(elt.op, ast.Mod):
                    left = elt.left
                    if isinstance(left, ast.Constant) and isinstance(left.value, str):
                        out.append(left)
                # ('t', …) 元组整个跳过：斜体由第三个元素控制
    return out


def _join_str_parts(node):
    """把 `'a' 'b'` 这种隐式拼接的字符串常量合并成一个文本。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def scan_file(path):
    """返回 [(lineno, kind, char, text)]。"""
    with open(path, encoding='utf-8') as fh:
        src = fh.read()
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [(exc.lineno or 0, 'syntax-error', '', str(exc))]
    lines = src.splitlines()
    problems = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = None
        if isinstance(fn, ast.Attribute):
            name = fn.attr
        elif isinstance(fn, ast.Name):
            name = fn.id
        if name not in TARGET_CALLS:
            continue
        for snode in _string_nodes(node):
            text = snode.value if isinstance(snode, ast.Constant) else None
            if text is None:
                continue
            clean = _strip_protected(text)
            for ch in clean:
                if ch in GREEK_LOWER:
                    problems.append((snode.lineno, 'greek-lower', ch,
                                     text.strip()[:70]))
                    break
                if ch in GREEK_QUANT:
                    problems.append((snode.lineno, 'greek-quantity', ch,
                                     text.strip()[:70]))
                    break
    # 去重（同一行同一字符只报一次）
    seen = set()
    out = []
    for item in problems:
        key = (item[0], item[1], item[2])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return sorted(out)


def main(argv):
    tools = []
    if argv:
        tools = argv
    else:
        for name in sorted(os.listdir(REPO)):
            d = os.path.join(REPO, name, 'pcal')
            if os.path.isfile(os.path.join(d, 'report.py')):
                tools.append(name)
    total = 0
    for tool in tools:
        path = os.path.join(REPO, tool, 'pcal', 'report.py')
        if not os.path.isfile(path):
            print('跳过（无 report.py）：%s' % tool)
            continue
        probs = scan_file(path)
        total += len(probs)
        if not probs:
            continue
        print('=' * 70)
        print('%s：%d 处' % (tool, len(probs)))
        for lineno, kind, ch, text in probs:
            print('  L%-5d %-16s %-3r %s' % (lineno, kind, ch, text[:58]))
    print()
    print('合计 %d 处（纯字符串里的量符号，一律会印成正体）' % total)
    return 0 if total == 0 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))