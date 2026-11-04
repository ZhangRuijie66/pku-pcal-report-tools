# -*- coding: utf-8 -*-
"""检查 docx 里字母的正/斜体是否符合物理化学实验报告规范。

规则（GB 3102 / 课程模板，用户 2026-10-21 定为强制项）：
  * 物理量符号、变量、小写希腊字母 → 斜体：A, c, b, L(箱长), λ, ε, σ, R², I₀ …
  * 单位、函数名、化学式、人名、编号、下标说明文字 → 正体：
      nm, cm, L(升), mol, lg, Voigt, DTDC, C₂₃H₂₃IN₂S₂, A3/B2(分子编号), max(下标)
  * 公式里单位/函数用 \\mathrm{} 或 OMML 的 m:sty="p"

用法：python check_italic.py 报告.docx
"""
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
}

GREEK = 'αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ'
MATH_FUNCS = {'lg', 'ln', 'exp', 'sin', 'cos', 'tan', 'log', 'max', 'min'}
UPRIGHT_OK = {'Voigt', 'DTDC', 'DTDCI', 'DiSC', 'CAS', 'Alfa', 'Aesar', 'ChemicalBook',
              'Thermo', 'Fisher', 'nm', 'cm', 'mm', 'kPa', 'Pa', 'mol', 'mmol', 'μmol',
              'min', 'max', 'ln', 'lg', 'exp', 'cm−1', 'mol−1'}

# 明知的误报（斜体其实是正确排版），按整词豁免：
#   ix —— 一维势箱里 i·x 相乘，是「变量 × 变量」，斜体正确。
KNOWN_FALSE_POSITIVES = {'ix'}


def _run_iter(p):
    """依次产出 (text, italic, is_math)。"""
    for r in p.findall('.//w:r', NS):
        t = ''.join(x.text or '' for x in r.findall('w:t', NS))
        if not t.strip():
            continue
        rpr = r.find('w:rPr', NS)
        it = False
        if rpr is not None:
            i = rpr.find('w:i', NS)
            it = i is not None and i.get('{%s}val' % NS['w']) not in ('0', 'false')
        yield t, it, False
    for mr in p.iter('{%s}r' % NS['m']):
        t = ''.join(x.text or '' for x in mr.findall('m:t', NS))
        if not t.strip():
            continue
        sty = mr.find('.//m:sty', NS)
        plain = sty is not None and sty.get('{%s}val' % NS['m']) in ('p', 'b')
        yield t, not plain, True


def check(path):
    z = zipfile.ZipFile(path)
    doc = ET.fromstring(z.read('word/document.xml'))
    body = doc.find('.//w:body', NS)
    problems = []
    for p in body.iter('{%s}p' % NS['w']):
        ptxt = ''.join(t.text or '' for t in p.findall('.//w:t', NS))
        for text, italic, math in _run_iter(p):
            s = text.strip()
            if not italic or s in KNOWN_FALSE_POSITIVES:
                continue
            # 1) 整词斜体（Voigt、mol、nm…）：只允许数学函数名。
            #    重复索引 i/j（h_{ii}、ε_{ij}）是变量下标，斜体是正确排版，豁免。
            if re.fullmatch(r'[A-Za-z]{2,}', s) and s not in MATH_FUNCS \
                    and not re.fullmatch(r'[ij]+', s):
                if s in UPRIGHT_OK or s not in MATH_FUNCS:
                    problems.append(('整词应正体', s, ptxt[:60]))
                continue
            # 2) 编号斜体：A3、B2、DTDCI2 …
            if re.fullmatch(r'[A-Za-z]\d+', s):
                problems.append(('编号应正体', s, ptxt[:60]))
                continue
            # 3) 拉丁字母 + 数字混排（A3c5 之类），且不含希腊字母 → 可疑
            if re.fullmatch(r'[A-Za-z\d\.]+', s) and re.search(r'\d', s) and re.search(r'[A-Za-z]', s):
                problems.append(('含数字的符号应正体', s, ptxt[:60]))
    return problems


if __name__ == '__main__':
    probs = check(sys.argv[1])
    for kind, txt, ctx in probs:
        print('%-20s %-12r %s' % (kind, txt, ctx))
    print('---- 共 %d 处' % len(probs))
