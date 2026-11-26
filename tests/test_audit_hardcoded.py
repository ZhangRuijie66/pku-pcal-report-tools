# -*- coding: utf-8 -*-
"""``audit_hardcoded.py`` 的自测：它必须区分「真写死」与「正常配置/术语」。

## 为什么

这一轮审计第一版报 138 处物种名，其中绝大多数是「仪器试剂」「方法名」
「术语」（最大气泡压力法、最高占据能级）——全是噪音。
用户要的是「哪些文字跟不上数据变化」，不是「哪些名词出现过」。

所以判据必须能区分：
    rb.para('莫尔盐（AR），CuSO₄·5H₂O（AR）')      ← 仪器试剂，正常
    rb.para('其中环己烷符合较好；水存在正偏差')      ← 结论，写死

本测试为两种情形各造样例，断言分类正确。
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

import audit_hardcoded as ah          # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def scan(self, body):
        p = Path(self._tmp.name) / 'report.py'
        p.write_text(textwrap.dedent(body), encoding='utf-8')
        return ah.scan_report(str(p))


class VerdictTests(_Base):
    """纯结论句（无 % 依赖）必须被报出来。"""

    def test_hardcoded_conclusion_is_caught(self):
        res = self.scan("""
            def f(rb):
                rb.para('其中环己烷的各热力学量与文献值符合较好；水的常压沸点存在系统性正偏差。')
        """)
        self.assertTrue(res['verdict'], '整段写死的结论没报出来')

    def test_data_driven_conclusion_is_not_reported(self):
        """带 % 的结论随数据变，不该报。"""
        res = self.scan("""
            def f(rb):
                rb.para('相对误差为 %.2f%%，与文献值符合较好。' % e)
        """)
        self.assertEqual(res['verdict'], [],
                         '带 %% 格式化的句子会随数据变，不该算写死')


class NoiseTests(_Base):
    """术语、方法名、仪器试剂不该进「结论」类。"""

    def test_method_name_is_not_a_conclusion(self):
        res = self.scan("""
            def f(rb):
                rb.para('用最大气泡压力法测定表面张力。')
        """)
        self.assertEqual(res['verdict'], [],
                         '「最大气泡压力法」是方法名，不是「最大值」的结论')

    def test_term_in_physics_text(self):
        res = self.scan("""
            def f(rb):
                rb.para('前 N/2 个能级被占据，最高占据能级的量子数为 n。')
        """)
        self.assertEqual(res['verdict'], [], '「最高占据能级」是术语')


class SpeciesTests(_Base):
    """物种名会被单独归类，便于人工判断是配置还是写死。"""

    def test_species_in_text_is_classified(self):
        res = self.scan("""
            def f(rb):
                rb.para('各浓度正丁醇溶液的液柱高度列于表3。')
        """)
        self.assertTrue(res['species'], '物种名没归到 species 类')

    def test_count_is_classified(self):
        res = self.scan("""
            def f(rb):
                rb.para('三个物种的拟合结果分别如图3~图5所示。')
        """)
        self.assertTrue(res['count'], '写死的数量没报出来')


class DataDependencyTests(unittest.TestCase):
    """`_has_data_dependency` 的边界。"""

    def test_percent_means_dependent(self):
        self.assertTrue(ah._has_data_dependency('偏差 %.2f%%'))

    def test_plain_text_means_independent(self):
        self.assertFalse(ah._has_data_dependency('符合较好'))


if __name__ == '__main__':
    unittest.main()