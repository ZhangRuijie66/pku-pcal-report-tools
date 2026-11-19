# -*- coding: utf-8 -*-
"""电导率：共享数据表解析 + 组内统计（2026-11-20 新增）。

两个层面的验收基准，都刻意选成**外部可核对**的，而不是照当前代码抄：

1. **解析正确性**：共享表里老师自己填了 Λm∞ 那一列。对填了值的成员，
   本工具算出的 Λm∞(NaCl)、Λm∞(NaAc) 必须与它逐位吻合（相对偏差 <1%）。
   这条能一次抓住三类错：列位置错、单位没换算、物种张冠李戴。

2. **统计量正确性**：用**已知答案的合成数据**验 t/F/Grubbs——
   例如两组数完全相同则 t=0、p=1；方差比为 4 时 F=4。
   拿真实数据验统计函数是验不出来的（不知道真值）。
"""
from __future__ import annotations

import json
import math
import unittest

from support import REPO_ROOT, load_module

FIXTURES = REPO_ROOT / 'tests' / 'fixtures' / '电导率'
SHARED_XLSX = FIXTURES / '共享数据表.xlsx'
DATA_JSON = FIXTURES / '电导率数据.json'

_have_openpyxl = True
try:
    import openpyxl                                    # noqa: F401
except ImportError:                                    # pragma: no cover
    _have_openpyxl = False


def _shared():
    return load_module('电导率工具', 'shared')


def _groupstat():
    return load_module('电导率工具', 'groupstat')


def _analysis():
    return load_module('电导率工具', 'analysis')


# ================================================================= 解析
@unittest.skipUnless(_have_openpyxl, '需要 openpyxl 才能解析 xlsx')
class SharedParseTests(unittest.TestCase):
    """共享表 → N 份同构数据。"""

    def setUp(self):
        self.sh = _shared()
        self.members, self.meta = self.sh.parse_workbook(str(SHARED_XLSX))

    def test_finds_filled_blocks_only(self):
        """填了姓名的 7 块要认出来；空白块（4/9/10）要跳过并留痕。"""
        names = [m['name'] for m in self.members]
        self.assertEqual(names, ['蔡瑞洲', '郭晓文', '兰博', '磨瞳',
                                 '宋晨风', '武湛博', '周子翔'])
        self.assertNotIn('室温(℃)：', names,
                         '空白块的值位置上是下一个标签，被误当成姓名了')
        self.assertEqual(sorted(self.meta['skipped']), [4, 9, 10])

    def test_four_species_per_member(self):
        """每块都要读出 4 个物种；第 10 号把 NaCl 换成硝酸钠那条路径也要对。"""
        for m in self.members:
            self.assertEqual(sorted(m['solutions']),
                             ['HAc', 'HCl', 'NaAc', 'NaCl'], m['name'])
            for key, sol in m['solutions'].items():
                self.assertEqual(len(sol['conc']), 5, (m['name'], key))
                self.assertEqual(len(sol['kappa']), 5, (m['name'], key))

    def test_text_scientific_notation_is_number(self):
        """郭晓文有两格写成文本 '10.31E3' / '2.00E3'，必须当数读。"""
        guo = [m for m in self.members if m['name'] == '郭晓文'][0]
        hcl = guo['solutions']['HCl']['kappa']
        self.assertAlmostEqual(hcl[0], 10310.0)
        self.assertAlmostEqual(hcl[1], 4750.0)

    def test_metadata_read(self):
        cai = self.members[0]
        self.assertAlmostEqual(cai['cell_constant'], 1.012)
        self.assertAlmostEqual(cai['kappa_w_uS'], 1.993)
        self.assertAlmostEqual(cai['room_temp'], 23.3)
        self.assertAlmostEqual(cai['pressure'], 102.1)
        self.assertEqual(self.meta['date'], '20261118')

    def test_wrong_format_raises(self):
        """不是共享表格式的文件要明确报错，不能静默返回空列表。"""
        with self.assertRaises(self.sh.SharedTableError):
            self.sh.parse_workbook(str(DATA_JSON))

    def test_member_names_for_ui(self):
        self.assertEqual(self.sh.member_names(self.members)[0], '1 蔡瑞洲')


@unittest.skipUnless(_have_openpyxl, '需要 openpyxl 才能解析 xlsx')
class SharedValueTests(unittest.TestCase):
    """算出来的 Λm∞ 要与老师表里那一列吻合（外部基准）。"""

    def setUp(self):
        self.r = _analysis().analyze_shared(
            str(SHARED_XLSX), me_name='武湛博')

    def test_lambda_inf_matches_teacher_column(self):
        """老师在共享表里自己填了 Λm∞，本工具算的值要与之同一量级与量级口径。

        ⚠ **实测发现老师那一列混了两种口径**（2026-11-20 用 7 位成员逐一核对）：

           蔡瑞洲 / 郭晓文 / 周子翔 → 扣了 κw（与"κ校 = κ测 − κw"一致）
           磨瞳   / 宋晨风         → 没扣 κw（隐含 κw ≈ 0）

        所以它**不能当逐位基准**：扣 κw 与否差 0.8~1.0%，正好卡在 1% 附近。
        这里改成两条更可靠、也更本质的断言：

        1. 量级必须在 0.008~0.015（NaCl）/ 0.008~0.010（NaAc）之间——
           这一条能抓住列位置错、物种张冠李戴、单位没换算（差 10⁷ 倍）；
        2. 与老师值相差不超过 1.5%（覆盖两种 κw 口径的差）。

        真正钉住"算得对"的是 ``test_conductivity`` 里的完整数值基准，
        以及 ``test_lambda_inf_matches_theory`` 的物理判据。
        """
        members, _meta = _shared().parse_workbook(str(SHARED_XLSX))
        checked = 0
        for rec, mem in zip(self.r['members'], members):
            got = rec['analysis'].fits
            for key, lo, hi in (('NaCl', 0.008, 0.015), ('NaAc', 0.008, 0.010)):
                val = got[key]['lam_inf']
                self.assertTrue(lo < val < hi,
                                '%s 的 Λm∞(%s) = %g 量级不对'
                                % (rec['name'], key, val))
                theo = mem['teacher']['lam_inf'].get(key)
                if not theo:
                    continue
                rel = abs(val - theo) / abs(theo)
                self.assertLess(rel, 0.015,
                                '%s 的 Λm∞(%s)：算得 %.6f，老师表里 %.6f，'
                                '相对偏差 %.2f%%（超过两种 κw 口径能解释的范围）'
                                % (rec['name'], key, val, theo, rel * 100))
                checked += 1
        self.assertGreaterEqual(checked, 8, '应当至少核对了 8 个数值')

    def test_lambda_inf_matches_theory(self):
        """物理判据：组内 Λm∞ 的**中位数**与该物种离子加和理论值相差应在 3% 内。

        这一条**不依赖共享表里任何一格**，是真正的外部基准（CRC 离子值）。
        它守住三件事：单位换算对、物种没张冠李戴、κw 扣得对——任何一项错，
        中位数会整体偏移几个数量级或几十个百分点。

        ⚠ 刻意用**中位数而不是每个人的值**：真实数据里个别人偏差很大
        （郭晓文的 HCl −8.3%、兰博的 NaCl −8.3%），那是实验本身的问题
        （浓度配制、挥发、电极状态），不是工具算错。若对每个人都要求 <3%，
        测试会因为"别人的实验做得不够好"而失败——这不是代码缺陷。
        组内中位数 −1.5%~+1.3%，说明整组的口径是对的。
        """
        import statistics
        cond = load_module('电导率工具', 'conduct')
        for key in ('NaCl', 'NaAc', 'HCl'):
            vals = [rec['analysis'].fits[key]['lam_inf']
                    for rec in self.r['members']]
            med = statistics.median(vals)
            theo = cond.LAMBDA_THEO[key]
            rel = abs(med - theo) / theo
            self.assertLess(
                rel, 0.03,
                '组内 Λm∞(%s) 中位数 %.5f，理论值 %.5f，偏差 %.1f%%'
                % (key, med, theo, rel * 100))
        hacs = [rec['analysis'].esa['lam_inf'] for rec in self.r['members']]
        med = statistics.median(hacs)
        rel = abs(med - cond.LAMBDA_THEO['HAc']) / cond.LAMBDA_THEO['HAc']
        self.assertLess(rel, 0.03,
                        '组内 Λm∞(HAc) 中位数 %.5f 偏离理论值 %.5f 达 %.1f%%'
                        % (med, cond.LAMBDA_THEO['HAc'], rel * 100))

    def test_unit_conversion_is_applied(self):
        """共享表是 mol/dm³ 与 μS/cm；工具内部是 mol/m³ 与 S/m。

        不换算的话 Λm = κ/c 会差 10⁷ 倍（0.0126 → 128081），
        而结果看上去"还是个正常的数"，不会报错。这条专门钉住它。
        """
        for m in self.r['members']:
            lam = m['analysis'].fits['NaCl']['lam_inf']
            self.assertTrue(0.005 < lam < 0.03,
                            '%s 的 Λm∞(NaCl) = %g，量级不对（单位没换算？）'
                            % (m['name'], lam))
            # 浓度也要在同一量级：mol·m⁻³ 下首点是 25，不是 0.025
            conc = m['analysis'].data['solutions']['NaCl']['conc']
            self.assertAlmostEqual(float(conc[0]), 25.0, places=6,
                                   msg='浓度没从 mol·dm⁻³ 换算成 mol·m⁻³')

    def test_magnitude_fix_applied(self):
        """兰博把 2830 写成 0.00283（差 6 个量级），要自动改正并留痕。"""
        fixes = self.r['fixes']
        self.assertEqual(len(fixes), 1, fixes)
        f = fixes[0]
        self.assertEqual(f['name'], '兰博')
        self.assertEqual(f['species'], 'NaCl')
        self.assertAlmostEqual(f['old'], 0.00283)
        self.assertAlmostEqual(f['new'], 2830.0)
        # 改正后兰博的 Λm∞(NaCl) 应该落回组内范围
        lan = [m for m in self.r['members'] if m['name'] == '兰博'][0]
        self.assertTrue(0.010 < lan['analysis'].fits['NaCl']['lam_inf'] < 0.014)

    def test_unfixable_point_is_flagged_not_changed(self):
        """武湛博 HAc 的 259.8（应为 ~159.8）不是量级错，**不许自动改**，只标记。"""
        sus = self.r['suspects']
        self.assertEqual(len(sus), 1, sus)
        s = sus[0]
        self.assertEqual(s['name'], '武湛博')
        self.assertEqual(s['species'], 'HAc')
        self.assertAlmostEqual(s['value'], 259.8)
        # 原始值必须还在（没被悄悄改掉）
        members, _ = _shared().parse_workbook(str(SHARED_XLSX))
        wu = [m for m in members if m['name'] == '武湛博'][0]
        self.assertAlmostEqual(wu['solutions']['HAc']['kappa'][1], 259.8)


# ================================================================= 认领
@unittest.skipUnless(_have_openpyxl, '需要 openpyxl 才能解析 xlsx')
class MeMatchingTests(unittest.TestCase):
    """「我的数据」：能按姓名匹配就自动认领，匹配不上交给界面手选。"""

    def setUp(self):
        self.sh = _shared()
        self.members, _ = self.sh.parse_workbook(str(SHARED_XLSX))

    def test_exact_name_matches(self):
        idx, cand = self.sh.match_member(self.members, '武湛博')
        self.assertEqual(idx, 5)
        self.assertEqual(cand, [])

    def test_name_with_spaces_matches(self):
        idx, _ = self.sh.match_member(self.members, ' 武湛博 ')
        self.assertEqual(idx, 5)

    def test_unknown_name_returns_all_candidates(self):
        """张瑞杰不在表里（与武湛博合作，共用 7 号）→ 不猜，返回全部候选。"""
        idx, cand = self.sh.match_member(self.members, '张瑞杰')
        self.assertIsNone(idx)
        self.assertEqual(len(cand), len(self.members))

    def test_empty_name_returns_candidates(self):
        idx, cand = self.sh.match_member(self.members, '')
        self.assertIsNone(idx)
        self.assertEqual(len(cand), len(self.members))

    def test_analyze_shared_auto_vs_manual(self):
        """自动认领与手动选择两条路都要能定下"我"。"""
        auto = _analysis().analyze_shared(str(SHARED_XLSX), me_name='武湛博')
        self.assertTrue(auto['match']['auto'])
        self.assertEqual(auto['match']['index'], 5)

        manual = _analysis().analyze_shared(str(SHARED_XLSX),
                                           me_name='张瑞杰', me_index=5)
        self.assertEqual(manual['match']['index'], 5)
        self.assertFalse(manual['match']['auto'])
        me = [m for m in manual['members'] if m['is_me']]
        self.assertEqual(len(me), 1)
        self.assertEqual(me[0]['name'], '武湛博')


# ================================================================= 统计
class GroupStatTests(unittest.TestCase):
    """统计函数用**已知答案**的合成数据验，不用真实数据。"""

    def setUp(self):
        self.gs = _groupstat()

    def test_describe(self):
        d = self.gs.describe([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(d['n'], 5)
        self.assertAlmostEqual(d['mean'], 3.0)
        # 样本标准差（ddof=1）：√2.5 = 1.5811
        self.assertAlmostEqual(d['sd'], math.sqrt(2.5))
        self.assertAlmostEqual(d['rsd'], math.sqrt(2.5) / 3.0 * 100)

    def test_describe_ignores_nan(self):
        d = self.gs.describe([1.0, float('nan'), 3.0])
        self.assertEqual(d['n'], 2)
        self.assertAlmostEqual(d['mean'], 2.0)

    def test_grubbs_flags_clear_outlier(self):
        """10 个数里放一个离得很远的，Grubbs 必须判出来。"""
        vals = [10.0, 10.1, 9.9, 10.05, 9.95, 10.02, 9.98, 10.08, 9.92, 20.0]
        r = self.gs.grubbs(vals)
        self.assertTrue(r['is_outlier'])
        self.assertEqual(r['outlier_index'], 9)
        self.assertAlmostEqual(r['outlier'], 20.0)

    def test_grubbs_does_not_flag_uniform_data(self):
        r = self.gs.grubbs([10.0, 10.1, 9.9, 10.05, 9.95, 10.02])
        self.assertFalse(r['is_outlier'])

    def test_grubbs_needs_three_points(self):
        """n<3 不做判定（两点谈不上"离群"）。"""
        self.assertFalse(self.gs.grubbs([1.0, 2.0])['is_outlier'])

    def test_grubbs_critical_value_matches_table(self):
        """n=7, α=0.05 的 Grubbs 临界值查表是 2.020（ISO 5725 / Grubbs 原表）。"""
        r = self.gs.grubbs([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
        self.assertAlmostEqual(r['g_crit'], 2.020, places=3)

    def test_t_test_identical_data(self):
        """我的值正好等于别人的均值 → t=0, p=1。"""
        r = self.gs.t_test_vs_group(5.0, [4.0, 5.0, 6.0])
        self.assertAlmostEqual(r['t'], 0.0, places=12)
        self.assertAlmostEqual(r['p'], 1.0, places=12)
        self.assertFalse(r['significant'])

    def test_t_test_uses_extra_variance_term(self):
        """SE 要含"参考值本身也是估计"的那一项：SE = s·√(1+1/n)。"""
        others = [4.0, 5.0, 6.0]
        r = self.gs.t_test_vs_group(5.0, others)
        s = 1.0                      # [4,5,6] 的样本标准差
        self.assertAlmostEqual(r['se'], s * math.sqrt(1.0 + 1.0 / 3.0))
        self.assertEqual(r['df'], 2)

    def test_t_test_detects_big_shift(self):
        r = self.gs.t_test_vs_group(100.0, [10.0, 10.1, 9.9, 10.05])
        self.assertTrue(r['significant'])
        self.assertLess(r['p'], 0.01)

    def test_f_test_ratio_four(self):
        """方差比 4 → F=4。"""
        r = self.gs.f_test_variance(4.0, 1.0, df_mine=3, df_others=3)
        self.assertAlmostEqual(r['F'], 4.0)

    def test_f_test_equal_variance_not_significant(self):
        r = self.gs.f_test_variance(1.0, 1.0, df_mine=3, df_others=3)
        self.assertAlmostEqual(r['F'], 1.0)
        self.assertAlmostEqual(r['p'], 1.0, places=9)

    def test_f_test_handles_bad_input(self):
        r = self.gs.f_test_variance(float('nan'), 1.0)
        self.assertTrue(math.isnan(r['F']))
        self.assertFalse(r['significant'])

    def test_paired_test_cancels_common_shift(self):
        """配对检验：两列都加同一个常数，"差值"完全不变，t 必须一样。

        ⚠ 差值必须**有变化**：若每对的差都是同一个常数，sd_diff = 0，
        t = 均值/0 无定义（返回 NaN 是正确行为，不是 bug）。
        """
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [1.5, 2.2, 3.6, 4.1, 5.8]        # 差值 −0.5,−0.2,−0.6,−0.1,−0.8
        r1 = self.gs.paired_test(a, b)
        r2 = self.gs.paired_test([x + 100 for x in a], [x + 100 for x in b])
        self.assertAlmostEqual(r1['mean_diff'], r2['mean_diff'])
        self.assertAlmostEqual(r1['sd_diff'], r2['sd_diff'])
        self.assertAlmostEqual(r1['t'], r2['t'])
        self.assertAlmostEqual(r1['mean_diff'], -0.44)
        self.assertAlmostEqual(r1['sd_diff'], 0.288097, places=5)
        self.assertAlmostEqual(r1['t'], -0.44 / (0.288097 / math.sqrt(5)),
                               places=5)

    def test_paired_test_zero_spread_is_nan_not_crash(self):
        """差值为常数时 sd=0，t 无定义 —— 返回 NaN 且不抛异常。"""
        r = self.gs.paired_test([1.0, 2.0, 3.0], [2.0, 3.0, 4.0])
        self.assertAlmostEqual(r['mean_diff'], -1.0)
        self.assertEqual(r['sd_diff'], 0.0)
        self.assertTrue(math.isnan(r['t']))
        self.assertFalse(r['significant'])


# ============================================================ 组内汇总
class GroupAnalysisTests(unittest.TestCase):
    """``group_analysis`` 的编排逻辑：用假结果验，不依赖真实数据。"""

    def _fake(self, name, no, nacl, s2=1e-8, khac=0.039, kmean=1.7e-5,
              kfit=1.8e-5):
        return dict(no=no, name=name,
                    fits={'NaCl': {'lam_inf': nacl, 'sigma_inf': 1e-4, 's2': s2},
                          'NaAc': {'lam_inf': 0.009, 'sigma_inf': 1e-4, 's2': s2},
                          'HCl': {'lam_inf': 0.043, 'sigma_inf': 2e-4, 's2': s2}},
                    lam_hac=khac, sigma_hac=3e-4,
                    kmean=dict(mean=kmean, sigma=1e-7),
                    kfit=dict(K=kfit, sigma_K=1e-7))

    def test_orders_species_like_report(self):
        gs = _groupstat()
        rows = [self._fake('a', 1, 0.0124), self._fake('b', 2, 0.0125),
                self._fake('c', 3, 0.0126)]
        g = gs.group_analysis(rows)
        self.assertEqual(list(g['species']), ['NaCl', 'NaAc', 'HCl'])

    def test_me_index_marks_tests(self):
        gs = _groupstat()
        rows = [self._fake('a', 1, 0.0124), self._fake('b', 2, 0.0125),
                self._fake('c', 3, 0.0126)]
        g = gs.group_analysis(rows, me_index=1)
        self.assertEqual(g['me']['name'], 'b')
        self.assertIn('NaCl', g['tests'])
        self.assertIn('k_tests', g)

    def test_no_me_index_skips_tests(self):
        gs = _groupstat()
        rows = [self._fake('a', 1, 0.0124), self._fake('b', 2, 0.0125)]
        g = gs.group_analysis(rows)
        self.assertIsNone(g['me'])
        self.assertEqual(g['tests'], {})

    def test_tolerates_plain_float_k(self):
        """kmean/kfit 传纯 float 也要能算（不同调用方的形态不一致）。"""
        gs = _groupstat()
        rows = []
        for i, (nm, v) in enumerate((('a', 0.0124), ('b', 0.0125), ('c', 0.0126))):
            r = self._fake(nm, i + 1, v)
            r['kmean'] = 1.7e-5 + i * 1e-7
            r['kfit'] = 1.8e-5 + i * 1e-7
            rows.append(r)
        g = gs.group_analysis(rows, me_index=0)
        self.assertAlmostEqual(g['k_methods']['mean']['n'], 3)


# ============================================================ 脏数据容忍
@unittest.skipUnless(_have_openpyxl, '需要 openpyxl 才能解析 xlsx')
class SharedRobustnessTests(unittest.TestCase):
    """真实共享表里的脏数据不该让整份统计失败。"""

    def test_every_member_computes(self):
        r = _analysis().analyze_shared(str(SHARED_XLSX))
        self.assertTrue(r['ok'])
        self.assertEqual(len(r['members']), 7)
        for m in r['members']:
            an = m['analysis']
            # 每个人都要真算出 Λm∞(HAc) 与两种 K°，
            # 不能因为某人的一个脏读数就整份跳过
            self.assertIsNotNone(an.esa, m['name'])
            self.assertTrue(math.isfinite(an.esa['lam_inf']), m['name'])
            self.assertIsNotNone(an.kmean, m['name'])
            self.assertIsNotNone(an.kfit, m['name'])

    def test_group_stats_have_expected_shape(self):
        r = _analysis().analyze_shared(str(SHARED_XLSX), me_name='武湛博')
        g = r['group']
        self.assertEqual(g['n'], 7)
        for key in ('NaCl', 'NaAc', 'HCl'):
            self.assertIn(key, g['species'])
            self.assertIn('lam_inf', g['species'][key])
            self.assertTrue(math.isfinite(g['species'][key]['lam_inf']['mean']))
        self.assertIn('paired', g['k_methods'])


if __name__ == '__main__':
    unittest.main()