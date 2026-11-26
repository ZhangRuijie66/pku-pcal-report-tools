# -*- coding: utf-8 -*-
"""``check_source_symbols.py`` 的自测：它必须真的能抓到「纯字符串里的量符号」。

## 为什么必须写

2026-11-26 第一版静态检查**漏掉了片段列表里的裸字符串**：

```python
rb.para(['...ε...', ('t','x',ITALIC)])   # ✗ 第一版不报，实际整段正体
```

当时它报「0 处」，而 docx 检查报 26 处 —— 两个工具结论不一致，
正是「假绿」的典型。补上判据后两边数字才对上（26 = 26）。

本文件为两类情形各造一个样例，断言能报 / 不报。
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from support import REPO_ROOT

TESTS_DIR = REPO_ROOT / 'tests'
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import check_source_symbols as css        # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def scan(self, body):
        p = self.tmp / 'report.py'
        p.write_text(textwrap.dedent(body), encoding='utf-8')
        return css.scan_file(str(p))


class DetectionTests(_Base):
    """纯字符串参数 / 片段列表裸字符串里的量符号都要报。"""

    def test_pure_string_argument_is_caught(self):
        probs = self.scan("""
            def f(rb):
                rb.para('因为 Λm∞ 是外推得到的量')
        """)
        self.assertTrue(probs, '纯字符串里的 Λ 没报出来')
        self.assertEqual(probs[0][1], 'greek-quantity')

    def test_bare_string_in_segment_list_is_caught(self):
        """片段列表里的裸字符串 —— 第一版漏掉的正是这一类。"""
        probs = self.scan("""
            def f(rb):
                rb.para(['所得 ε 应视为下限',
                         ('t', 'x', {'italic': True})])
        """)
        self.assertTrue(probs, '片段列表裸字符串里的 ε 没报出来')
        self.assertEqual(probs[0][1], 'greek-lower')

    def test_heading_and_caption_are_checked(self):
        probs = self.scan("""
            def f(rb):
                rb.heading('3.1.2 表面张力 γ 的计算', 3)
                rb.caption('图1  A(λ) 关系')
        """)
        self.assertEqual(len(probs), 2, 'heading/caption 都应该被检查：%r' % (probs,))


class ExemptionTests(_Base):
    """这些是正确写法，一个都不许报。"""

    def test_segment_tuple_is_exempt(self):
        probs = self.scan("""
            def f(rb):
                rb.para(['测得的 ', ('t', 'ε', {'italic': True}), ' 为下限'])
        """)
        self.assertEqual(probs, [], '片段元组里的 ε 已由样式控制，不该报')

    def test_equation_is_exempt(self):
        """equation 的参数是 LaTeX，正斜体由 OMML 层判定。"""
        probs = self.scan("""
            def f(rb):
                rb.equation(r'\\sigma=\\frac{\\varepsilon}{\\sqrt{S}}')
        """)
        self.assertEqual(probs, [], 'equation 的 LaTeX 不该报（会报出假阳性）')

    def test_unit_and_si_prefix_are_exempt(self):
        probs = self.scan("""
            def f(rb):
                rb.para('浓度 10 μmol·L⁻¹、电流 1 μA、电阻 10 Ω')
        """)
        self.assertEqual(probs, [], '单位串 / SI 词头 / 电阻单位 Ω 不该报')

    def test_chem_greek_prefix_is_exempt(self):
        """β-胡萝卜素是化合物名的一部分，正体正确。"""
        probs = self.scan("""
            def f(rb):
                rb.para('B1（β-胡萝卜素）含有 11 个共轭双键')
        """)
        self.assertEqual(probs, [], 'β-胡萝卜素 是化学名，不该报')


if __name__ == '__main__':
    unittest.main()