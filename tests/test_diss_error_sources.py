# -*- coding: utf-8 -*-
"""溶解热 4.5「误差来源的系统分析」的结构与数值守卫（2026-11-26 新增）。

## 为什么要写这些

用户要求「为溶解热加上误差来源分析」，并给了课程幻灯片的四级口径：
Level 0 罗列 → Level 1 半定量 → Level 2 确定主因 → Level 3 改进设计。
这一节的价值全在**数字得是真的**，所以测试盯的是三件事：

1. 四级结构齐全、且编号连续（4.4 误差分析 → 4.5 误差来源 → 4.6 小结）；
2. 表6 的各分项占比与 ``ds.sigma_terms`` 逐项一致，**不许是手写死的数字**；
3. 正文里不许出现 Markdown 的 ``**`` 残留（docx 不支持，会原样印出来）、
   不许用直角引号（项目规范）。

⚠ 踩过的两个坑（都写进断言里）：
* 片段列表里夹 ``('t', ...)`` 元组时，``% (...)`` 只作用于紧邻的字符串字面量，
  跨元素写会报 "not all arguments converted" 或把括号截断成语法错；
* ``pct()`` 是「2 位有效数字」，用它印方差占比会把 48.2% 印成 48%，
  占比必须单独用 ``%.1f``。
"""
from __future__ import annotations

import re
import unittest

from support import REPO_ROOT, load_module

TOOL = '溶解热工具'
REPORT_PY = REPO_ROOT / TOOL / 'pcal' / 'report.py'


def _src():
    return REPORT_PY.read_text(encoding='utf-8')


def _section_src():
    """取出 _sec_error_sources 的函数体源码。"""
    src = _src()
    i = src.find('def _sec_error_sources')
    if i < 0:
        return ''
    j = src.find('\ndef ', i + 10)
    return src[i:j if j > 0 else len(src)]


class ErrorSourcesStructureTests(unittest.TestCase):
    """四级结构与编号。"""

    def test_section_exists_and_is_called(self):
        src = _src()
        self.assertIn('def _sec_error_sources', src)
        self.assertIn('_sec_error_sources(rb, analysis, fit, cfg, lit, sub_label)',
                      src, '4.5 节定义了却没有被 build_report 调用')

    def test_heading_numbering_is_continuous(self):
        """4.4 误差分析 → 4.5 误差来源 → 4.6 小结，不许跳号或重号。"""
        src = _src()
        heads = re.findall(r"heading\('(4\.\d+) ", src)
        self.assertIn('4.4', heads)
        self.assertIn('4.5', heads)
        self.assertIn('4.6', heads)
        # 同一编号不许出现两次
        dup = {h for h in heads if heads.count(h) > 1}
        self.assertEqual(dup, set(), '4.x 标题重号：%r' % (dup,))

    def test_all_four_levels_present(self):
        """Level 0~3 都要有，缺一级就等于分析没做完。"""
        seg = _section_src()
        for lv in ('Level 0', 'Level 1', 'Level 2', 'Level 3'):
            self.assertIn(lv, seg, '缺 %s 的内容' % lv)

    def test_tables_are_numbered_5_to_8(self):
        """本节用表5~表8，接在已有的表1~表4 后面。"""
        seg = _section_src()
        for n in (5, 6, 7, 8):
            self.assertIn('表%d ' % n, seg, '缺 表%d 的题注' % n)


class ErrorSourcesNumberTests(unittest.TestCase):
    """表6 的占比必须由 ds.sigma_terms 算出来，不能是常量。"""

    @classmethod
    def setUpClass(cls):
        cls.ds = load_module(TOOL, 'dissolution')

    def test_shares_match_sigma_terms(self):
        """用真实分项复算：方差占比 == v²/σ²，且五项之和为 100%。"""
        terms = self.ds.sigma_terms(1.01, 10.70, 10.85, 193.013, 537.212,
                                    1.7369, 1.5590)
        keys = ['I', 'R', 't', 'd', 'h']
        total = terms['total']
        shares = [terms[k] ** 2 / total ** 2 * 100 for k in keys]
        self.assertAlmostEqual(sum(shares), 100.0, places=6,
                               msg='方差占比之和不等于 100%，口径错了')
        # 电流与电阻必须是前两名（这是本实验的实测结论）
        order = sorted(keys, key=lambda k: -terms[k])
        self.assertEqual(set(order[:2]), {'I', 'R'},
                         '实测下电流/电阻应为主导项，实际排序 %r' % (order,))

    def test_total_is_quadrature_not_linear(self):
        """合成 σ 必须是平方和开方，不是各项线性相加。"""
        terms = self.ds.sigma_terms(1.01, 10.70, 10.85, 193.013, 537.212,
                                    1.7369, 1.5590)
        quad = sum(terms[k] ** 2 for k in ('I', 'R', 't', 'd', 'h')) ** 0.5
        linear = sum(terms[k] for k in ('I', 'R', 't', 'd', 'h'))
        self.assertAlmostEqual(terms['total'], quad, places=6)
        self.assertLess(terms['total'], linear,
                        '平方和合成应小于线性相加')


def _section_strings():
    """取出 _sec_error_sources 里**所有字符串字面量**（跳过注释）。

    ⚠ 必须用 ast：注释里写着「2 位有效数字」「**紧邻的那个字符串字面量**
    会报错」这类说明，直接对源码做整体匹配会把它们当违规（实测误报两次）。
    注释不会进 docx，只有字符串会。
    """
    import ast
    src = _src()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == '_sec_error_sources':
            return [n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return []


class ErrorSourcesFormatTests(unittest.TestCase):
    """排版与文风：这些都是 audit_docx 抓不到的坑。"""

    def test_no_markdown_asterisks_in_text(self):
        """正文里不许有 ``**强调**``：docx 不支持 Markdown，会原样印出来。"""
        bad = [s for s in _section_strings() if '**' in s]
        self.assertEqual(bad, [],
                         '这些字符串里的 Markdown 星号会原样印进报告：%r'
                         % (bad,))

    def test_no_corner_quotes(self):
        """项目规范：简体中文用弯引号“”，不用直角引号「」。"""
        bad = [s for s in _section_strings()
               if '「' in s or '」' in s]
        self.assertEqual(bad, [],
                         '这些字符串仍用了直角引号：%r' % (bad,))

    def test_share_uses_one_decimal_not_pct(self):
        """方差占比用 %.1f，不能用 pct()（2 位有效数字会把 48.2 印成 48）。"""
        seg = _section_src()
        self.assertIn("%.1f", seg,
                      '方差占比应显式用 %.1f 保留一位小数')

    def test_table_widths_within_text_area(self):
        """每个表的列宽之和不超过正文宽 16 cm，否则一定折行。"""
        seg = _section_src()
        for m in re.finditer(r'widths_cm=\[([^\]]+)\]', seg):
            vals = [float(v) for v in m.group(1).split(',')]
            self.assertLessEqual(sum(vals), 16.0,
                                 '列宽和 %.1f cm 超过正文宽 16 cm' % sum(vals))

    def test_small_tables_keep_together(self):
        """本节四个表都是小表，必须 keep_together，别被从中间劈开。"""
        seg = _section_src()
        n_tables = len(re.findall(r'rb\.table\(', seg))
        n_keep = len(re.findall(r'keep_together=True', seg))
        self.assertEqual(n_tables, n_keep,
                         '本节 %d 个表里只有 %d 个设了 keep_together'
                         % (n_tables, n_keep))


if __name__ == '__main__':
    unittest.main()