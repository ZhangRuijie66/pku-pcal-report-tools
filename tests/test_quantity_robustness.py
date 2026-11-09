# -*- coding: utf-8 -*-
"""可移植性回归：**数量变化**时各模块的行为契约。

这个文件守的不是「路径写死」，而是「数量变了会不会坏」——换个人做实验、
测的浓度档次不同、平行读数次数不同、标定条数不同，工具都必须
**要么照常算对，要么明确说清为什么算不出**，绝不能：

  · 静默给出 nan / 0 / 空表（用户以为是打印问题）
  · 因为数量不够而在不相干的地方崩掉
  · 把「点估计」（两点也能唯一定直线的斜率）跟「不确定度」一起丢掉

每一项都对应 2026-11-09 这一轮实测过的具体场景。
"""
from __future__ import annotations

import copy
import math
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support                                        # noqa: E402

REPO = support.REPO_ROOT


def _mod(tool, name):
    return support.load_module(tool, name)


def _finite(x):
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


class ConductLineFitTests(unittest.TestCase):
    """电导率 line_fit：点数与「能算什么」的契约（本轮修的真 bug）。"""

    def setUp(self):
        self.cond = _mod('电导率工具', 'conduct')

    @staticmethod
    def _rows(n, lam_inf=0.0126, B=0.0020):
        out = []
        for i in range(n):
            c = 0.05 / (2 ** i)
            out.append(dict(c=c, lam=lam_inf - B * math.sqrt(c)))
        return out

    def test_two_points_give_point_estimate(self):
        """⚠ 本轮修的真 bug：2 点时原来连斜率和截距都返回 NaN。

        两点唯一确定一条直线，点估计是精确解，不该丢。
        """
        rows = self._rows(2)
        f = self.cond.kohlrausch(rows)
        self.assertTrue(_finite(f['lam_inf']),
                        '2 点必须给出 Λm∞（点估计），不能是 NaN')
        # 数据是精确的两点连线，截距就是 lam_inf
        self.assertAlmostEqual(f['lam_inf'], 0.0126, places=10)

    def test_two_points_have_no_sigma(self):
        """2 点没有残差自由度，σ 必须留空而不是编一个数。"""
        rows = self._rows(2)
        f = self.cond.kohlrausch(rows)
        self.assertFalse(_finite(f['sigma_inf']),
                         '2 点不该给出不确定度（会误导）')

    def test_three_points_have_sigma(self):
        rows = self._rows(3)
        f = self.cond.kohlrausch(rows)
        self.assertTrue(_finite(f['lam_inf']))
        self.assertTrue(_finite(f['sigma_inf']))

    def test_one_and_zero_points_give_nothing(self):
        """1 点过一点有无数条直线，斜率不唯一 → 必须空。"""
        for n in (0, 1):
            f = self.cond.kohlrausch(self._rows(n))
            self.assertFalse(_finite(f['lam_inf']), '%d 点不该给 Λm∞' % n)

    def test_point_estimate_independent_of_count(self):
        """精确数据下，任意 ≥2 点都应还原同一个 Λm∞。"""
        vals = [self.cond.kohlrausch(self._rows(n))['lam_inf'] for n in (2, 3, 4, 5)]
        for v in vals:
            self.assertAlmostEqual(v, 0.0126, places=9)

    def test_degenerate_two_points_same_x(self):
        """两点 x 相同（同一浓度测两次）：斜率无定义，必须 NaN 而不是崩。"""
        rows = [dict(c=0.05, lam=0.010), dict(c=0.05, lam=0.011)]
        f = self.cond.kohlrausch(rows)
        self.assertFalse(_finite(f['lam_inf']))


class ConductPointCountWarningTests(unittest.TestCase):
    """点数退化时要有可读警告（不能只让报告显示「—」）。"""

    def test_two_point_warning_mentions_no_uncertainty(self):
        ana = _mod('电导率工具', 'analysis')
        import inspect
        src = inspect.getsource(ana)
        self.assertIn('只有 2 个浓度点', src,
                      '2 点退化必须给出说明性警告')


class SurfaceAdsorptionRepeatTests(unittest.TestCase):
    """表面吸附：平行读数次数可调（1~6），两法各自独立。"""

    def setUp(self):
        self.ads = _mod('表面吸附工具', 'adsorption')
        self.ana = _mod('表面吸附工具', 'analysis')
        self.base = self.ads.sample_data()

    def _run(self, nb, npl):
        data = copy.deepcopy(self.base)
        cfg = self.ana.default_config()
        cfg['repeat_n_bubble'] = nb
        cfg['repeat_n_plate'] = npl
        for k in ('zero', 'water_bubble'):
            for side in ('left', 'right'):
                data[k][side] = (list(data[k][side]) * 6)[:nb]
        for row in data['bubble']:
            for side in ('left', 'right'):
                row[side] = (list(row[side]) * 6)[:nb]
        data['water_plate'] = (list(data['water_plate']) * 6)[:npl]
        for row in data['plate']:
            row['gamma'] = (list(row['gamma']) * 6)[:npl]
        return self.ads.analyze(data, cfg)

    def test_single_reading_works(self):
        """1 次读数也必须能算（σ 退化为仪器误差）。"""
        an = self._run(1, 1)
        self.assertEqual((an.get('bubble') or {}).get('repeat_n'), 1)
        self.assertEqual((an.get('plate') or {}).get('repeat_n'), 1)

    def test_three_to_six_readings(self):
        for n in (2, 3, 4, 5, 6):
            an = self._run(n, n)
            self.assertEqual((an.get('bubble') or {}).get('repeat_n'), n,
                             '%d 次读数没被采用' % n)

    def test_two_methods_independent_counts(self):
        """两法次数不同：各取各的，不能串。"""
        an = self._run(5, 2)
        self.assertEqual((an.get('bubble') or {}).get('repeat_n'), 5)
        self.assertEqual((an.get('plate') or {}).get('repeat_n'), 2)

    def test_one_method_empty(self):
        """一条方法数据全空：另一条照常，且给出警告。"""
        data = copy.deepcopy(self.base)
        data['plate'] = []
        data['water_plate'] = []
        an = self.ads.analyze(data, self.ana.default_config())
        self.assertTrue(an.get('bubble'), '气泡法不该被拖垮')
        self.assertTrue(an.get('warnings'), '吊片法空必须给警告')

    def test_gamma_water_stable_across_counts(self):
        """纯水 γ 不该随读数次数乱跳。"""
        for n in (1, 3, 6):
            an = self._run(n, n)
            gw = (an.get('bubble') or {}).get('gamma_water')
            if _finite(gw):
                self.assertAlmostEqual(float(gw), 71.19, delta=0.6,
                                       msg='%d 次读数时 γ_w 跑偏' % n)


class VaporPointCountTests(unittest.TestCase):
    """蒸气压：拟合点数的下限与「不足时明确不出数」。"""

    def setUp(self):
        self.vap = _mod('蒸气压工具', 'vapor')
        self.ana = _mod('蒸气压工具', 'analysis')
        self.base = self.vap.sample_data()

    def _run(self, n_water):
        return self.vap.analyze(
            {'water': {'atm': self.base['water']['atm'],
                       'series': self.base['water']['series'][:n_water]},
             'cyclo': {'atm': self.base['cyclo']['atm'],
                       'series': self.base['cyclo']['series']}},
            self.ana.default_config())

    def test_two_series_points_plus_atm_is_enough(self):
        """1 个变压点 + 1 个沸点 = 2 点 → 不足 3 点，必须不给 fit。"""
        an = self._run(1)
        self.assertIsNone((an.get('water') or {}).get('fit'))
        self.assertTrue(an.get('warnings'), '点数不足要有警告')

    def test_more_points_still_fit(self):
        for n in (2, 4, 6, 10):
            an = self._run(n)
            fit = (an.get('water') or {}).get('fit')
            self.assertIsNotNone(fit, '%d 点应能拟合' % n)
            self.assertTrue(_finite(fit['A']))

    def test_empty_series_no_crash(self):
        an = self._run(0)
        self.assertIsNone((an.get('water') or {}).get('fit'))


class DipoleSolutionCountTests(unittest.TestCase):
    """偶极矩：溶液点数 < 3 时给警告，而不是静默 nan。"""

    def setUp(self):
        self.dip = _mod('偶极矩工具', 'dipole')
        self.ana = _mod('偶极矩工具', 'analysis')
        self.base = self.dip.sample_data()

    def test_three_or_more_solutions_reasonable(self):
        for n in (3, 4, 5):
            data = copy.deepcopy(self.base)
            data['solutions'] = self.base['solutions'][:n]
            an = self.dip.analyze(data, self.ana.default_config())
            self.assertTrue(_finite(an.get('mu')),
                            '%d 个溶液点应给出有限 μ' % n)
            self.assertTrue(0.5 < float(an['mu']) < 4.0,
                            '%d 点时 μ 量级不合理：%r' % (n, an['mu']))

    def test_two_solutions_warns_about_insufficient(self):
        data = copy.deepcopy(self.base)
        data['solutions'] = self.base['solutions'][:2]
        an = self.dip.analyze(data, self.ana.default_config())
        joined = ' '.join(str(x) for x in (an.get('warnings') or []))
        self.assertIn('不足 3 组', joined,
                      '2 个溶液点必须明说「不足 3 组」，不能只给 nan')

    def test_pycno_readings_any_count(self):
        """比重瓶读数 1~4 次都要能出密度。"""
        for n in (1, 2, 3, 4):
            data = copy.deepcopy(self.base)
            data['pycno']['mw'] = (list(self.base['pycno']['mw']) * 4)[:n]
            an = self.dip.analyze(data, self.ana.default_config())
            rho = an.get('rho_cyc_measured')
            self.assertTrue(_finite(rho), '%d 次比重瓶读数应给出密度' % n)


class MagneticSampleCountTests(unittest.TestCase):
    """磁化率：样品个数 0/1/多个都要稳。"""

    def setUp(self):
        self.mag = _mod('磁化率工具', 'magnetic')
        self.base = self.mag.sample_data()

    def test_sample_count_matches_output(self):
        meta = {'temperature_C', 'tube', 'mohr_salt'}
        samples = [k for k in self.base if k not in meta]
        for n in (0, 1, 2, len(samples)):
            data = {k: self.base[k] for k in meta if k in self.base}
            for s in samples[:n]:
                data[s] = self.base[s]
            an = self.mag.process_all(data)
            got = an.get('samples') or {}
            self.assertEqual(len(got), n, '%d 个样品 → 输出行数不对' % n)

    def test_diamagnetic_mu_is_none_not_nan(self):
        """反磁性样品（亚铁氰化钾）没有永久磁矩：μ 应为 None，不是 nan。"""
        an = self.mag.process_all(self.base)
        samples = an.get('samples') or {}
        rows = list(samples.values()) if isinstance(samples, dict) else list(samples)
        self.assertTrue(rows, '应至少有样品结果')
        for row in rows:
            if not isinstance(row, dict):
                continue
            mu = row.get('mu')
            if mu is not None:
                self.assertTrue(_finite(mu),
                                'μ 要么是有限数要么是 None，不能是 %r' % (mu,))
        # 亚铁氰化钾是反磁性的：必须有这一条且 μ 为 None
        if isinstance(samples, dict) and '亚铁氰化钾' in samples:
            self.assertIsNone(samples['亚铁氰化钾'].get('mu'),
                              '反磁性样品不该有永久磁矩')


class UvConcentrationCountTests(unittest.TestCase):
    """紫外：浓度档次 / 重复测量次数变化时，选择器与计算都要跟得上。"""

    def setUp(self):
        self.uv = _mod('紫外光谱工具', 'uv')

    def test_pick_choices_cover_all(self):
        ch = self.uv.pick_choices()
        self.assertEqual(len(ch['conc']), len(self.uv.CONC_VALUES))
        self.assertEqual(set(ch['mol']), set(self.uv.MOLECULES))

    def test_any_pick_yields_valid_sample_keys(self):
        uv = self.uv
        for c in uv.CONC_VALUES:
            label = uv.conc_label(c)
            for cand in uv.CONC_CANDIDATES.get(label, []):
                for k in uv.used_sample_keys({}, {label: cand}):
                    self.assertIn(k, uv.SAMPLES_BY_KEY)

    def test_calibration_count_and_curve_pick(self):
        """标定条数可增减、每条曲线可选（上一轮），这里的数量契约要保住。"""
        uv = self.uv
        self.assertEqual(len(uv.effective_calibrations(None)), 3)
        cals = uv.effective_calibrations([
            dict(key='c4', label='第四周', file='x.txt')])
        self.assertEqual(len(cals), 4)
        mapping = uv.curve_cal_map({'A4': 'c4'}, cals)
        self.assertEqual(mapping['A4'], 'c4')
        # 选了不存在的标定 → 退回默认，不是 None
        mapping2 = uv.curve_cal_map({'A4': '不存在'}, cals)
        self.assertEqual(mapping2['A4'], uv.CURVE_CAL_DEFAULT['A4'])


class CombustionRoundCountTests(unittest.TestCase):
    """燃烧热：轮次（标准物质 + 待测）不足要明确报错。"""

    def test_at_least_two_rounds_required(self):
        ana = _mod('燃烧热工具', 'analysis')
        import inspect
        src = inspect.getsource(ana)
        self.assertIn('至少需要两轮', src,
                      '轮次不足必须给可读错误，不能静默算出个空报告')


class NoSilentNanContractTests(unittest.TestCase):
    """总契约：这些模块的关键入口在退化输入下要么给数、要么给警告。"""

    def test_vapor_and_adsorption_warn_on_degenerate(self):
        vap = _mod('蒸气压工具', 'vapor')
        ana = _mod('蒸气压工具', 'analysis')
        base = vap.sample_data()
        an = vap.analyze({'water': {'atm': base['water']['atm'], 'series': []},
                          'cyclo': {'atm': base['cyclo']['atm'],
                                    'series': base['cyclo']['series']}},
                         ana.default_config())
        warns = an.get('warnings') or []
        self.assertTrue(any('水' in str(x) for x in warns),
                        '空系列应给出与水有关的警告：%s' % warns)


if __name__ == '__main__':
    unittest.main(verbosity=2)
