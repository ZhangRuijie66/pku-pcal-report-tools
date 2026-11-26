# -*- coding: utf-8 -*-
"""表面吸附：换溶质时报告文字必须跟着变（2026-11-27 修完后钉住）。

## 背景

原来 `report.py` 里有 11 处写死「正丁醇」——摘要、试剂、步骤、表3/表4/表6
的题注、讨论、结论。这个实验按讲义确实是正丁醇，但换成其它醇或表面活性剂
时这些地方全部变成错的，而**代码里没有任何开关能改**。

修法：`analysis.default_config()` 增加 `solute_name`（默认「正丁醇」），
`report.py` 一律从配置取。

本测试真的换一个溶质名生成报告，断言：
1. 新名字出现在所有该出现的位置；
2. 旧名字**一处都不残留**（这一条最关键 —— 漏改一处就会自相矛盾）。
"""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest

from support import REPO_ROOT

TOOL = '表面吸附工具'
PKG = 'pcal_ads_solute_test'


def _load():
    import importlib
    import importlib.util
    if PKG in sys.modules:
        pkg = sys.modules[PKG]
    else:
        pkg_dir = REPO_ROOT / TOOL / 'pcal'
        spec = importlib.util.spec_from_file_location(
            PKG, pkg_dir / '__init__.py',
            submodule_search_locations=[str(pkg_dir)])
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[PKG] = pkg
        spec.loader.exec_module(pkg)
    mods = {}
    for m in ('adsorption', 'analysis', 'report'):
        mods[m] = importlib.import_module('%s.%s' % (PKG, m))
    return mods


class SoluteNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import matplotlib
        matplotlib.use('Agg')
        cls.mods = _load()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def render(self, solute, tag):
        from docx import Document
        ads = self.mods['adsorption']
        ana = self.mods['analysis']
        rpt = self.mods['report']
        cfg = ana.default_config()
        cfg['solute_name'] = solute
        cfg.update({'student_name': '测试', 'student_id': '000',
                    'group': '3', 'group_no': '8', 'date': '2026/11/27',
                    'room_temp': 21.0, 'pressure': 101.5,
                    'zero_correction': False, 'conc_axis': 'lg'})
        an = ads.analyze(copy.deepcopy(ads.sample_data()),
                         copy.deepcopy(cfg))
        out = os.path.join(self.tmp, '%s.docx' % tag)
        tpl = REPO_ROOT / TOOL / 'templates' / '表面吸附报告模板2026.docx'
        rpt.build_report(an, cfg, out, os.path.join(self.tmp, 'fig_' + tag),
                         str(tpl))
        d = Document(out)
        return '\n'.join(p.text for p in d.paragraphs)

    def test_config_has_solute_name(self):
        cfg = self.mods['analysis'].default_config()
        self.assertIn('solute_name', cfg, 'config 里没有 solute_name 字段')
        self.assertEqual(cfg['solute_name'], '正丁醇', '默认值应为讲义的溶质')

    def test_solute_name_is_persisted(self):
        """要能在界面里保存，否则用户改了重启就丢。"""
        self.assertIn('solute_name', self.mods['analysis'].PERSIST_KEYS)

    def test_default_solute_appears(self):
        text = self.render('正丁醇', 'default')
        self.assertIn('正丁醇', text)
        # 摘要、表题、试剂、讨论都要有
        for frag in ('测定了不同浓度正丁醇水溶液的表面张力',
                     '不同浓度正丁醇溶液的液柱高度',
                     '不同浓度正丁醇溶液的表面张力'):
            self.assertIn(frag, text, '缺少「%s」' % frag)

    def test_changed_solute_leaves_no_old_name(self):
        """换溶质后旧名字一处都不能残留 —— 这是本测试的核心。"""
        text = self.render('辛醇', 'octanol')
        self.assertIn('辛醇', text)
        self.assertNotIn('正丁醇', text,
                         '换溶质后仍残留「正丁醇」，说明还有写死的地方')

    def test_changed_solute_reaches_all_sections(self):
        text = self.render('辛醇', 'octanol2')
        for frag in ('测定了不同浓度辛醇水溶液的表面张力',
                     '不同浓度辛醇溶液的液柱高度',
                     '辛醇（AR）水溶液'):
            self.assertIn(frag, text, '新溶质名没到「%s」这一节' % frag)


if __name__ == '__main__':
    unittest.main()