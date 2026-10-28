# -*- coding: utf-8 -*-
"""11 个模块的数值基准 + 生成报告的结构审计。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from audit_docx import audit_docx
from module_cases import build_cases, generate_report
from support import load_module


class ModuleRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases, cls.build_errors = build_cases()

    def case(self, label):
        if label not in self.cases:
            exc = self.build_errors.get(label)
            self.skipTest('%s 基准数据不可用：%s' % (label, exc))
        return self.cases[label]

    def close(self, actual, expected, rtol=2e-3, label=''):
        if expected == 0:
            self.assertAlmostEqual(actual, 0.0, places=12, msg=label)
            return
        rel = abs(float(actual) - float(expected)) / abs(float(expected))
        self.assertLessEqual(rel, rtol,
                             '%s: %.10g != %.10g（相对差 %.2g）'
                             % (label, actual, expected, rel))

    # ------------------------------------------------------------ 数值基准
    def test_chemical_kinetics(self):
        an = self.case('化学动力学').an
        group = next(g for g in an['groups'] if g['label'] == '4M')
        self.close(group['k1'], 0.00110116, label='k1(4M)')
        self.close(group['sigma_k1'], 7.65e-06, rtol=0.02, label='σk1(4M)')
        self.close(group['t_half'], 629.4727, label='t1/2(4M)')
        self.close(group['fits']['1']['r2'], 0.99922773, rtol=1e-5, label='r2')
        self.assertEqual(an['order']['best'], 1)
        self.close(an['rate_law']['n'], 1.9342952, rtol=2e-3, label='n(H+)')

    def test_vapor_pressure(self):
        an = self.case('蒸气压').an
        water, cyclo = an['water']['fit'], an['cyclo']['fit']
        for key, expected in (('A', 4969.6484), ('B', 13.29438),
                              ('tb', 374.17927), ('dh_kJ', 41.317656),
                              ('ds', 110.42209)):
            self.close(water[key], expected, label='water.' + key)
        for key, expected in (('A', 3823.6804), ('B', 10.839772),
                              ('tb', 353.16629), ('dh_kJ', 31.790079),
                              ('ds', 90.014475)):
            self.close(cyclo[key], expected, label='cyclo.' + key)
        self.assertEqual(an['warnings'], [])

    def test_phase_diagram(self):
        an = self.case('双液系').an
        self.close(an['curve']['fit']['r2'], 0.99955555, rtol=1e-5, label='R2')
        self.close(an['azeotrope']['w'], 0.30576065, label='azeotrope w')
        self.close(an['azeotrope']['sigma_w'], 0.0144319, rtol=2e-3,
                   label='sigma_w')
        self.assertEqual(an['mode'], 'ratio')

    def test_dipole_moment(self):
        an = self.case('偶极矩').an
        for key, expected in (('a', 2.7505005), ('eps1', 1.9590845),
                              ('b', 0.01671356), ('rho1', 0.77790199),
                              ('P_inf', 79.472504), ('mu', 1.6627369),
                              ('s_mu', 0.03154062)):
            self.close(an[key], expected, label=key)

    def test_surface_adsorption(self):
        an = self.case('表面吸附').an
        bubble, plate = an['bubble'], an['plate']
        self.close(bubble['gamma_inf'], 5.82e-06, rtol=5e-3, label='bubble Γ∞')
        self.close(bubble['q'], 0.28546527, label='bubble q')
        self.close(bubble['fit']['r2'], 0.99942133, rtol=1e-5, label='bubble R2')
        self.close(plate['gamma_inf'], 4.53e-06, rtol=5e-3, label='plate Γ∞')
        self.close(plate['q'], 0.36673407, label='plate q')
        self.close(an['comparison']['d_gamma'], -1.29e-06, rtol=0.02,
                   label='ΔΓ∞')

    def test_surface_adsorption_tables(self):
        """数据表导出（xlsx / csv）的表结构，防止改动内核后列错位。"""
        case = self.case('表面吸附')
        exportdata = load_module('表面吸附工具', 'exportdata')
        tabs = exportdata.tables(case.an)
        self.assertEqual([t[0] for t in tabs],
                         ['说明', '结果', '最大气泡法', '吊片法',
                          '零点与纯水', '浓度修正'])
        heads = {name: hdr for name, hdr, _ in tabs}
        self.assertEqual(heads['最大气泡法'][0], 'c /(mol·dm⁻³)')
        self.assertIn('h_r 来源', heads['最大气泡法'])
        rows = {name: rows for name, _, rows in tabs}
        self.assertEqual(rows['结果'][0][0], '最大气泡压力法')
        self.assertEqual(rows['结果'][1][0], '吊片法')
        self.assertEqual(rows['零点与纯水'][0][0], '压力计零点')

        with tempfile.TemporaryDirectory() as tmp:
            xp, cp = Path(tmp) / 'a.xlsx', Path(tmp) / 'a.csv'
            exportdata.write(case.an, str(xp), 'xlsx')
            exportdata.write(case.an, str(cp), 'csv')
            self.assertEqual(xp.read_bytes()[:2], b'PK')      # 真 xlsx（zip 包）
            self.assertGreater(xp.stat().st_size, 5000)
            text = cp.read_text(encoding='utf-8-sig')
            self.assertIn('最大气泡法', text)
            self.assertIn('吊片法', text)

    def test_surface_adsorption_repeat_n(self):
        """两种方法各自设平行次数：n 只影响自己那一半，导出列数跟着走。"""
        adsorption = load_module('表面吸附工具', 'adsorption')
        analysis = load_module('表面吸附工具', 'analysis')
        exportdata = load_module('表面吸附工具', 'exportdata')
        d = adsorption.sample_data()
        d['bubble'] = [dict(r,
                            left=list(r['left']) + [r['left'][-1] + 0.01,
                                                    r['left'][-1] - 0.01],
                            right=list(r['right']) + [r['right'][-1] - 0.01,
                                                      r['right'][-1] + 0.01])
                       for r in d['bubble']]
        d['plate'] = [dict(r, gamma=list(r['gamma'])[:2]) for r in d['plate']]
        cfg = analysis.default_config()
        cfg['repeat_n_bubble'] = 5
        cfg['repeat_n_plate'] = 2
        an = adsorption.analyze(d, cfg)
        self.assertEqual(an['bubble']['repeat_n'], 5)
        self.assertEqual(an['bubble']['rows'][0]['left']['n'], 5)
        self.assertEqual(an['plate']['repeat_n'], 2)
        self.assertEqual(an['plate']['rows'][0]['stats']['n'], 2)
        sheets = {n: h for n, h, _ in exportdata.tables(an)}
        self.assertIn('h_l5 /cm', sheets['最大气泡法'])
        self.assertIn('h_r5 /cm', sheets['最大气泡法'])
        self.assertIn('γ2 /(mN·m⁻¹)', sheets['吊片法'])
        self.assertNotIn('γ3 /(mN·m⁻¹)', sheets['吊片法'])

    def test_surface_adsorption_repeat_n_legacy(self):
        """旧 settings 只有一个 repeat_n，升级后应拆给两个方法。"""
        analysis = load_module('表面吸附工具', 'analysis')
        cfg = analysis.default_config_with_saved({'repeat_n': 4})
        self.assertEqual(cfg['repeat_n_bubble'], 4)
        self.assertEqual(cfg['repeat_n_plate'], 4)
        cfg2 = analysis.default_config_with_saved(
            {'repeat_n': 4, 'repeat_n_plate': 2})
        self.assertEqual(cfg2['repeat_n_bubble'], 4)
        self.assertEqual(cfg2['repeat_n_plate'], 2)

    def test_surface_adsorption_single_reading(self):
        """只测一次：n=1，σ 退化成纯仪器项，导出只有一列。"""
        adsorption = load_module('表面吸附工具', 'adsorption')
        analysis = load_module('表面吸附工具', 'analysis')
        exportdata = load_module('表面吸附工具', 'exportdata')
        d = adsorption.sample_data()
        d['zero'] = {'left': [21.80], 'right': [22.00]}
        d['water_bubble'] = {'left': [17.66], 'right': [26.36]}
        d['bubble'] = [dict(r, left=list(r['left'])[:1], right=list(r['right'])[:1])
                       for r in d['bubble']]
        d['plate'] = [dict(r, gamma=list(r['gamma'])[:1]) for r in d['plate']]
        cfg = analysis.default_config()
        cfg['repeat_n_bubble'] = 1
        cfg['repeat_n_plate'] = 1
        an = adsorption.analyze(d, cfg)
        self.assertEqual(an['bubble']['repeat_n'], 1)
        self.assertEqual(an['bubble']['zero']['left']['n'], 1)
        # 单次：标准误差为 0，σ 就是仪器读数误差
        self.assertAlmostEqual(an['bubble']['zero']['left']['sigma'], 0.02, places=9)
        self.assertAlmostEqual(an['plate']['rows'][0]['stats']['sigma'], 0.01, places=9)
        sheets = {n: h for n, h, _ in exportdata.tables(an)}
        self.assertIn('h_l1 /cm', sheets['最大气泡法'])
        self.assertNotIn('h_l2 /cm', sheets['最大气泡法'])
        self.assertNotIn('γ2 /(mN·m⁻¹)', sheets['吊片法'])

    def test_magnetic_susceptibility(self):
        an = self.case('磁化率').an
        self.close(an['chi_std'], 4.0242886e-07, label='chi_std')
        cuso4 = an['samples']['硫酸铜']
        self.close(cuso4['mu'], 1.0287810, label='CuSO4 μ')
        self.close(cuso4['n'], 0.43470915, label='CuSO4 n')
        self.assertIsNone(an['samples']['亚铁氰化钾']['mu'])
        self.assertIsNone(an['samples']['未知样']['chi_m'])

    def test_conductivity(self):
        an = self.case('电导率').an
        for key, expected in (('NaNO3', 0.012144), ('NaAc', 0.00911507),
                              ('HNO3', 0.0428627)):
            self.close(an.fits[key]['lam_inf'], expected, label=key)
        self.close(an.esa['lam_inf'], 0.0398338, label='Λm∞(HAc)')
        self.close(an.esa['sigma'], 0.00075, rtol=0.02, label='σ(HAc)')
        self.close(an.kmean['mean'], 1.4344265e-05, label='K mean')
        self.close(an.kfit['K'], 1.7870724e-05, label='K fit')
        self.close(an.kfit['r'], 0.99991435, rtol=1e-6, label='K fit r')
        self.assertEqual(an.warnings, [])

    def test_electrochemistry(self):
        an = self.case('电化学').an
        self.close(an.esa['area_mm2'], 1.3156314, label='ESA')
        self.close(an.dmfc['P_max'], 3.1927896e-07, label='Pmax')
        self.close(an.dmfc['E_at_Pmax'], 0.18361794, label='E(Pmax)')
        self.assertEqual(an.orr['onset_red'], 0.517)
        self.assertEqual(an.orr['onset_ox'], 0.595)
        self.assertEqual(an.mor['onset'], 0.248)
        self.assertEqual(an.warnings, [])

    def test_uv_spectrum(self):
        an = self.case('紫外').an
        for key, expected in (('A1', 428.53567), ('A2', 560.85106),
                              ('A3', 655.89487), ('A4', 770.18773),
                              ('B1', 449.88736), ('B2', 296.25782)):
            self.close(an.box['lambdas'][key], expected, label=key)
        self.close(an.beer['fit']['eps'], 43297.19984, label='epsilon')
        self.close(an.beer['fit']['r2'], 0.99880146, rtol=1e-5, label='Beer R2')
        self.close(an.cals['d1_long']['r2'], 0.99992434, rtol=1e-6,
                   label='calibration R2')
        self.assertEqual(an.warnings, [])

    def test_combustion(self):
        an = self.case('燃烧热').an
        self.close(an.W, 4225.4519, label='W')
        self.close(an.sigma_W, 29.332786, rtol=0.02, label='sigma W')
        self.assertEqual(len(an.rounds), 2)
        standard, sample = an.rounds
        self.close(standard['dT'], 1.3267450, label='standard dT')
        self.close(sample['dT'], 2.0129593, label='sample dT')
        self.close(sample['Qv_per_gram'], 16859.486, label='Qv/g')

    def test_dissolution(self):
        an = self.case('溶解热').an
        self.assertEqual(len(an.rounds), 6)
        self.close(an.fit['Qs0'], 38.931963, label='Qs0')
        self.close(an.fit['a'], 0.25582814, label='a')
        self.close(an.fit['r_square'], 0.97501810, rtol=1e-5, label='R2')
        self.close(an.rounds[0]['Qs'], 38.144946, label='Qs(1)')
        self.close(an.rounds[-1]['Qs'], 36.139364, label='Qs(6)')

    # ------------------------------------------------------------ 结构审计
    def test_all_reports_generate_and_audit(self):
        for label in sorted(self.cases):
            with self.subTest(module=label):
                case = self.cases[label]
                with tempfile.TemporaryDirectory() as td:
                    out = generate_report(case, td)
                    self.assertTrue(out.exists(), label)
                    self.assertGreater(out.stat().st_size, 100_000, label)
                    issues = audit_docx(out)
                    errors = [i for i in issues if i.level == 'ERROR']
                    self.assertEqual(
                        [str(i) for i in errors], [],
                        '%s 的报告有结构错误' % label)


if __name__ == '__main__':
    unittest.main()
