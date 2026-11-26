# -*- coding: utf-8 -*-
"""「数据变了文字要跟着变」的回归测试（2026-11-27 修完后钉住）。

## 为什么这些测试值得写

上一轮体检发现 4 处写死表述，其中**最严重的一处不是文字错，而是崩溃**：

    Analysis.compute() 在缺物种时优雅降级（记 warning、从 fits 去掉）
    → report.py 仍按硬编码 ('NaCl','NaAc','HCl') 取 fits[key]
    → KeyError，用户只是少了一瓶溶液的数据却得到「生成失败」

修完之后必须用**改造数据**的方式验证，不能只看源码里还有没有某个字符串：
静态扫描能过、运行时仍崩，是完全可能的（我这一轮就踩过 —— 改完摘要后
又在 `_sec_strong` 的 `an.esa['combo']` 崩了一次）。

所以这里的每个用例都**真的把数据改掉再生成一次报告**。
"""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest

from support import REPO_ROOT

TOOL = '电导率工具'


def _load_conduct():
    """载入电导率的 analysis / report（用唯一包名，避免 sys.modules 串味）。"""
    import importlib
    import importlib.util
    tool_dir = REPO_ROOT / TOOL
    name = 'pcal_conduct_hardcode_test'
    if name in sys.modules:
        pkg = sys.modules[name]
    else:
        pkg_dir = tool_dir / 'pcal'
        spec = importlib.util.spec_from_file_location(
            name, pkg_dir / '__init__.py',
            submodule_search_locations=[str(pkg_dir)])
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[name] = pkg
        spec.loader.exec_module(pkg)
    return (importlib.import_module(name + '.analysis'),
            importlib.import_module(name + '.report'))


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import matplotlib
        matplotlib.use('Agg')
        cls.ana, cls.rep = _load_conduct()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def make(self, drop=(), tag='t'):
        """删掉指定物种的数据后生成报告，返回 (docx 段落文本, analysis)。"""
        import json
        from docx import Document
        jp = REPO_ROOT / 'tests' / 'fixtures' / '电导率' / '电导率数据.json'
        with open(jp, encoding='utf-8') as fh:
            data = json.load(fh)
        for k in drop:
            data.get('solutions', {}).pop(k, None)
        cfg = self.ana.default_config()
        cfg.update({'student_name': '测试', 'student_id': '000',
                    'group': '3', 'group_no': '8', 'date': '2026/11/27'})
        a = self.ana.Analysis(copy.deepcopy(cfg))
        a.data = data
        a.compute()
        out = os.path.join(self.tmp, '%s.docx' % tag)
        tpl = REPO_ROOT / TOOL / 'templates' / '电导率报告模板2026.docx'
        self.rep.build_report(a, cfg, out, os.path.join(self.tmp, 'fig_' + tag),
                              str(tpl))
        d = Document(out)
        return '\n'.join(p.text for p in d.paragraphs), a


class MissingSpeciesTests(_Base):
    """缺任一物种都不许崩，且文字数量要跟着变。"""

    def test_full_data_says_three_species(self):
        text, a = self.make(())
        self.assertEqual(len(a.fits), 3)
        self.assertIn('3 个物种的拟合结果', text)
        self.assertIn('根据 3 条拟合直线', text)

    def test_missing_NaAc_does_not_crash(self):
        """原崩溃点：fits['NaAc'] / an.esa['combo'] / an.lit_table。"""
        text, a = self.make(['NaAc'], 'no_naac')
        self.assertEqual(sorted(a.fits), ['HCl', 'NaCl'])
        self.assertIn('2 个物种的拟合结果', text)
        self.assertIn('根据 2 条拟合直线', text)
        # 必须明确说明缺了什么，不能静默省略
        self.assertIn('缺少 NaAc', text)

    def test_missing_HCl_does_not_crash(self):
        """原崩溃点：死代码 f_worst = fits['HCl']。"""
        text, a = self.make(['HCl'], 'no_hcl')
        self.assertEqual(sorted(a.fits), ['NaAc', 'NaCl'])
        self.assertIn('缺少 HCl', text)

    def test_only_one_strong_species(self):
        text, a = self.make(['NaAc', 'HCl'], 'one')
        self.assertEqual(sorted(a.fits), ['NaCl'])
        self.assertIn('1 个物种的拟合结果', text)
        # 单数时不该写「分别」
        self.assertNotIn('1 个物种的拟合结果分别', text)

    def test_skipped_sections_are_explained_not_silent(self):
        """HAc 相关小节跳过时必须写明原因（读者否则以为报告漏印）。"""
        text, _a = self.make(['NaAc'], 'explain')
        self.assertIn('本次未完成', text)
        self.assertIn('从略', text)
        self.assertIn('补齐', text)


class AnalysisDefaultTests(_Base):
    """`Analysis` 的属性在提前 return 的路径上也必须存在。"""

    def test_lit_table_exists_when_data_incomplete(self):
        """`compute()` 在数据不齐时提前 return，`lit_table` 也不能缺。

        原来它只在 compute() 末尾赋值 → AttributeError（实测）。
        """
        import json
        jp = REPO_ROOT / 'tests' / 'fixtures' / '电导率' / '电导率数据.json'
        with open(jp, encoding='utf-8') as fh:
            data = json.load(fh)
        data['solutions'].pop('NaAc', None)
        a = self.ana.Analysis(self.ana.default_config())
        a.data = data
        a.compute()
        self.assertTrue(hasattr(a, 'lit_table'),
                        'compute() 提前 return 后 lit_table 不存在')
        self.assertEqual(a.lit_table, [])

    def test_optional_attributes_default_to_none(self):
        a = self.ana.Analysis(self.ana.default_config())
        for attr in ('esa', 'kmean', 'kfit', 'lit_table', 'shared'):
            self.assertTrue(hasattr(a, attr), '缺少默认值：%s' % attr)


if __name__ == '__main__':
    unittest.main()