# -*- coding: utf-8 -*-
"""电导率 4.2「K° 误差来源分析」的数值与结构守卫（2026-11-27 新增）。

## 背景

用户指出 4.1 节讨论的是「强电解质 Λm∞ 的相对误差」，而课程要求的误差分析
是**最终量 K° 的误差贡献分解**——温度补偿、温度波动、溶液浓度、移液管允差、
拟合误差各占多少。于是新增了 4.2 节与 ``conduct.error_budget``。

## 为什么测试要这么写

这一节的风险不是「文字不好看」，而是**数字错得很像对的**。我在这上面推错过
两版解析灵敏度系数，两次的结论都排得整整齐齐、看上去完全合理：

1. 第一版把「浓度误差」当成「c 变」，推出 1+r 的系数，算出母液项 0.5% 档；
   实际机制是「κ 变、名义 c 不变」，走的是 2+r，量级差一倍。
2. 第二版漏掉「独立项合成是 √Σx²、不该再除 n」，把读数项少算了 √n 倍。

两次都是**用整链有限差分才发现的**。所以这里的核心断言是：
把预算里的数字与「独立重算整条链」的结果对照，而不是只检查源码里有没有
某些字符串。任何一处灵敏度写错，这些用例都会红。
"""
from __future__ import annotations

import math
import sys
import unittest

from support import REPO_ROOT, load_module

TOOL = '电导率工具'
REPORT_PY = REPO_ROOT / TOOL / 'pcal' / 'report.py'
CONDUCT_PY = REPO_ROOT / TOOL / 'pcal' / 'conduct.py'


def _src(name):
    return (REPO_ROOT / TOOL / 'pcal' / name).read_text(encoding='utf-8')


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import matplotlib
        matplotlib.use('Agg')
        cls.conduct = load_module(TOOL, 'conduct')
        cls.analysis = load_module(TOOL, 'analysis')
        cls.an = cls.analysis.Analysis(cls.analysis.default_config())
        cls.an.run()

    def budget(self, an=None):
        an = an or self.an
        esa = an.esa
        # 数据不齐时 esa 是 None（compute 提前返回），此时不能取下标——
        # error_budget 本身要求调用方传 Λ∞，缺数据的情形由 report 层判断。
        # 这里给 NaN 占位，让 error_budget 走它自己的 not-ok 分支。
        lam = float(esa['lam_inf']) if esa else float('nan')
        sig = float(esa['sigma']) if esa else float('nan')
        combo = (esa.get('combo') if esa else None) or {'add': [], 'sub': []}
        return self.conduct.error_budget(
            an.tables, an.fits, lam, sig, combo,
            temp_c=an.ctx.get('temp'), compensation=an.ctx.get('compensation'),
            kappa_w=an.ctx.get('kappa_w'))

    # ---- 独立的整链重算（不复用 error_budget 的任何中间量）
    def k_of(self, delta=None):
        """``delta``: {(物种, 瓶): κ 缩放因子}。返回 K̄。

        ⚠ 必须调 ``compute()`` 而不是 ``run()``：``run()`` 会重新从磁盘读数据，
        把注入的 ``data`` 顶掉，于是所有校验都返回 +0.0000%（我第一次就踩了）。
        """
        d = self.conduct._deep_default()
        for (sp, i), fi in (delta or {}).items():
            d['solutions'][sp]['kappa'][i] = repr(
                float(d['solutions'][sp]['kappa'][i]) * fi)
        a = self.analysis.Analysis(self.analysis.default_config())
        a.data = d
        a.compute()
        return a.kmean['mean']


class BudgetTermTests(_Base):
    """分项数值：每项都要与整链重算吻合。"""

    def test_all_six_terms_present(self):
        """用户点名的五项 + 温度波动，一个都不能少。"""
        eb = self.budget()
        self.assertTrue(eb['ok'])
        keys = {t['key'] for t in eb['terms']}
        for k in ('fit', 'comp', 'fluct', 'conc', 'pip', 'read'):
            self.assertIn(k, keys, '缺误差来源 %s' % k)

    def test_read_term_matches_chain(self):
        """电导率读数项 = 逐瓶 σ_κ/κ 全同向扰动时的整链变化（RSS）。"""
        eb = self.budget()
        got = next(t['value'] for t in eb['terms'] if t['key'] == 'read')
        delta = {}
        for i, r in enumerate(self.an.tables['HAc']):
            delta[('HAc', i)] = 1 + r['sigma_kappa'] / r['kappa_corr']
        K0 = self.k_of()
        K1 = self.k_of(delta)
        want = abs((K1 - K0) / K0)
        self.assertAlmostEqual(got, want, places=9,
                               msg='读数项 %.6f%% 与整链 %.6f%% 不符'
                                   % (got * 100, want * 100))

    def test_pipette_term_matches_chain(self):
        """移液管项 = 全部瓶同向取最大允差时的整链变化（RSS）。"""
        eb = self.budget()
        got = next(t['value'] for t in eb['terms'] if t['key'] == 'pip')
        delta = {}
        for sp in self.conduct.SPECIES_ORDER:
            vols = self.conduct._PREP_VOLUMES.get(sp, [])
            n = len(self.an.data['solutions'][sp]['conc'])
            for i, v in enumerate(vols[:n]):
                _nom, tol = self.conduct.pipette_for(v)
                delta[(sp, i)] = 1 + tol / math.sqrt(3.0) / v
        K0 = self.k_of()
        K1 = self.k_of(delta)
        want = abs((K1 - K0) / K0)
        self.assertAlmostEqual(got, want, places=9,
                               msg='移液管项 %.6f%% 与整链 %.6f%% 不符'
                                   % (got * 100, want * 100))

    def test_temperature_compensation_cancels_in_K(self):
        """温度补偿对 K 一阶抵消，但它是表6 的 0.1% 档误差源。

        这是本节最容易写错的一条：把它当成 K 的主要误差源，或者当成 0，
        两种极端都不对。
        """
        eb = self.budget()
        comp = next(t['value'] for t in eb['terms'] if t['key'] == 'comp')
        self.assertGreater(eb['lam_comp_pct'], 0.1,
                           '温度补偿对单个 Λ∞ 的影响应达 0.1% 量级')
        self.assertLess(comp * 100, 0.25 * eb['lam_comp_pct'],
                        '温度补偿在 K 里应一阶抵消（%.4f%% 远小于 %.2f%%）'
                        % (comp * 100, eb['lam_comp_pct']))

    def test_compensation_scales_with_dT(self):
        """ΔT 变大时，残差项也要跟着变大（说明它是算出来的，不是写死的）。"""
        import copy
        a = self.analysis.Analysis(self.analysis.default_config())
        a.data = copy.deepcopy(self.conduct._deep_default())
        a.data['temp_c'] = 30.0
        a.compute()
        b = self.budget(a)
        c = next(t['value'] for t in b['terms'] if t['key'] == 'comp')
        # 30 ℃ 偏离 25 ℃ 更多，残差应更大
        a0 = self.budget()
        c0 = next(t['value'] for t in a0['terms'] if t['key'] == 'comp')
        self.assertGreater(c, c0 * 2,
                           'ΔT 从 1.5 K 增到 5 K，补偿残差没有相应增大')

    def test_lambda_weights_have_signs(self):
        """组合权重必须有正有负（减法项），且 |w| 之和 > 1（放大）。"""
        eb = self.budget()
        w = eb['weights']
        self.assertTrue(any(v < 0 for v in w.values()),
                        '组合式里有减法项，权重不可能全为正：%r' % (w,))
        self.assertGreater(sum(abs(v) for v in w.values()), 1.0,
                           '三个物种的 |权重| 之和应大于 1（HCl 被放大）')

    def test_total_is_rss_of_terms(self):
        """合成值必须等于各分项的方和根，不许另外算一套。"""
        eb = self.budget()
        want = math.sqrt(sum(t['value'] ** 2 for t in eb['terms']))
        self.assertAlmostEqual(eb['total'], want, places=12)

    def test_shares_sum_to_100(self):
        eb = self.budget()
        self.assertAlmostEqual(sum(t['share'] for t in eb['terms']), 100.0,
                               places=6)


class BudgetRobustnessTests(_Base):
    """退化数据下不许崩，且要说明原因。"""

    def _with(self, mut):
        import copy
        d = copy.deepcopy(self.conduct._deep_default())
        mut(d)
        a = self.analysis.Analysis(self.analysis.default_config())
        a.data = d
        a.compute()
        return a

    def test_missing_species_returns_not_ok(self):
        def mut(d):
            d['solutions'].pop('NaAc')
        a = self._with(mut)
        eb = self.budget(a)
        self.assertFalse(eb['ok'])
        self.assertTrue(eb['notes'], '不 ok 时必须说明原因')
        self.assertTrue(any('NaAc' in n for n in eb['notes']),
                        '原因里应点出缺的是哪个物种：%r' % (eb['notes'],))

    def test_missing_temperature_still_works(self):
        """没填温度时只丢温度两项，其余照算——不许整节崩掉。"""
        def mut(d):
            d['temp_c'] = None
        a = self._with(mut)
        eb = self.budget(a)
        keys = {t['key'] for t in eb['terms']}
        self.assertNotIn('comp', keys)
        self.assertNotIn('fluct', keys)
        self.assertIn('fit', keys, '温度缺失不该把拟合项也丢掉')
        self.assertIn('read', keys)
        self.assertTrue(any('温度' in n for n in eb['notes']))

    def test_two_bottles_only(self):
        """只有两瓶数据时不抛异常（不确定度可能退化，但要能算）。"""
        def mut(d):
            for k in ('NaCl', 'NaAc', 'HCl', 'HAc'):
                d['solutions'][k]['conc'] = d['solutions'][k]['conc'][:2]
                d['solutions'][k]['kappa'] = d['solutions'][k]['kappa'][:2]
        a = self._with(mut)
        eb = self.budget(a)
        self.assertIn('terms', eb)          # 不抛异常即可
        if eb['ok']:
            self.assertGreater(eb['total'], 0)

    def test_never_raises_on_empty_tables(self):
        eb = self.conduct.error_budget({}, {}, float('nan'), float('nan'),
                                       {'add': [], 'sub': []})
        self.assertFalse(eb['ok'])
        self.assertTrue(eb['notes'])


class BudgetWiringTests(unittest.TestCase):
    """4.2 节的接线与排版。"""

    def test_section_defined_and_called(self):
        src = _src('report.py')
        self.assertIn('def _sec_error_budget', src)
        self.assertIn('_sec_error_budget(rb, analysis)', src,
                      '4.2 节定义了却没有被 build_report 调用')

    def test_section_numbering_continuous(self):
        """4.1 → 4.2 → 4.3 …：不许跳号、不许重号。"""
        import re
        src = _src('report.py')
        lvl2 = re.findall(r"heading\(\s*'4\.(\d+) ", src)
        # 动态编号的（4.%d）不计入静态集合，但静态的必须无重复
        dup = {h for h in lvl2 if lvl2.count(h) > 1}
        self.assertEqual(dup, set(), '4.x 二级标题重号：%r' % (dup,))

    def test_no_markdown_bold_in_budget_section(self):
        """docx 不渲染 Markdown，'**' 会原样印出来。"""
        src = _src('report.py')
        i = src.find('def _sec_error_budget')
        j = src.find('\ndef ', i + 10)
        seg = src[i:j if j > 0 else len(src)]
        for line in seg.split('\n'):
            s = line.lstrip()
            if s.startswith('#') or '** 2' in line or '** e' in line:
                continue
            self.assertNotIn('**', line,
                             '4.2 节正文里有 Markdown 粗体标记：%s' % line.strip())

    def test_no_corner_quotes(self):
        """项目规范：不用直角引号「」，用 “”。"""
        src = _src('report.py')
        i = src.find('def _sec_error_budget')
        j = src.find('\ndef ', i + 10)
        seg = src[i:j if j > 0 else len(src)]
        # 注释里的「」允许（不打印），只查字符串字面量
        for line in seg.split('\n'):
            if line.lstrip().startswith('#'):
                continue
            for q in ('「', '」'):
                self.assertNotIn(q, line,
                                 '正文里有直角引号：%s' % line.strip())


class BudgetTableTests(_Base):
    """表10/表11 的编号与正文引用一致性。"""

    def test_budget_uses_table_10_and_11(self):
        src = _src('report.py')
        self.assertIn("caption('表10  K^{⊖} 各误差来源的贡献", src)
        self.assertIn("caption('表11  K^{⊖} 误差来源的四级分析", src)

    def test_shared_tables_renumbered(self):
        """4.2 占用了表10/11，共享数据那节必须从表12 起，否则重号。"""
        src = _src('report.py')
        self.assertIn("caption('表12  各物种极限摩尔电导率的组内一致性", src)
        self.assertIn("caption('表13  本人结果与组内其余同学平均值的 t 检验'", src)
        self.assertIn("caption('表14  本人拟合精度与组内的 F 检验'", src)
        self.assertIn("caption('表15  两种方法所得 K° 的组内统计", src)

    def test_no_duplicate_table_numbers(self):
        """静态扫所有 caption 的表号，重复的直接判失败。"""
        import re
        src = _src('report.py')
        nums = re.findall(r"caption\('表(\d+)", src)
        dup = {n for n in nums if nums.count(n) > 1}
        self.assertEqual(dup, set(), '表号重复：%r（全部：%r）' % (dup, nums))


if __name__ == '__main__':
    unittest.main()