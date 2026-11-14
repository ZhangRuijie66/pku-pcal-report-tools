# -*- coding: utf-8 -*-
"""化学动力学：读数文件按**类型**分流（动态 / 静态 / 标定表）。

守的是 2026-11-10 用户报的那个静默错数：

    「动力学导入逻辑没对……导入错将步数导入为角度了」

根因是 Polariputer 两种 xlsx 的列结构完全不同——

    动态测量：index, time, steps, angle, …, 实验参数   → 时间序列
    静态测量：index, steps, angle                      → 同一份样品的重复读数

而旧解析器**不看类型**：`parse_calibration_xlsx` 找不到 c/alpha 表头就走
「取前两列数字」的兜底，于是 index 当浓度、steps 当角度（steps=−3292 印成
α=−3292°）；`parse_polariputer_xlsx` 也把静态文件按 `[r[1], r[-1]]` 解析成
[steps, angle]，整条动力学曲线的时间轴变成步数。

这类缺陷不报错、不崩溃，只是安静地印出一份看起来正常的错报告，
所以断言必须落在**数值**上，不能只断言「没抛异常」。
"""
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support                                        # noqa: E402

import numpy as np                                    # noqa: E402
import openpyxl                                       # noqa: E402

TOOL = '化学动力学工具'


def _k():
    return support.load_module(TOOL, 'kinetics')


def _kinds():
    m = _k()
    return m.KIND_DYNAMIC, m.KIND_STATIC, m.KIND_CALIB, m.KIND_UNKNOWN


def make_xlsx(rows, header=True):
    """把行写成内存里的 xlsx 字节流（第一个 sheet）。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    if header and rows:
        ws.append(list(rows[0]))
        rows = rows[1:]
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


#: 用户真实数据的形状（张瑞杰 无穷.xlsx，静态 10 次读数，steps/angle 恒为 746 倍）
STATIC_ROWS = [('index', 'steps', 'angle'),
               (1, -3292, -4.412868499755859),
               (2, -3301, -4.424932956695557),
               (3, -3286, -4.404825687408447),
               (4, -3289, -4.408847332000732),
               (5, -3301, -4.424932956695557)]

#: 动态测量的形状（第一次测量.xlsx 前几行）
DYNAMIC_ROWS = [('index', 'time', 'steps', 'angle', None, '实验参数', None),
                (1, 282.4392322, 898, 1.2037533521652222, None, None, None),
                (2, 309.3515106, 525, 0.7037533521652222, None,
                 '实验温度 (°C)', 30),
                (3, 339.5586955, 152, 0.20375335216522217, None,
                 '蔗糖浓度', 0.1),
                (4, 373.0089515, -221, -0.29624664783477783, None,
                 '盐酸浓度', 3.02)]

#: c–α 标定表
CAL_ROWS = [('c', 'alpha'),
            (0.005, 0.87), (0.0104, 1.51), (0.025, 3.45), (0.0504, 6.88)]


class TestKindDetection(unittest.TestCase):
    def test_static_detected_not_dynamic(self):
        """静态文件必须判成 static，且 steps 绝不能出现在 points 里。"""
        K_DYN, K_STA, _, _ = _kinds()
        res = _k().parse_measurement_xlsx(make_xlsx(STATIC_ROWS), stem='无穷')
        self.assertEqual(res['kind'], K_STA)
        self.assertEqual(res['points'], [])          # 不是时间序列
        self.assertEqual(res['alpha']['n'], 5)
        self.assertAlmostEqual(res['alpha']['mean'], -4.4152814865, places=6)
        # 步数只能进 steps 诊断字段，绝不能当角度
        self.assertIsNotNone(res['steps'])
        self.assertAlmostEqual(res['steps']['mean'], -3293.8, places=6)

    def test_dynamic_detected(self):
        K_DYN, _, _, _ = _kinds()
        res = _k().parse_measurement_xlsx(make_xlsx(DYNAMIC_ROWS), stem='第一次测量')
        self.assertEqual(res['kind'], K_DYN)
        self.assertEqual(len(res['points']), 4)
        self.assertAlmostEqual(res['points'][0][0], 282.4392322, places=6)
        self.assertAlmostEqual(res['points'][0][1], 1.2037533521652222, places=12)
        # 侧栏参数要认出来
        self.assertAlmostEqual(res['temperature'], 30.0)
        self.assertAlmostEqual(res['sucrose'], 0.1)
        self.assertAlmostEqual(res['acid'], 3.02)

    def test_calibration_table_detected(self):
        _, _, K_CAL, _ = _kinds()
        res = _k().parse_measurement_xlsx(make_xlsx(CAL_ROWS))
        self.assertEqual(res['kind'], K_CAL)
        self.assertEqual(len(res['rows']), 4)
        self.assertAlmostEqual(res['rows'][0]['c'], 0.005)
        self.assertAlmostEqual(res['rows'][0]['alpha'], 0.87)

    def test_unknown_header_is_unknown_not_guessed(self):
        """认不出表头就返回 unknown——绝不按列序号猜。"""
        _, _, _, K_UNK = _kinds()
        rows = [('foo', 'bar'), (1, 2), (3, 4)]
        res = _k().parse_measurement_xlsx(make_xlsx(rows))
        self.assertEqual(res['kind'], K_UNK)
        self.assertEqual(res['points'], [])
        self.assertEqual(res['rows'], [])
        self.assertTrue(res['warnings'])


class TestOldBugRegression(unittest.TestCase):
    """把修好之前的两条错误路径钉死。"""

    def test_calibration_xlsx_does_not_take_first_two_columns(self):
        """旧 bug 1：静态文件导标定表 → index 当 c、steps 当 α。"""
        rows = _k().parse_calibration_xlsx(make_xlsx(STATIC_ROWS))
        self.assertEqual(rows, [],
                         '静态读数没有 c 列，不能当成标定表；'
                         '旧代码会把 index/steps 当 c/alpha')

    def test_parse_points_rejects_static_header(self):
        """旧 bug 2：静态文本按 r[1],r[-1] 取 → 时间为 steps。"""
        text = '\n'.join('%d %d %.4f' % r for r in STATIC_ROWS[1:])
        pts = _k().parse_points('index steps angle\n' + text)
        self.assertEqual(pts, [], '带 steps 没有 time 的表头是静态读数，'
                                  '不能解析成时间序列')

    def test_polariputer_points_empty_for_static(self):
        """parse_polariputer_xlsx 遇到静态文件不再吐出 [steps, angle]。"""
        res = _k().parse_polariputer_xlsx(make_xlsx(STATIC_ROWS))
        self.assertEqual(res['points'], [])
        self.assertEqual(res['kind'], _kinds()[1])


class TestConcentrationHint(unittest.TestCase):
    """浓度只能从文件名猜，且必须「唯一、明确」——猜错会改掉整条标定直线。"""

    def setUp(self):
        self.f = _k().concentration_hint

    def test_simple_names(self):
        self.assertAlmostEqual(self.f('0.0412'), 0.0412)
        self.assertAlmostEqual(self.f('蔗糖0.01'), 0.01)
        self.assertAlmostEqual(self.f('0.1蔗糖'), 0.1)
        self.assertAlmostEqual(self.f('0.02g mL 蔗糖'), 0.02)
        # 带单位片段的名字要先剥单位再数数字：蔗糖0.05g L-1 是 0.05，不是「0.05 和 1」
        self.assertAlmostEqual(self.f('蔗糖0.05g L-1'), 0.05)
        self.assertAlmostEqual(self.f('0.005g'), 0.005)
        self.assertAlmostEqual(self.f('0.02g/mL'), 0.02)
        # 1.4927 超过 0.5 g·mL⁻¹ 的合理上限 → 不猜
        self.assertIsNone(self.f('1.4927-50ml'))

    def test_rejects_non_sample_names(self):
        # 文件名里带这些词的文件本来就不是「某个浓度的样品」
        for name in ('无穷', 'alpha无穷', '0.2 完全反应', '去离子水', '旋光零点',
                     'water'):
            self.assertIsNone(self.f(name), name)

    def test_rejects_ambiguous_numbers(self):
        # 两个数字（浓度 + 酸浓度/体积）→ 不猜，让用户手填
        for name in ('0.15-2', '0.1 酸2', '0.0412 1', '蔗糖0.1 酸5'):
            self.assertIsNone(self.f(name), name)


class TestServerImportRouting(unittest.TestCase):
    """server._import 必须按类型分流：静态文件进分组要**报错**，不能静默导入。"""

    @classmethod
    def setUpClass(cls):
        # ⚠ 每个工具的 server.py 都有 ``sys.path.insert(0, ROOT)`` +
        # ``from pcal import …``，导入它会把本工具的 pcal 以**裸包名**注册进
        # sys.modules；后面紫外的 server 再 ``from pcal import gcalc_bridge``
        # 就会拿到化学动力学的 pcal → ImportError。真实运行时一进程一模块，
        # 这是测试装载的坑，导入前后快照/还原即可（同 test_echem_assign）。
        cls._mods_before = set(sys.modules)
        cls.srv = support.load_module(TOOL, 'server')

    @classmethod
    def tearDownClass(cls):
        for name in [m for m in sys.modules if m not in cls._mods_before]:
            if name == 'pcal' or name.startswith('pcal.'):
                del sys.modules[name]

    def _post(self, kind, rows, filename):
        raw = make_xlsx(rows)
        return self.srv._import(kind, '', raw, filename)

    def test_static_into_group_raises(self):
        with self.assertRaises(Exception) as ctx:
            self._post('group', STATIC_ROWS, '无穷.xlsx')
        msg = str(ctx.exception)
        self.assertIn('静态', msg)
        self.assertIn('α∞', msg)          # 要告诉用户该往哪导

    def test_dynamic_into_group_ok(self):
        r = self._post('group', DYNAMIC_ROWS, '第一次测量.xlsx')
        self.assertTrue(r['ok'])
        self.assertEqual(r['count'], 4)
        self.assertAlmostEqual(r['points'][0][0], 282.4392322, places=6)
        self.assertAlmostEqual(r['acid'], 3.02)

    def test_dynamic_into_calibration_raises(self):
        with self.assertRaises(Exception) as ctx:
            self._post('calibration', DYNAMIC_ROWS, '第一次测量.xlsx')
        self.assertIn('动态', str(ctx.exception))

    def test_static_into_calibration_becomes_one_point(self):
        r = self._post('calibration', STATIC_ROWS, '0.0412.xlsx')
        self.assertTrue(r['ok'])
        self.assertEqual(r['mode'], 'point')
        self.assertAlmostEqual(r['point']['c'], 0.0412)
        self.assertAlmostEqual(r['point']['alpha'], -4.4152814865, places=6)
        self.assertEqual(r['point']['n'], 5)

    def test_static_into_calibration_without_c_still_reports_n(self):
        """文件名认不出浓度时也不能丢掉「读了几次」——界面要提示手填 c。"""
        r = self._post('calibration', STATIC_ROWS, '无穷.xlsx')
        self.assertTrue(r['ok'])
        self.assertEqual(r['mode'], 'point')
        self.assertIsNone(r['point']['c'])
        self.assertEqual(r['point']['n'], 5)

    def test_alpha_inf_import(self):
        r = self._post('alpha_inf', STATIC_ROWS, '无穷.xlsx')
        self.assertTrue(r['ok'])
        self.assertEqual(r['alpha']['n'], 5)
        self.assertAlmostEqual(r['alpha']['mean'], -4.4152814865, places=6)
        self.assertGreater(r['alpha']['sd'], 0)

    def test_calibration_table_import(self):
        r = self._post('calibration', CAL_ROWS, '标定.xlsx')
        self.assertTrue(r['ok'])
        self.assertEqual(r['mode'], 'table')
        self.assertEqual(r['count'], 4)


class TestReportRepeatCount(unittest.TestCase):
    """报告表 1 只示出平均值与重复次数（用户 2026-11-10 要求）。"""

    def test_analysis_keeps_n_and_sd(self):
        k = _k()
        data = k.sample_data()
        data['calibration'] = [{'c': 0.01, 'alpha': 1.5, 'n': 7, 'sd': 0.02},
                               {'c': 0.05, 'alpha': 6.9, 'n': 1, 'sd': None},
                               {'c': 0.10, 'alpha': 12.1, 'n': 12, 'sd': 0.01}]
        an = k.analyze(data, {})
        pts = an['calibration']['points']
        self.assertEqual([p['n'] for p in pts], [7, 1, 12])
        self.assertAlmostEqual(pts[0]['sd'], 0.02)
        self.assertIsNone(pts[1]['sd'])

    def test_single_reading_has_no_fake_spread(self):
        """n=1 时 sd 必须是 0（不编造离散度），且平均值就是那次读数。"""
        res = _k().parse_measurement_xlsx(
            make_xlsx([('index', 'steps', 'angle'), (1, 100, 1.2345)]))
        self.assertEqual(res['alpha']['n'], 1)
        self.assertEqual(res['alpha']['sd'], 0.0)
        self.assertAlmostEqual(res['alpha']['mean'], 1.2345, places=6)


class TestChemistrySanity(unittest.TestCase):
    """物理判据：一级反应的 ln(α−α∞)–t 必须比零级/二级更像直线。"""

    def test_first_order_wins_on_user_data_shape(self):
        k = _k()
        # 用解析式造一组严格一级的数据（k=8e-4 s⁻¹，α∞=−4.41，α0=14.8）
        import math
        import numpy as np
        ainf, a0, kk = -4.41, 14.8, 8.0e-4
        data = {'temperature_c': 30.0, 'sucrose_stock': 0.1,
                'alpha_inf_measured': ainf,
                'calibration': [{'c': 0.1, 'alpha': 13.4, 'n': 1},
                                {'c': 0.05, 'alpha': 6.7, 'n': 1}],
                'groups': [{'label': '4M', 'acid_nominal': 4.0,
                            'acid_true': 2.0, 'alpha_inf': None,
                            'exclude': [],
                            'data': [[t, ainf + (a0 - ainf) * math.exp(-kk * t)]
                                     for t in range(60, 1200, 60)]}]}
        an = k.analyze(data, {'alpha_inf_mode': 'measured',
                              'order_group': '4M'})
        self.assertEqual(an['order']['best'], 1)
        self.assertLess(abs(an['groups'][0]['k1'] - kk) / kk, 1e-6)



class AcidConcentrationTests(unittest.TestCase):
    """标称酸浓度 → 实际 c(H⁺) 换算（用户 2026-11-14 要求）。

    用户原话：「标称酸浓度和实际浓度之间是有 2 倍关系的，可以直接填写
    标称酸浓度换算成实际浓度」。核对 2025 课程数据：实际/标称 = 0.498~0.510，
    即浓度减半（与讲义「混合后又被蔗糖溶液稀释一倍」一致）。

    三条判据：
      1. 手填 acid_true 时行为**逐位不变**（不能因为加了换算而改数）；
      2. 只填标称值时按系数换算，且换算结果等价于原来的手填值；
      3. 两个都不填时明确告警，不静默当 0 参与拟合。
    """

    #: 导入内核前 sys.modules 的快照——用完必须还原。
    #: 每个工具的 ``pcal/server.py`` 都用裸包名 ``from pcal import …``，
    #: 一旦留在缓存里，后面紫外光谱的 ``from pcal import gcalc_bridge``
    #: 就会拿到动力学的 pcal 并抛 ImportError。单独跑一个文件看不出来，
    #: 全量跑才有 3 项 ERROR（tests/test_echem_assign.py 里记过同一个坑）。
    _mods_before = None

    def setUp(self):
        import sys
        from pathlib import Path
        repo = Path(__file__).resolve().parent.parent
        tool = repo / '化学动力学工具'
        if str(tool) not in sys.path:
            sys.path.insert(0, str(tool))
        type(self)._mods_before = set(sys.modules)
        from pcal import kinetics, analysis
        self.k = kinetics
        self.a = analysis

    def tearDown(self):
        """把本类导入时新出现的裸 ``pcal`` 及其子模块清掉。"""
        import sys
        before = type(self)._mods_before
        if not before:
            return
        for name in [m for m in sys.modules if m not in before]:
            if name == 'pcal' or name.startswith('pcal.'):
                del sys.modules[name]

    def _base(self):
        import copy
        return copy.deepcopy(self.k.sample_data())

    def _cfg(self, **kw):
        cfg = self.a.default_config()
        cfg.update(kw)
        return cfg

    def test_measured_value_wins(self):
        """手填 c(H⁺) 优先于换算。"""
        data = self._base()
        g = data['groups'][0]
        g['acid_nominal'] = 4.0
        g['acid_true'] = 9.99
        an = self.k.analyze(data, self._cfg())
        row = next(x for x in an['groups'] if x['label'] == g['label'])
        self.assertEqual(row['acid_eff'], 9.99)
        self.assertEqual(row['acid_source'], 'measured')

    def test_nominal_converted_by_ratio(self):
        """只填标称值时按系数换算。"""
        data = self._base()
        for g in data['groups']:
            g['acid_true'] = None
        an = self.k.analyze(data, self._cfg(acid_ratio=0.5))
        for row in an['groups']:
            self.assertEqual(row['acid_source'], 'nominal')
            self.assertAlmostEqual(row['acid_eff'], row['acid_nominal'] * 0.5)
        self.assertEqual(sorted(an['acid']['derived']),
                         sorted(g['label'] for g in an['groups']))

    def test_conversion_reproduces_measured_numbers(self):
        """用标称值换算，得到的 k1 应与原来手填真值一致（量级 + 相对差）。"""
        measured = self.k.analyze(self._base(), self._cfg())
        data = self._base()
        for g in data['groups']:
            g['acid_true'] = None
        derived = self.k.analyze(data, self._cfg(acid_ratio=0.5))

        by_label_m = {g['label']: g for g in measured['groups']}
        for row in derived['groups']:
            ref = by_label_m[row['label']]
            # 示例数据的真值不是精确的一半（0.498~0.510），允许 3% 偏差
            self.assertAlmostEqual(row['k1'], ref['k1'],
                                   delta=abs(ref['k1']) * 0.03,
                                   msg='%s 的 k1 差太多' % row['label'])

    def test_ratio_from_config_and_bad_values_fall_back(self):
        """系数可配；非法值退回默认 0.5。"""
        self.assertAlmostEqual(self.k.acid_ratio_of({'acid_ratio': 0.4}), 0.4)
        for bad in (None, '', 0, -1, 'abc', float('nan')):
            self.assertAlmostEqual(
                self.k.acid_ratio_of({'acid_ratio': bad}), 0.5,
                msg='非法系数 %r 应退回默认' % (bad,))

    def test_missing_both_warns_not_silent(self):
        """两个都不填 → source=missing、eff=None，且有明确警告（不静默当 0）。"""
        data = self._base()
        for g in data['groups']:
            g['acid_true'] = None
            g['acid_nominal'] = None
        an = self.k.analyze(data, self._cfg())
        self.assertTrue(all(g['acid_source'] == 'missing' for g in an['groups']))
        self.assertTrue(all(g['acid_eff'] is None for g in an['groups']))
        self.assertTrue(any('既没填标称酸浓度' in w for w in an['warnings']),
                        '缺少浓度时必须给出可读警告')
        self.assertIsNone(an['rate_law'],
                          '没有浓度就不该硬拟合速率方程')

    def test_sorting_uses_effective_concentration(self):
        """只填标称值时，组仍按 c(H⁺) 递增排列（否则表/正文对不上）。"""
        data = self._base()
        for g in data['groups']:
            g['acid_true'] = None
        data['groups'].reverse()          # 故意打乱录入顺序
        an = self.k.analyze(data, self._cfg())
        eff = [g['acid_eff'] for g in an['groups']]
        self.assertEqual(eff, sorted(eff), '各组应按 c(H⁺) 从小到大排列')

    def test_default_ratio_is_half(self):
        """默认系数就是 0.5（与讲义「稀释一倍」一致）。"""
        self.assertAlmostEqual(self.k.ACID_RATIO_DEFAULT, 0.5)
        self.assertAlmostEqual(self.a.default_config()['acid_ratio'], 0.5)
        self.assertIn('acid_ratio', self.a.PERSIST_KEYS)

if __name__ == '__main__':
    unittest.main()


class TestDegenerateFits(unittest.TestCase):
    """自由度 0 的非线性拟合：点估计照给，不确定度明确置空并说清原因。

    SKILL §27 强制项：**点估计与不确定度分开**——数量不够算不出 σ，
    不代表连值都给不出；但也绝不能把 None/inf 印成看起来正常的数字。
    """

    def test_three_points_three_params_has_no_sigma(self):
        k = _k()
        d = k.sample_data()
        d['groups'] = d['groups'][:3]          # 3 组数据 → 拟 3 个参数
        d['order_group'] = d['groups'][1]['label']
        an = k.analyze(d, {'alpha_inf_mode': 'measured',
                           'order_group': d['groups'][1]['label']})
        rl = an['rate_law']
        self.assertIsNotNone(rl, '3 组数据仍应给出点估计')
        self.assertEqual(rl['dof'], 0)
        self.assertFalse(rl['sigma_ok'])
        self.assertIsNone(rl['sigma_n'], 'σ 必须明确为 None，不能是 inf/nan')
        self.assertIsNone(rl['sigma_k0'])
        self.assertTrue(np.isfinite(rl['n']), 'n 的点估计必须仍然给出')
        self.assertIn('自由度', rl['note'])
        # 必须有一条人能看懂的告警，而不是静默
        self.assertTrue(any('自由度' in w for w in an['warnings']))

    def test_five_points_have_sigma(self):
        """组数够了就要给出 σ（不能一律置空）。"""
        k = _k()
        d = k.sample_data()
        an = k.analyze(d, {'alpha_inf_mode': 'measured', 'order_group': '4M'})
        rl = an['rate_law']
        self.assertTrue(rl['sigma_ok'])
        self.assertIsNotNone(rl['sigma_n'])
        self.assertTrue(np.isfinite(rl['sigma_n']))
        self.assertGreater(rl['dof'], 0)


class TestGroupOrdering(unittest.TestCase):
    """各组必须按 c(H⁺) 升序排列，否则正文「k₁ 单调增大」与表中数字矛盾。

    用户 2026-11-10 的真实数据按测量顺序是 3M、1M、2M：
    k₁ = 4.67e-3、8.41e-4、1.47e-3 —— 先降后升，正文却印「单调增大」。
    """

    def test_groups_sorted_by_acidity(self):
        k = _k()
        d = k.sample_data()
        # 故意打乱顺序（3M 在前、2M 其次、1M 最后）
        order = ['3M', '2M', '1M']
        d['groups'] = [g for lab in order for g in k.sample_data()['groups']
                       if g['label'] == lab]
        an = k.analyze(d, {'alpha_inf_mode': 'measured', 'order_group': '2M'})
        acids = [g['acid_true'] for g in an['groups']]
        self.assertEqual(acids, sorted(acids), '组必须按 c(H⁺) 升序')
        k1 = [g['k1'] for g in an['groups']]
        self.assertEqual(k1, sorted(k1), '排序后 k₁ 应单调增大')

    def test_missing_acid_kept_at_end(self):
        """没有 acid_true 的组排到最后，且不抛异常。"""
        k = _k()
        d = k.sample_data()
        d['groups'] = d['groups'][:3]
        d['groups'][0] = dict(d['groups'][0], acid_true=None)
        an = k.analyze(d, {'alpha_inf_mode': 'measured',
                           'order_group': d['groups'][1]['label']})
        self.assertIsNone(an['groups'][-1]['acid_true'])


class TestReportNumbering(unittest.TestCase):
    """表号/图号必须随实际条目数连续（3 组数据时 α–t 只占一张表）。"""

    def _build(self, n_groups, tmp):
        import os
        k = _k()
        rep = support.load_module(TOOL, 'report')
        ana = support.load_module(TOOL, 'analysis')
        d = k.sample_data()
        d['groups'] = d['groups'][:n_groups]
        cfg = ana.default_config()
        cfg.update({'student_name': '测', 'student_id': '1', 'group': '3',
                    'group_no': '8', 'date': 'd', 'room_temp': 22.0,
                    'pressure': 101.3, 'alpha_inf_mode': 'measured',
                    'order_group': d['groups'][min(1, n_groups - 1)]['label']})
        an = k.analyze(d, cfg)
        tpl = support.REPO_ROOT / TOOL / 'templates' / '化学动力学报告模板2026.docx'
        out = os.path.join(tmp, 'r%d.docx' % n_groups)
        rep.build_report(an, cfg, out, os.path.join(tmp, 'f%d' % n_groups),
                         str(tpl))
        return out

    def test_no_caption_gap_for_any_group_count(self):
        import tempfile
        import shutil
        from audit_docx import audit_docx
        tmp = tempfile.mkdtemp(prefix='kin_num_')
        try:
            for n in (1, 2, 3, 4, 5):
                out = self._build(n, tmp)
                errs = [i for i in audit_docx(out)
                        if getattr(i, 'level', '') == 'ERROR']
                self.assertEqual(
                    errs, [],
                    '%d 组数据时报告编号有问题：%s'
                    % (n, [getattr(e, 'detail', e) for e in errs]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestNoMarkdownInText(unittest.TestCase):
    """正文里不能漏出 markdown 的 **（Word 会原样印出来）。"""

    def test_no_double_asterisk_in_paragraph_text(self):
        import re
        p = support.REPO_ROOT / TOOL / 'pcal' / 'report.py'
        src = p.read_text(encoding='utf-8')
        # 只看字符串字面量里、作为中文正文报送的内容：逐行排除注释与文档字符串
        bad = []
        for i, line in enumerate(src.split('\n'), 1):
            code = line.split('#', 1)[0]
            for m in re.finditer(r"'([^']*\*\*[^']*)'", code):
                bad.append((i, m.group(1)[:60]))
        self.assertEqual(bad, [], '报告正文里出现了 markdown 粗体标记 **')


class TestJsonIsAlwaysLegal(unittest.TestCase):
    """接口回的 JSON 必须**永远合法**——一个 nan 就能让整个页面打不开。

    2026-11-10 真实事故：分析内核里 alpha_inf['sd'] 取到 float('nan')，
    `json.dumps` 把它写成裸 `NaN`（不是合法 JSON），前端 `res.json()` 抛
    `Unexpected token 'N', ...is not valid JSON`，界面卡在「初始化失败」，
    而错误消息完全指不到源头。

    判据（SKILL §27）：算不了时要**明确表示**——用 null（前端显示「—」），
    不能用 NaN/Infinity 混过去。
    """

    @classmethod
    def setUpClass(cls):
        cls._mods_before = set(sys.modules)
        cls.srv = support.load_module(TOOL, 'server')

    @classmethod
    def tearDownClass(cls):
        for name in [m for m in sys.modules if m not in cls._mods_before]:
            if name == 'pcal' or name.startswith('pcal.'):
                del sys.modules[name]

    def test_finite_only_replaces_nan_and_inf(self):
        import json
        f = support.load_module(TOOL, 'jsonutil').to_jsonable
        out = f({'a': float('nan'), 'b': [1.0, float('inf'), float('-inf')],
                 'c': {'d': float('nan')}})
        self.assertIsNone(out['a'])
        self.assertEqual(out['b'], [1.0, None, None])
        self.assertIsNone(out['c']['d'])
        # 关键断言：序列化结果必须能被标准 JSON 解析器读回
        json.loads(json.dumps(out, allow_nan=False))

    def test_analyze_output_has_no_nan_alpha_inf_sd(self):
        """分析结果里的 alpha_inf['sd'] 必须是 None，不能是 nan。"""
        k = _k()
        d = k.sample_data()
        # 模拟「没有 sd」的输入（用户从界面手填 α∞ 时就是这样）
        d['alpha_inf_measured'] = -1.10
        d.pop('alpha_inf_sd', None)
        d.pop('alpha_inf_n', None)
        an = k.analyze(d, {'alpha_inf_mode': 'measured', 'order_group': '4M'})
        sd = an['alpha_inf']['sd']
        self.assertIsNone(sd, 'alpha_inf.sd 必须是 None，不能是 nan/inf')
        self.assertEqual(an['alpha_inf']['n'], 1)

    def test_summary_json_parses(self):
        """/api/state 那一整包结构必须能被 json 解析（含大数据点的真实路径）。"""
        import json
        import math

        k = _k()
        d = k.sample_data()
        d['alpha_inf_measured'] = -1.10
        an = k.analyze(d, {'alpha_inf_mode': 'measured', 'order_group': '4M'})
        cfg = support.load_module(TOOL, 'analysis').default_config()

        # 直接调 _summary 需要 STATE，这里只验证内核输出经过 _finite_only 后可序列化
        payload = support.load_module(TOOL, 'jsonutil').to_jsonable(
            {'calibration': an['calibration'],
                                         'alpha_inf': an['alpha_inf'],
                                          'groups': [{kk: g[kk] for kk in
                                                      ('label', 'k1', 'sigma_k1',
                                                       't_half', 'alpha_inf')}
                                                     for g in an['groups']]})
        text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        back = json.loads(text)
        self.assertTrue(math.isfinite(back['groups'][0]['k1']))

    def test_no_bare_nan_literal_in_response(self):
        """允许 nan 的 dumps 会产出裸 NaN；加了 allow_nan=False 就不该出现。"""
        import json
        with self.assertRaises(ValueError):
            json.dumps({'x': float('nan')}, allow_nan=False)
