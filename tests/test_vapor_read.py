# -*- coding: utf-8 -*-
"""蒸气压模块的**读数据**回归（2026-11-25 用户要求「调整蒸气压模式的读数据逻辑」）。

为什么单独一个文件：这一批的缺陷全在「读」这一层，而且都是**静默**的 ——
旧解析器对真实日志返回 0 行、不报错；旧分支法把检漏读数当液体、把好点丢掉。

外部基准（不照着自己的输出写期望值）：
  · 真实 csv 是采集软件原样导出的文件（tests/fixtures/蒸气压/，GBK + 时间列）；
  · 拟合值的对照来自**操作者自己在 Origin 工程 20261125.opju 里的拟合结果**：
    水 A = 4972.9891 K、σ_A = 13.9230 K —— 本模块算出的 A、σ_A 与之逐位相同。
    环己烷那一支操作者用的是另一套取点（A = 3883.8943 / 3918.02…），
    与其 Origin 表格里存了 3 组互相不一致的拟合，故只作量级校验
    （ΔvapH 落在 31.5~32.6 kJ·mol⁻¹，与手册 29.97~33.01 相符）。
"""
from __future__ import annotations

import copy
import os
import sys
import unittest

from support import FIXTURES, drop_bare_pcal, load_module

# 必须带 sys.modules 隔离：本文件把某工具的 pcal 以裸包名载入后，
# 后面的模块（紫外要 from pcal import gcalc_bridge）会拿到错的 pcal。
# 见 test_echem_assign / test_kinetics_import 的同一段（§28.5）。
# 反过来也一样：**别人**留在 sys.modules 里的裸 pcal（如 test_uv_calibration
# 导入紫外 server 之后）会让本文件的 `from pcal import vapor` 直接 ImportError，
# 所以 setUpModule 先把残留清掉，tearDownModule 再把自己产生的清掉。
_MODS = None


def setUpModule():
    global _MODS
    drop_bare_pcal()                 # 清掉前面文件留下的裸 pcal
    _MODS = set(sys.modules)


def tearDownModule():
    drop_bare_pcal(_MODS)


FIX = FIXTURES / '蒸气压'


def _bytes(name):
    with open(str(FIX / name), 'rb') as fh:
        return fh.read()


def _text(name):
    """按采集软件的真实编码读：GBK。读不出就退回 utf-8-sig。"""
    raw = _bytes(name)
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('gbk')


class ParseRealCsvTests(unittest.TestCase):
    """真实 csv：GBK、第一列是采集时间、带表头。"""

    @classmethod
    def setUpClass(cls):
        cls.v = load_module('蒸气压工具', 'vapor')

    def test_fixtures_are_the_original_gbk_bytes(self):
        """fixture 必须保持 GBK 原样，否则「按 gbk 解码」这条路径测不到。"""
        raw = _bytes('水.csv')
        self.assertRaises(UnicodeDecodeError, raw.decode, 'utf-8')
        self.assertIn('pressure', raw.decode('gbk'))

    def test_time_column_is_not_read_as_pressure(self):
        """第一个数据行是 `13:27:11.033,  50.21,  28.63`：p=50.21、t=28.63。"""
        rows = self.v.parse_numeric_rows(_text('水.csv'))
        self.assertEqual(len(rows), 15, '水.csv 有 15 个数据行（含表头应被跳过）')
        self.assertAlmostEqual(rows[0][0], 50.21, places=6)
        self.assertAlmostEqual(rows[0][1], 28.63, places=6)

    def test_header_is_not_a_data_row(self):
        rows = self.v.parse_numeric_rows(_text('环己烷.csv'))
        self.assertEqual(len(rows), 26)
        for p, t in rows:
            self.assertGreater(p, 1.0, '表头不可能变成一行数据')
            self.assertGreater(t, 10.0)

    def test_seconds_only_timestamp_also_skipped(self):
        """环己烷那份的时间是 `53:03.0`（只有分:秒），别当成数值。"""
        rows = self.v.parse_numeric_rows(_text('环己烷.csv'))
        self.assertAlmostEqual(rows[0][0], 47.61, places=6)
        self.assertAlmostEqual(rows[0][1], 23.06, places=6)

    def test_without_time_column_gives_same_rows(self):
        """去掉时间列、换分隔符都不该改变读数（格式鲁棒性）。"""
        rows = self.v.parse_numeric_rows(_text('水.csv'))
        for sep in ('\t', ';', ','):
            txt = '\n'.join('%s%s%s' % (r[0], sep, r[1]) for r in rows)
            self.assertEqual(self.v.parse_numeric_rows(txt), rows,
                             '分隔符 %r 改变了读数' % sep)

    def test_row_order_does_not_matter(self):
        rows = self.v.parse_numeric_rows(_text('环己烷.csv'))
        shuffled = list(reversed(rows))
        a = self.v.classify_rows(rows)
        b = self.v.classify_rows(shuffled)
        for key in ('water', 'cyclo'):
            self.assertEqual(len(a[key]['atm']), len(b[key]['atm']))
            self.assertEqual(len(a[key]['series']), len(b[key]['series']))


class ClassifyRealCsvTests(unittest.TestCase):
    """分支与「哪些点不进拟合」的判定。"""

    @classmethod
    def setUpClass(cls):
        cls.v = load_module('蒸气压工具', 'vapor')
        cls.w = cls.v.classify_rows(cls.v.parse_numeric_rows(_text('水.csv')))
        cls.c = cls.v.classify_rows(cls.v.parse_numeric_rows(_text('环己烷.csv')))

    def test_water_file_only_feeds_water(self):
        self.assertEqual(len(self.w['water']['series']), 10)
        self.assertEqual(len(self.w['water']['atm']), 1)
        self.assertEqual((len(self.w['cyclo']['atm']),
                          len(self.w['cyclo']['series'])), (0, 0),
                         '水.csv 不该产出环己烷的点')

    def test_cyclo_file_only_feeds_cyclo(self):
        self.assertEqual(len(self.c['cyclo']['series']), 10)
        self.assertGreaterEqual(len(self.c['cyclo']['atm']), 1)
        self.assertEqual((len(self.c['water']['atm']),
                          len(self.c['water']['series'])), (0, 0),
                         '环己烷.csv 的读数不能被判成水')

    def test_unboiled_readings_of_water_are_rejected(self):
        """水 50 kPa 附近 28~29 ℃ 的 4 个读数是抽真空检漏时的，不是沸点。"""
        self.assertEqual(len(self.w['rejected']), 4)
        for r in self.w['rejected']:
            self.assertLess(r['t'], 35.0, '被排除的应是室温附近那 4 行')
            self.assertGreater(r['resid'], 0.5, '偏离必须显著才排除')
        # 剩下的系列里绝不能有 35 ℃ 以下的点
        for p, t in self.w['water']['series']:
            self.assertGreater(t, 35.0)

    def test_cyclo_leak_and_vent_readings_are_rejected(self):
        """环己烷：3 个室温检漏 + 1 个通大气后温度骤降到 59.59 ℃ 的读数。"""
        self.assertEqual(len(self.c['rejected']), 4)
        temps = sorted(r['t'] for r in self.c['rejected'])
        self.assertLess(temps[0], 30.0)
        self.assertLess(temps[-1], 62.0)
        for p, t in self.c['cyclo']['series']:
            self.assertGreater(t, 58.0, '59.59 ℃ 那行不能留在系列里')

    def test_every_row_is_accounted_for(self):
        """每一行要么进某一支，要么出现在 rejected 里，不许凭空消失。"""
        for diag, name in ((self.w, '水.csv'), (self.c, '环己烷.csv')):
            rows = self.v.parse_numeric_rows(_text(name))
            used = sum(len(diag[k]['atm']) + len(diag[k]['series'])
                       for k in ('water', 'cyclo'))
            self.assertEqual(used + len(diag['rejected']), len(rows),
                             '%s 的行对不上账' % name)

    def test_fake_line_from_leak_and_vent_is_rejected(self):
        """环己烷那份的 3 个检漏点 + 通大气点**恰好共线**（r2>0.9999），
        外推沸点 333 K。必须靠「外推沸点接近某支液体」把它挡掉。"""
        notes = ' '.join(self.c['notes'])
        self.assertIn('333', notes,
                      '应当说明有一簇共线但外推沸点不符的读数被排除：%s' % notes)


class FitForeignToKernelTests(unittest.TestCase):
    """拟合值对照外部基准（操作者自己的 Origin 结果）。"""

    @classmethod
    def setUpClass(cls):
        cls.v = load_module('蒸气压工具', 'vapor')
        cls.ana = load_module('蒸气压工具', 'analysis')
        diag = {}
        for name in ('水.csv', '环己烷.csv'):
            c = cls.v.classify_rows(cls.v.parse_numeric_rows(_text(name)))
            for k in ('water', 'cyclo'):
                if c[k]['atm'] or c[k]['series']:
                    diag[k] = c[k]
            diag.setdefault('_rej', [])
            diag['_rej'].extend(c['rejected'])
        cls.data = {k: diag[k] for k in ('water', 'cyclo')}
        cls.an = cls.v.analyze(cls.data, cls.ana.default_config())

    def test_water_A_matches_operators_origin_fit(self):
        """水：A = 4972.9891 K、σ_A = 13.9230 K —— 与 20261125.opju 逐位相同。"""
        f = self.an['water']['fit']
        self.assertAlmostEqual(f['A'], 4972.9891, places=3)
        self.assertAlmostEqual(f['sigma_A'], 13.9230, places=3)

    def test_water_enthalpy_physical(self):
        f = self.an['water']['fit']
        self.assertTrue(40.0 < f['dh_kJ'] < 42.5,
                        '水的 ΔvapH 应≈41 kJ/mol，实得 %r' % f['dh_kJ'])
        self.assertGreater(f['r2'], 0.999)

    def test_cyclo_enthalpy_physical(self):
        f = self.an['cyclo']['fit']
        self.assertTrue(31.0 < f['dh_kJ'] < 33.5,
                        '环己烷 ΔvapH 应在 31~33.5（手册 29.97~33.01），实得 %r'
                        % f['dh_kJ'])
        self.assertGreater(f['r2'], 0.995)

    def test_cyclo_atm_plateau_averaged_not_a_series_point(self):
        """环己烷有 12 个大气压附近的读数：它们是平行读数，只算一个平均点。"""
        m = self.an['cyclo']
        self.assertGreaterEqual(len(m['atm']), 2)
        self.assertIsNotNone(m['atm_avg'])
        self.assertEqual(len(m['fit']['points']),
                         len(m['series']) + 1,
                         '大气压平台只应贡献 1 个平均点')

    def test_no_regression_on_2025_sample(self):
        """2025 那批示例数据的数值必须逐位不变（README §27.7）。"""
        an = self.v.analyze(self.v.sample_data(), self.ana.default_config())
        w, c = an['water']['fit'], an['cyclo']['fit']
        self.assertAlmostEqual(w['A'], 4969.648358730787, places=6)
        self.assertAlmostEqual(w['B'], 13.294379771466687, places=6)
        self.assertAlmostEqual(w['tb'], 374.17927184332143, places=6)
        self.assertAlmostEqual(w['dh_kJ'], 41.31765645448776, places=6)
        self.assertAlmostEqual(c['A'], 3823.680378929886, places=6)
        self.assertAlmostEqual(c['tb'], 353.16629470818424, places=6)
        self.assertAlmostEqual(c['dh_kJ'], 31.790078670423075, places=6)


class DegenerateInputTests(unittest.TestCase):
    """读不了的时候必须**说清为什么**，不能静默 0 行 / nan。"""

    @classmethod
    def setUpClass(cls):
        cls.v = load_module('蒸气压工具', 'vapor')

    def test_empty_text_raises_with_reason(self):
        self.assertEqual(self.v.parse_numeric_rows(''), [])
        with self.assertRaises(ValueError) as ctx:
            self.v.classify_rows([])
        self.assertIn('没有读到', str(ctx.exception))

    def test_header_only_raises(self):
        rows = self.v.parse_numeric_rows('time,pressure(KPa),temperature(°C)')
        self.assertEqual(rows, [])
        self.assertRaises(ValueError, self.v.classify_rows, rows)

    def test_two_points_is_not_enough_and_says_so(self):
        with self.assertRaises(ValueError) as ctx:
            self.v.classify_rows([[50.0, 80.0], [60.0, 85.0]])
        msg = str(ctx.exception)
        self.assertIn('3 个点', msg)
        self.assertIn('10 K', msg)

    def test_points_clustered_at_one_temperature_rejected(self):
        """几个挤在同一温度的噪声点不构成一支系列。"""
        rows = [[50.0, 20.0], [51.0, 20.1], [52.0, 20.2], [53.0, 20.3]]
        with self.assertRaises(ValueError) as ctx:
            self.v.classify_rows(rows)
        self.assertIn('温区', str(ctx.exception))

    def test_noisy_log_still_finds_the_real_line(self):
        """真实日志 + 0.005 K 读数噪声：分类结果不变（不靠巧合的取整）。"""
        base = self.v.parse_numeric_rows(_text('环己烷.csv'))
        noisy = [[p + 0.01 * ((i % 3) - 1), t + 0.005 * ((i % 5) - 2)]
                 for i, (p, t) in enumerate(base)]
        c = self.v.classify_rows(noisy)
        self.assertEqual(len(c['cyclo']['series']), 10)
        self.assertEqual(len(c['rejected']), 4)

    def test_tolerance_is_not_on_a_knife_edge(self):
        """容差 0.05~0.15 内结论必须一致（实测内点余量 1.6 倍、外点 7 倍）。"""
        rows = self.v.parse_numeric_rows(_text('环己烷.csv'))
        shapes = set()
        for tol in (0.05, 0.08, 0.10, 0.15):
            c = self.v.classify_rows(rows, tol=tol)
            shapes.add((len(c['cyclo']['atm']), len(c['cyclo']['series']),
                        len(c['rejected'])))
        self.assertEqual(len(shapes), 1, '容差敏感，说明判据不稳：%s' % shapes)


class MergeImportTests(unittest.TestCase):
    """水与环己烷来自两个文件：后一次导入不能把前一支抹掉。"""

    @classmethod
    def setUpClass(cls):
        cls.v = load_module('蒸气压工具', 'vapor')
        cls.w = cls.v.classify_rows(cls.v.parse_numeric_rows(_text('水.csv')))
        cls.c = cls.v.classify_rows(cls.v.parse_numeric_rows(_text('环己烷.csv')))

    def test_second_import_keeps_first_liquid(self):
        old = {'water': self.w['water'], 'cyclo': {'atm': [], 'series': []}}
        merged, replaced = self.v.merge_classified(
            old, {'water': {'atm': [], 'series': []}, 'cyclo': self.c['cyclo']})
        self.assertEqual(replaced, ['cyclo'])
        self.assertEqual(len(merged['water']['series']), 10,
                         '导入环己烷时把水的数据弄丢了')
        self.assertEqual(len(merged['cyclo']['series']), 10)

    def test_empty_side_does_not_erase_existing(self):
        old = {'water': self.w['water'], 'cyclo': self.c['cyclo']}
        merged, replaced = self.v.merge_classified(
            old, {'water': {'atm': [], 'series': []},
                  'cyclo': {'atm': [], 'series': []}})
        self.assertEqual(replaced, [])
        self.assertEqual(len(merged['water']['series']), 10)
        self.assertEqual(len(merged['cyclo']['series']), 10)

    def test_explicit_target_replaces_only_that_liquid(self):
        old = {'water': self.w['water'], 'cyclo': self.c['cyclo']}
        merged, replaced = self.v.merge_classified(
            old, {'water': self.c['cyclo'], 'cyclo': self.c['cyclo']},
            target='water')
        self.assertEqual(replaced, ['water'])


class ServerImportTests(unittest.TestCase):
    """服务端：导入 → 合并 → 诊断能跟着数据活下来（改封面重算不丢）。

    ⚠️ 每个工具的 ``pcal/server.py`` 都有 ``sys.path.insert(0, ROOT)`` 加
    ``from pcal import …``。导入 server 会把这个工具的 ``pcal`` 以**裸包名**
    注册进 ``sys.modules``，之后别的工具的 server（例如紫外光谱的
    ``from pcal import gcalc_bridge``）就会拿到**蒸气压的 pcal**，
    报 ``ImportError: cannot import name 'vapor'``（2026-11-25 全量跑就是
    这么红的：单跑本文件 31 项全绿）。所以本类导入前后要快照/还原裸 'pcal'。
    """

    @classmethod
    def setUpClass(cls):
        cls._mods_before = set(sys.modules)
        cls.srv = load_module('蒸气压工具', 'server')

    @classmethod
    def tearDownClass(cls):
        for name in [m for m in sys.modules if m not in cls._mods_before]:
            if name == 'pcal' or name.startswith('pcal.'):
                del sys.modules[name]

    def setUp(self):
        with self.srv.LOCK:
            self.srv.STATE.update(analysis=None, config=None, data=None,
                                  key=None, diag=None, diag_key=None)

    def tearDown(self):
        with self.srv.LOCK:
            self.srv.STATE.update(analysis=None, config=None, data=None,
                                  key=None, diag=None, diag_key=None)

    def _imp(self, name):
        import base64
        return self.srv._import('file', {
            'b64': base64.b64encode(_bytes(name)).decode('ascii'),
            'name': name})

    def test_import_reports_rejected_rows(self):
        out = self._imp('水.csv')
        self.assertTrue(out['ok'], out.get('error'))
        self.assertEqual(out['count'], 15)
        self.assertEqual(len(out['rejected']), 4)
        self.assertTrue(out['lines'])

    def test_import_error_is_actionable(self):
        out = self.srv._import('file', {'b64': '', 'name': 'x.csv'})
        self.assertFalse(out['ok'])
        self.assertIn('数据行', out['error'])

    def test_two_imports_merge_and_diag_persists(self):
        self.srv._absorb_import(self._imp('水.csv'), {})
        o2 = self.srv._absorb_import(self._imp('环己烷.csv'), {})
        self.assertIn('cyclo', o2['replaced'])
        self.assertEqual(len(o2['water']['series']), 10)
        self.assertEqual(len(o2['cyclo']['series']), 10)
        self.assertEqual(len(o2['rejected']), 8)

        an = self.srv._analysis(self.srv._config_from(), o2, force=True)
        self.assertEqual(len(an['rejected']), 8)
        # 只改封面再算：诊断必须还在（挂 cfg 上就会丢）
        cfg2 = self.srv._config_from({'config': {'date': '2026/11/26'}})
        an2 = self.srv._analysis(cfg2, o2, force=True)
        self.assertEqual(len(an2['rejected']), 8,
                         '改了封面之后「被排除的读数」不该消失')

    def test_sample_data_is_not_merged_with_real_import(self):
        """首次打开时 STATE 里是 2025 示例：导入真实数据必须整份替换。"""
        with self.srv.LOCK:
            self.srv.STATE['data'] = self.srv._normalize_data(
                load_module('蒸气压工具', 'vapor').sample_data())
        out = self.srv._absorb_import(self._imp('水.csv'), {})
        self.assertEqual(len(out['cyclo']['series']), 0,
                         '示例的环己烷不该混进真实数据')


class ReportNumberingTests(unittest.TestCase):
    """有「未参与拟合的读数」时多一张表：表号必须按出现顺序连续。"""

    def test_report_tables_stay_continuous(self):
        import re
        import tempfile
        from pathlib import Path
        vapor = load_module('蒸气压工具', 'vapor')
        ana = load_module('蒸气压工具', 'analysis')
        rpt = load_module('蒸气压工具', 'report')
        w = vapor.classify_rows(vapor.parse_numeric_rows(_text('水.csv')))
        c = vapor.classify_rows(vapor.parse_numeric_rows(_text('环己烷.csv')))
        data = {'water': w['water'], 'cyclo': c['cyclo']}
        diag = {'rejected': w['rejected'] + c['rejected'],
                'notes': w['notes'] + c['notes'],
                'lines': w['lines'] + c['lines']}
        an = vapor.analyze(data, ana.default_config(), diag=diag)
        cfg = ana.default_config()
        cfg.update(student_name='测试', student_id='2300000000', group='3',
                   group_no='8', date='2026/11/25', room_temp=23.0,
                   pressure=101.3)
        from support import REPO_ROOT
        tpl = REPO_ROOT / '蒸气压工具' / 'templates' / '蒸气压报告模板2026.docx'
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'r.docx')
            rpt.build_report(an, cfg, out, os.path.join(tmp, 'fig'), str(tpl))
            from docx import Document
            doc = Document(out)
            nums = []
            for p in doc.paragraphs:
                m = re.match(r'^表(\d+)\s{2}', p.text.strip())
                if m:
                    nums.append(int(m.group(1)))
            self.assertEqual(nums, list(range(1, len(nums) + 1)),
                             '表号不连续：%s' % nums)
            # 有排除行时，两支各多一张表 → 3+1+3+1+1 = 9
            self.assertEqual(len(nums), 9)


if __name__ == '__main__':
    unittest.main(verbosity=2)