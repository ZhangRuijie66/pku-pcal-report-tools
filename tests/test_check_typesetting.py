# -*- coding: utf-8 -*-
"""``check_typesetting.py`` 自身的守卫：它必须真的能抓到三类问题。

## 为什么这个测试必须存在

2026-11-03 那次审计的教训：57/208 个断言只是 grep 源码字符串，从来没验证
「注入 bug 后测试会不会红」。检查器尤其危险——它平时输出「0 处」看起来
一切都好，但如果判据写错，**永远报 0 处也不会有人发现**。

所以这里为每一类问题**现场造一个最小的 docx**（含该种错误），
断言检查器能报出来；再造一个**正确排版**的 docx，断言它报 0。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile

from support import REPO_ROOT

TESTS_DIR = REPO_ROOT / 'tests'
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import check_typesetting as ct                # noqa: E402

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def _run(text, italic=False, script=''):
    """造一个 w:r。script ∈ {'', 'sub', 'sup'}。"""
    rpr = ''
    if italic or script:
        rpr = '<w:rPr>'
        if italic:
            rpr += '<w:i/>'
        if script == 'sub':
            rpr += '<w:vertAlign w:val="subscript"/>'
        elif script == 'sup':
            rpr += '<w:vertAlign w:val="superscript"/>'
        rpr += '</w:rPr>'
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, text)


def _make_docx(runs_xml, path):
    """把若干 w:r 拼成一个段落，写进最小可用 docx。"""
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="%s">'
        '<w:body><w:p>%s</w:p></w:body></w:document>' % (W_NS, runs_xml))
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'wordprocessingml.document.main+xml"/></Types>')
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships"><Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', rels)
        z.writestr('word/document.xml', document)
    return path


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def build(self, runs_xml, name='t.docx'):
        return _make_docx(runs_xml, os.path.join(self.tmp, name))


# ============================================================ 正斜体
class ItalicDetectionTests(_Base):
    """检查器必须能报「漏斜体」和「误斜体」，且不误报正确排版。"""

    def test_correct_typesetting_reports_nothing(self):
        """正确排版：变量斜体、单位正体、化学式正体 → 0 处。"""
        xml = (_run('测得 ')
               + _run('c', italic=True)
               + _run(' = 0.5 mol·dm')
               + _run('−3', script='sup')
               + _run('，化学式为 C')
               + _run('12', script='sub')
               + _run('H')
               + _run('22', script='sub')
               + _run('O')
               + _run('11', script='sub')
               + _run('。'))
        p = self.build(xml)
        mi, wi = ct.check_italic(p)
        self.assertEqual(mi, [], '正确排版被报成漏斜体：%r' % (mi,))
        self.assertEqual(wi, [], '正确排版被报成误斜体：%r' % (wi,))

    def test_missing_greek_quantity_is_caught(self):
        """希腊量符号（Λ 摩尔电导率）写成正体 → 必须报出来。

        ⚠ 拉丁单字母**不再做**「该斜体却正体」判断（2026-11-26 改）：
        实测会报出 41 处噪音——`0.0103 g` 的 g、`0.71 s` 的 s 是单位，
        `电极B` 是器件代号（规范正体），`Qp` 是 Q+下标p 被切开。
        可靠地区分「变量 vs 单位 vs 代号」需要覆盖所有学科的词表，做不到
        就不做，只保留希腊字母这一条（希腊字母几乎不可能是单位，除 μ 词头
        与 Ω 电阻单位，均已单独豁免）。
        """
        xml = _run('因为 ') + _run('Λ') + _run('m') + _run(' 是外推量')
        p = self.build(xml)
        mi, _wi = ct.check_italic(p)
        kinds = [m[0] for m in mi]
        self.assertIn('greek-upright', kinds,
                      '希腊量符号 Λ 排成正体却没报：%r' % (mi,))

    def test_inconsistent_italic_is_caught(self):
        """同一符号一处斜体、一处正体 → 必须报「不一致」。

        这是最确定的一类错（用户实际看到的就是这种），也是新判据的核心。
        """
        xml = (_run('测得 ') + _run('κ', italic=True) + _run(' 为 1.5，')
               + _run('校正后 ') + _run('κ') + _run(' 为 1.2'))
        p = self.build(xml)
        mi, _wi = ct.check_italic(p)
        kinds = [m[0] for m in mi]
        self.assertIn('inconsistent-greek', kinds,
                      'κ 前后不一致却没报：%r' % (mi,))

    def test_si_prefix_unit_is_exempt(self):
        """`μA`（微安）里的 μ 是 SI 词头，必须正体，不能报。"""
        xml = _run('基线偏差 1 ') + _run('μ') + _run('A 时')
        p = self.build(xml)
        mi, _wi = ct.check_italic(p)
        self.assertEqual(mi, [], 'μA 的 μ 被误报：%r' % (mi,))

    def test_wrong_italic_word_is_caught(self):
        """整词（非函数名）排成斜体 → 必须报出来。"""
        xml = _run('峰形为 ') + _run('Voigt', italic=True) + _run(' 线型')
        p = self.build(xml)
        _mi, wi = ct.check_italic(p)
        self.assertTrue(wi, 'Voigt 排成斜体却没报')
        self.assertEqual(wi[0][0], 'word')

    def test_math_function_italic_is_allowed(self):
        """ln / lg 这类函数名排斜体是规范的例外，不该报。"""
        xml = _run('取对数 ') + _run('ln', italic=True) + _run(' p')
        p = self.build(xml)
        _mi, wi = ct.check_italic(p)
        kinds = [w[0] for w in wi]
        self.assertNotIn('word', kinds, 'ln 是数学函数，斜体应豁免')

    def test_chem_formula_single_letter_is_exempt(self):
        """O2 的 O 被切成单独 run 时属于化学式，不能报漏斜体。"""
        xml = _run('O') + _run('2', script='sub') + _run(' 饱和下测得')
        p = self.build(xml)
        mi, _wi = ct.check_italic(p)
        self.assertEqual(mi, [], '化学式的元素符号被误报成漏斜体：%r' % (mi,))

    def test_pka_half_symbol_is_exempt(self):
        """pK_a 的 p（正体）与 K（斜体）是同一符号，不能报。"""
        xml = (_run('理论 p') + _run('K', italic=True)
               + _run('a', italic=True, script='sub') + _run(' = 4.756'))
        p = self.build(xml)
        mi, wi = ct.check_italic(p)
        self.assertEqual(mi, [], 'pK_a 的 p 被误报：%r' % (mi,))
        self.assertEqual(wi, [], 'pK_a 的 K 被误报：%r' % (wi,))


# ============================================================ 上下标
class ScriptDetectionTests(_Base):
    """四类上下标问题都必须报出来。"""

    def test_unicode_subscript_is_caught(self):
        """Unicode 下标字符（Sₓₓ）→ 必须报。"""
        xml = _run('其中 Sₓₓ = 5.792×10') + _run('−3', script='sup')
        p = self.build(xml)
        probs = ct.check_scripts(p)
        kinds = [x[0] for x in probs]
        self.assertIn('unicode-script', kinds,
                      'Unicode 下标没报出来：%r' % (probs,))

    def test_raw_marker_is_caught(self):
        """未解析的 _{ / ^{ 标记 → 必须报。"""
        xml = _run('比热容 m_{Ni-1} 的值')
        p = self.build(xml)
        probs = ct.check_scripts(p)
        kinds = [x[0] for x in probs]
        self.assertIn('raw-marker', kinds, '未解析标记没报：%r' % (probs,))

    def test_bare_underscore_is_caught(self):
        """裸下划线（μ_B 当普通字符串）→ 必须报。"""
        xml = _run('磁矩 μ_B 的计算')
        p = self.build(xml)
        probs = ct.check_scripts(p)
        kinds = [x[0] for x in probs]
        self.assertIn('bare-underscore', kinds, '裸下划线没报：%r' % (probs,))

    def test_proper_scripts_report_nothing(self):
        """真上下标 → 0 处。"""
        xml = (_run('m') + _run('Ni-1', script='sub')
               + _run(' 与 10') + _run('−3', script='sup'))
        p = self.build(xml)
        probs = ct.check_scripts(p)
        self.assertEqual(probs, [], '正确上下标被误报：%r' % (probs,))


# ============================================================ 空格
class SpaceDetectionTests(_Base):
    """只报「汉字 空格 汉字」，不报规范要求的空格。"""

    def test_han_space_han_is_caught(self):
        """两个汉字之间的空格 → 必须报（这就是用户说的那类）。"""
        xml = _run('本实验测得 蔗糖的燃烧热')
        p = self.build(xml)
        probs = ct.check_spaces(p)
        self.assertTrue(probs, '汉字之间的多余空格没报')
        self.assertEqual(probs[0][0], '汉字 空格 汉字')

    def test_digit_and_latin_spaces_are_allowed(self):
        """数字/西文与汉字之间的空格是规范要求的，不能报。"""
        xml = _run('第 3 组测得 25 ℃ 下的 KCl 溶液')
        p = self.build(xml)
        probs = ct.check_spaces(p)
        self.assertEqual(probs, [],
                         '规范要求的空格被误报：%r' % (probs,))

    def test_cover_field_alignment_is_exempt(self):
        """封面「姓    名：」用空格对齐是模板手法，不能报。"""
        xml = _run('姓    名：')
        p = self.build(xml)
        probs = ct.check_spaces(p)
        self.assertEqual(probs, [], '封面字段对齐被误报：%r' % (probs,))

    def test_abstract_label_space_is_exempt(self):
        """「摘要 」标签后的那一格是模板写法，不能报。"""
        xml = _run('摘要 本实验用最大气泡压力法')
        p = self.build(xml)
        probs = ct.check_spaces(p)
        self.assertEqual(probs, [], '摘要标签后的空格被误报：%r' % (probs,))


if __name__ == '__main__':
    unittest.main()