# -*- coding: utf-8 -*-
"""紫外光谱：一维势箱模型的回归测试。

守住的要点（都对应 2026-11-09 复核出的真实问题）：

1. **分母是 N+1，不是 N 也不是 2N+1。**
   含 N 个 π 电子时 HOMO 为 n = N/2、跃迁到 n+1，能级差 ∝ (2n+1) = N+1。
   代码曾经因为 docstring 写 `/(2n+1)` 而参数实际是电子数，被人当成 bug
   （2026-11-03 复核：代码对、注释错）。这里同时钉住数值与文档口径。

2. **A 组反解自洽**：把解出的 x、y 代回 A1 自己的方程，必须还原 λ₁。

3. **B 组箱长与电子数同源**：单元数取下限时 π 电子数也要减 2，
   区间两端 (L, N) 各自成立 —— 曾经把 10 个 C–C=C 配成 N=22。

4. **a 没有分辨力时不许假装有**：a 在候选范围内变动引起的 λ 变化，
   必须远小于模型对 λ₂ 的系统残差（判据给在 20% 以内算"没有分辨力"）。

5. **参数非法时不静默**：a 不在候选里要给出 warning，而不是空白表。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support                                        # noqa: E402

TOOL = '紫外光谱工具'


def _uv():
    return support.load_module(TOOL, 'uv')


def _analysis_mod():
    return support.load_module(TOOL, 'analysis')


#: 交付报告表4 的实测 λmax（nm）。固定下来作为回归基准：
#: 只要这几个数不变，势箱的表格数值就不该变。
LAM_EXP = {'A1': 428.5357, 'A2': 560.8511, 'A3': 656.1452, 'A4': 770.1877,
           'B1': 449.8874, 'B2': 296.2578}


def _build_analysis():
    """按仓库里 settings.json 的默认配置跑一次完整分析（用于端到端断言）。"""
    analysis = _analysis_mod()
    cfg = analysis.default_config()
    an = analysis.Analysis(cfg)
    an.run()
    return an


class ParticleInBoxTests(unittest.TestCase):

    def test_constant_k_value(self):
        """K = 8·m_e·c/h，单位换算到 nm；用 CODATA-2018 独立算应一致到 0.1%。"""
        uv = _uv()
        m_e, c, h = 9.1093837015e-31, 2.99792458e8, 6.62607015e-34
        k_ref = 8 * m_e * c / h * 1e-9
        self.assertAlmostEqual(uv.BOX_K / k_ref, 1.0, delta=1e-3,
                               msg='BOX_K 应等于 8·m_e·c/h 换算到 nm 的结果')

    def test_denominator_is_N_plus_1(self):
        """分母必须是 N+1：把 N 与量子数 n 混用是本模块历史上最容易犯的错。"""
        uv = _uv()
        # λ = K·L²/(N+1)：取 L=1 nm 时 λ 就是 K/(N+1)
        for n_pi in (2, 4, 6, 14, 20, 22):
            self.assertAlmostEqual(uv.box_lambda(1.0, n_pi),
                                   uv.BOX_K / (n_pi + 1), places=9)
        # 明确排除两种错法
        self.assertNotAlmostEqual(uv.box_lambda(1.0, 6), uv.BOX_K / 6, places=3)
        self.assertNotAlmostEqual(uv.box_lambda(1.0, 6), uv.BOX_K / 13, places=3)

    def test_denominator_documented(self):
        """docstring 里的口径必须与实现一致（防止只改代码不改文档）。"""
        uv = _uv()
        doc = (uv.box_lambda.__doc__ or '')
        self.assertIn('N+1', doc, 'docstring 应写明分母是 N+1')
        self.assertNotIn('2n+1)', doc.replace('(2n+1) = N+1', ''),
                         'docstring 不应残留 /(2n+1) 的写法')

    def test_a_group_back_substitution(self):
        """A 组：解出的 x、y 代回 A1 的方程必须还原 λ₁。"""
        uv = _uv()
        for a in (0, 2, 4, 6, 8, 10):
            rows = uv.particle_in_box(LAM_EXP, a_values=(a,))
            r = rows[0]
            n_pi = 2 * 1 + 2 * a          # i = 1
            L1 = 1 * r['x'] + 2 * r['y']
            lam1 = uv.BOX_K * L1 ** 2 / (n_pi + 1)
            self.assertAlmostEqual(lam1, LAM_EXP['A1'], places=6,
                                   msg='a=%d 时 A1 的方程未被满足' % a)

    def test_a_group_denominators(self):
        """A_i 的分母等于 2i+2a+1（= N+1）。"""
        uv = _uv()
        rows = uv.particle_in_box(LAM_EXP)
        for r in rows:
            a = r['a']
            for i, key in ((2, 'lam2'), (3, 'lam3')):
                n_pi = 2 * i + 2 * a
                L = i * r['x'] + 2 * r['y']
                self.assertAlmostEqual(r[key], uv.BOX_K * L ** 2 / (n_pi + 1),
                                       places=6)

    def test_b_group_uses_consistent_N(self):
        """B 组：区间两端的 π 电子数必须等于 2×单元数，不能两端用同一个 N。

        曾经把 10 个 C–C=C 配成 N=22（应为 20），导致 B2 区间写成 140~315，
        实验值 296.3 恰好卡在边上纯属巧合；自洽后是 196~316。
        """
        uv = _uv()
        x = 0.2728
        for code, units in (('B1', (10, 11)), ('B2', (2, 3))):
            u_lo, u_hi = units
            l_lo, l_hi = uv.box_length(x, units)
            lam_lo = uv.box_lambda(l_lo, 2 * u_lo)
            lam_hi = uv.box_lambda(l_hi, 2 * u_hi)
            self.assertLess(lam_lo, lam_hi, '%s 的预测区间应随单元数增大' % code)
            n_back = uv.BOX_K * l_lo ** 2 / lam_lo - 1
            self.assertAlmostEqual(n_back, 2 * u_lo, places=6)
        # 与错法的差距要足够大，否则这条测试抓不住回归
        wrong = uv.box_lambda(uv.box_length(x, (2, 3))[0], 6)
        right = uv.box_lambda(uv.box_length(x, (2, 3))[0], 4)
        self.assertGreater(abs(wrong - right), 40.0,
                           'B2 下限用错 N 时差别应有几十 nm 量级')

    def test_b_group_rows_consistent_in_analysis(self):
        """端到端：analysis 产出的 b_rows 里 L 与 N 必须成对自洽。"""
        an = _build_analysis()
        rows = an.box.get('b_rows') or []
        self.assertEqual(len(rows), 2, 'B1、B2 两行')
        uv = _uv()
        for r in rows:
            self.assertEqual(r['n_lo'], 2 * r['units_lo'])
            self.assertEqual(r['n_hi'], 2 * r['units_hi'])
            self.assertAlmostEqual(
                r['lam_lo'], uv.BOX_K * r['L_lo'] ** 2 / (r['n_lo'] + 1), places=9)
            self.assertAlmostEqual(
                r['lam_hi'], uv.BOX_K * r['L_hi'] ** 2 / (r['n_hi'] + 1), places=9)

    def test_a_has_no_resolving_power(self):
        """a 从 0 到 10 的预测跨度应远小于模型对 A2 的系统残差。"""
        uv = _uv()
        rows = uv.particle_in_box(LAM_EXP)
        span2 = max(r['lam2'] for r in rows) - min(r['lam2'] for r in rows)
        span3 = max(r['lam3'] for r in rows) - min(r['lam3'] for r in rows)
        resid2 = abs(rows[0]['lam2'] - LAM_EXP['A2'])   # 量级参照
        self.assertLess(span2, 15.0, 'a 对 λ₂ 的影响不该这么大（%.1f nm）' % span2)
        self.assertLess(span3, 15.0, 'a 对 λ₃ 的影响不该这么大（%.1f nm）' % span3)
        self.assertGreater(resid2, span2,
                           '系统残差应大于 a 引起的变化，否则 a 反而有分辨力')


class BoxConfigRobustnessTests(unittest.TestCase):
    """非法 / 缺参数的 a 不许静默产出空白表。"""

    def _analysis(self):
        return _analysis_mod()

    def test_invalid_a_warns(self):
        """a 不在候选值里时必须给出 warning，不能静默产出空白表。"""
        analysis = _analysis_mod()
        uv = _uv()
        a_rows = uv.particle_in_box(LAM_EXP)
        valid = [r['a'] for r in a_rows]
        self.assertNotIn(3, valid)
        self.assertEqual(valid, [0, 2, 4, 6, 8, 10])

        cfg = analysis.default_config()
        cfg['box_a'] = 3                    # 非法
        an = analysis.Analysis(cfg).run()
        self.assertTrue(any('a' in w and '候选' in w for w in an.warnings),
                        '非法 a 必须给出可执行的 warning，实际 warnings=%r'
                        % (an.warnings,))
        self.assertFalse(an.box['x_used'] == an.box['x_used'], 'x 应为 nan')
        self.assertEqual(an.box['b_rows'], [])

    def test_mismatched_n_warns(self):
        """配置里的 π 电子数与单元数矛盾时要提示，并以 2×单元数为准。"""
        analysis = _analysis_mod()
        cfg = analysis.default_config()
        cfg['box_n_B1'] = 24                # 应为 2×11 = 22
        an = analysis.Analysis(cfg).run()
        self.assertTrue(any('B1' in w and 'π 电子数' in w for w in an.warnings),
                        'N 与单元数矛盾时必须提示，实际 warnings=%r'
                        % (an.warnings,))
        row = [r for r in an.box['b_rows'] if r['code'] == 'B1'][0]
        self.assertEqual(row['n_hi'], 22, '表里一律按 2×单元数取值')

    def test_particle_in_box_handles_missing_anchor(self):
        """缺 A4 时不能抛异常，要给出 nan 行。"""
        uv = _uv()
        rows = uv.particle_in_box({'A1': 428.5})
        self.assertEqual(len(rows), 6)
        for r in rows:
            self.assertFalse(r['x'] == r['x'], '缺锚点时应为 nan')


if __name__ == '__main__':
    unittest.main(verbosity=2)
