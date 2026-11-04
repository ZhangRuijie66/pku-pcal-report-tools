# -*- coding: utf-8 -*-
"""把 check_italic 的规则接进回归测试：11 份报告的正斜体必须是 0 处问题。

SKILL §3.2.1 写明「每次生成或修改报告后必须运行 check_italic.py，输出共 0 处
才算完成」，但这条规则之前只靠人工执行——脚本放在仓库外的 _pcal_tools/，
run_tests.py 根本不跑它。现在把脚本收进 tests/ 并用测试守住。

顺带守住「函数名要正体」这条：`_split_runs_by_italic` 曾把 ln/lg 当变量
排成斜体（化学动力学报告里 12 处），那次也是人工核对才发现的。
"""
from __future__ import annotations

import tempfile
import unittest

import check_italic
from module_cases import build_cases, generate_report
from support import load_module


class ItalicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases, cls.build_errors = build_cases()

    def test_all_reports_have_no_italic_violation(self):
        for label in sorted(self.cases):
            with self.subTest(module=label):
                case = self.cases[label]
                with tempfile.TemporaryDirectory() as td:
                    out = generate_report(case, td)
                    problems = check_italic.check(out)
                detail = '、'.join('%s:%r' % (k, s) for k, s, _ in problems[:6])
                self.assertEqual(problems, [], '%s 有正斜体问题：%s' % (label, detail))

    def test_function_names_stay_upright(self):
        """斜体片段里的 ln / lg / exp 必须被拎出来排正体。"""
        dk = load_module('化学动力学工具', 'docxkit')
        cases = {
            'ln(α−α_{∞})': 'ln',
            'lg(k_{1}−k_{0})': 'lg',
            'exp(-E/RT)': 'exp',
        }
        for text, fn in cases.items():
            segs = dk._split_runs_by_italic(text)
            hit = [(s, it) for s, it in segs if s == fn]
            self.assertTrue(hit, '%r 里没有单独的 %r run：%s' % (text, fn, segs))
            self.assertFalse(hit[0][1], '%r 里的 %r 被排成了斜体' % (text, fn))

    def test_variables_stay_italic(self):
        """函数名的豁免不能把真正的变量也排成正体。"""
        dk = load_module('化学动力学工具', 'docxkit')
        for text, var in (('Q_{V}', 'Q'), ('Δ T', 'T'), ('ln(α−α_{∞})', 'α')):
            segs = dk._split_runs_by_italic(text)
            hit = [(s, it) for s, it in segs if var in s]
            self.assertTrue(hit, '%r 里没找到 %r' % (text, var))
            self.assertTrue(any(it for _, it in hit),
                            '%r 里的 %r 应保持斜体：%s' % (text, var, segs))


if __name__ == '__main__':
    unittest.main()
