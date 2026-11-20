# -*- coding: utf-8 -*-
"""OMML 转换的回归测试：只覆盖报告里实际用到的 LaTeX 子集。"""
from __future__ import annotations

import unittest

from support import (M, find_one, load_module, omml_runs, omml_text,
                     parse_omml)

# 电导率那份 omml 是当前最完整的一版（\\lg、花括号单位、⊖、S 单位都已修）；
# 重复索引 i/j 的斜体规则只在双液系那份里，单独用双液系做对照。
GENERAL_TOOL = '电导率工具'
INDEX_TOOL = '双液系工具'


def _upright(runs, text):
    hits = [up for t, up in runs if t == text]
    if not hits:
        raise AssertionError('没有找到文本 %r，实际 %r' % (text, runs))
    return all(hits)


class OmmlCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.omml = load_module(GENERAL_TOOL, 'omml')

    def body(self, latex):
        return self.omml.to_omml_body(latex)

    def test_function_commands_are_upright(self):
        for latex, name in [(r'\lg x', 'lg'), (r'\ln K', 'ln'),
                            (r'\log c', 'log')]:
            xml = self.body(latex)
            runs = omml_runs(xml)
            self.assertTrue(_upright(runs, name), (latex, runs))
            self.assertNotIn('\\', omml_text(xml), latex)

    def test_frac_keeps_balanced_denominator(self):
        xml = self.body(r'\frac{n^{2}h}{8mL^{2}}')
        frac = find_one(xml, 'f')
        nums = frac.findall(M + 'num')
        dens = frac.findall(M + 'den')
        self.assertEqual(len(nums), 1)
        self.assertEqual(len(dens), 1)
        self.assertEqual(omml_text(xml_of(nums[0])), 'n2h')
        # 旧 bug 会在 8m 处把分母切开，分母只剩 8m，L 掉到分数线外
        self.assertEqual(omml_text(xml_of(dens[0])), '8mL2')

    def test_chem_formula_inside_denominator(self):
        xml = self.body(r'\frac{m}{M(KNO_{3})}')
        den = find_one(xml, 'den')
        self.assertEqual(omml_text(xml_of(den)), 'M(KNO3)')
        self.assertTrue(_upright(omml_runs(xml_of(den)), 'K'))

    def test_standard_state_symbols(self):
        for latex, symbol in [(r'K^{\ominus}', '⊖'), (r'a^{\oplus}', '⊕'),
                              (r'\theta^{\circ}', '∘')]:
            xml = self.body(latex)
            text = omml_text(xml)
            self.assertIn(symbol, text, (latex, text))
            self.assertNotIn('\\', text, (latex, text))

    def test_units_are_upright(self):
        xml = self.body(r'0.01214\ S\cdot m^{2}\cdot mol^{-1}')
        runs = omml_runs(xml)
        for symbol in ('S', 'm', 'mol', '2', '-1'):
            self.assertTrue(_upright(runs, symbol), (symbol, runs))

    def test_single_letter_unit_after_number(self):
        runs = omml_runs(self.body(r'298.15\ K'))
        self.assertTrue(_upright(runs, 'K'), runs)

    def test_chemical_formula_is_upright(self):
        runs = omml_runs(self.body(r'H_{2}O'))
        for text in ('H', '2', 'O'):
            self.assertTrue(_upright(runs, text), (text, runs))

    def test_mathrm_and_variable_case(self):
        runs = omml_runs(self.body(r'\mathrm{d}T'))
        self.assertTrue(_upright(runs, 'd'), runs)      # 微分号 d 正体
        self.assertFalse(_upright(runs, 'T'), runs)     # 变量 T 斜体

    def test_uppercase_greek_is_upright(self):
        runs = omml_runs(self.body(r'\Delta T'))
        self.assertTrue(_upright(runs, 'Δ'), runs)
        self.assertFalse(_upright(runs, 'T'), runs)

    def test_uppercase_greek_quantity_is_italic(self):
        """Λ（摩尔电导率）是**量符号**，必须斜体，不能因为是大写希腊字母就正体。

        ⚠ 2026-11-20 用户反馈「正斜体和上下标有严重问题」时查出的真 bug：
        omml.py 原判据是「希腊字母命令名首字母大写 → 正体」，于是
        `\\Lambda_{m}` 里的 Λ 被排成正体。依据：

          · 课程参照报告（2300012602-李晨曦-电导率.docx）：Λ 斜体 92 次、
            无一处正体
          · 讲义：Λ 斜体 7 次（另有 56 次正体，是老师手工漏改，不作依据）

        「大写希腊字母正体」这条只对**算子**成立（∂ 偏导、∑ 求和、
        ∏ 连乘、Δ 差分），不对量符号成立。
        """
        for latex in (r'\Lambda_{m}', r'\Lambda_{m}^{\infty}',
                      r'\sigma_{\Lambda_{m}^{\infty}}'):
            runs = omml_runs(self.body(latex))
            self.assertFalse(_upright(runs, 'Λ'),
                             '「%s」里的 Λ 被排成正体了：%r' % (latex, runs))

    def test_operators_are_upright(self):
        """算子必须正体：∂ 偏导、∑ 求和、∏ 连乘。

        用户 2026-11-20 明确「偏微分号应该是正体」，与讲义里 ∂ 正体
        40 次一致。（参照报告把 ∂ 排成斜体 8 次，属学生报告的疏漏，
        以用户要求 + 讲义为准。）
        """
        runs = omml_runs(self.body(
            r'\frac{\partial K^{\ominus}}{\partial \Lambda_{m}^{\infty}}'))
        self.assertTrue(_upright(runs, '∂'), runs)
        # 同一式子里 Λ 仍必须是斜体——两者不能一起被规则带走
        self.assertFalse(_upright(runs, 'Λ'), runs)

        for latex, sym in ((r'\sum_{i=1}^{n}', '∑'),
                           (r'\prod_{i}', '∏')):
            runs = omml_runs(self.body(latex))
            self.assertTrue(_upright(runs, sym), (latex, runs))

    def test_mean_value_m_is_not_upright(self):
        """式中的平均值 m̄ 是量符号，不能用 \\mathrm{} 强成正体。

        ⚠ 原来 report.py 写的是 `\\mathrm{m}^{\\ominus}`，与同一段正文
        「带下标 m 的量表示各瓶 K⊖ 的平均值」自相矛盾。

        ⚠ 判据要按**字符**而不是按 run：Unicode 组合符（上划线 U+0304）
        会和基字符分成两个 m:r，`_upright(runs, 'm̄')` 找不到它。
        """
        runs = omml_runs(self.body(r'\left(K_{i}^{\ominus}-m̄^{\ominus}\right)'))
        # m 与它上面的组合符都必须是斜体
        for text in ('m', '\u0304'):
            self.assertFalse(_upright(runs, text),
                             '%r 被排成正体：%r' % (text, runs))

    def test_left_right_delimiter(self):
        xml = self.body(r'\left( \frac{a}{b} \right)')
        delim = find_one(xml, 'd')
        beg = delim.find(M + 'dPr/' + M + 'begChr')
        end = delim.find(M + 'dPr/' + M + 'endChr')
        self.assertEqual(beg.get(M + 'val'), '(')
        self.assertEqual(end.get(M + 'val'), ')')

    def test_text_command_is_upright(self):
        runs = omml_runs(self.body(r'\text{mol}'))
        self.assertTrue(_upright(runs, 'mol'), runs)

    def test_escaped_percent(self):
        self.assertEqual(omml_text(self.body(r'50\%')), '50%')

    def test_display_math_wrapper(self):
        xml = self.omml.to_omml('x', display=True)
        self.assertIn('<m:oMathPara', xml)
        self.assertIn('<m:jc m:val="center"/>', xml)
        self.assertIn('<m:oMath>', xml)

    def test_no_empty_denominator(self):
        for latex in (r'\frac{a}{b}', r'\frac{m}{M(KNO_{3})}',
                      r'\frac{n^{2}h}{8mL^{2}}'):
            den = find_one(self.body(latex), 'den')
            self.assertTrue(omml_text(xml_of(den)).strip(), latex)


class OmmlRepeatedIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.omml = load_module(INDEX_TOOL, 'omml')

    def _subscript_runs(self, latex):
        xml = self.omml.to_omml_body(latex)
        sub = find_one(xml, 'sub')
        return omml_runs(xml_of(sub))

    def test_double_i_is_italic(self):
        runs = self._subscript_runs(r'h_{ii}')
        self.assertEqual(runs, [('ii', False)])

    def test_ij_is_italic(self):
        runs = self._subscript_runs(r'\varepsilon_{ij}')
        self.assertEqual(runs, [('ij', False)])

    def test_descriptive_subscript_is_upright(self):
        runs = self._subscript_runs(r'm_{sam}')
        self.assertEqual(runs, [('sam', True)])


def xml_of(element):
    from xml.etree.ElementTree import tostring
    return tostring(element, encoding='unicode')


if __name__ == '__main__':
    unittest.main()
