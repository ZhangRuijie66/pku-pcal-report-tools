# -*- coding: utf-8 -*-
"""表面吸附：导出的数据表回读（pcal/importdata.py）的回归测试。

为什么单列一个文件：这条链路的失败模式**全是静默的**——
读少一列、平行次数回退成 3、换算值被当成实测值，界面都不报错，
只是报告里的数字悄悄变了。所以每条用例都对比「回读前后重新分析的结果」。

用例覆盖（对应 SKILL §27.2 的三类检查）：
  · 数量：平行 1 / 5 / 6 次、浓度点 2 / 8 个、只有一种方法；
  · 路径：文件名不带后缀、工作表被改名、坏文件明确报错；
  · 口径：只读一侧时 σ(Δh) 的灵敏度 2 倍关系必须保住。
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from support import load_module


class DataTableRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adsorption = load_module('表面吸附工具', 'adsorption')
        cls.analysis = load_module('表面吸附工具', 'analysis')
        cls.exportdata = load_module('表面吸附工具', 'exportdata')
        cls.importdata = load_module('表面吸附工具', 'importdata')

    # ------------------------------------------------------------ 工具
    def _cfg(self, **kw):
        cfg = self.analysis.default_config()
        cfg.update(dict(temperature_bubble=30.0, temperature_plate=25.0,
                        gamma_water=71.19, sigma_read=0.02, sigma_plate=0.01,
                        conc_axis='lg', zero_correction=True,
                        height_mode='both', height_sum=0.0,
                        repeat_n_bubble=3, repeat_n_plate=3))
        cfg.update(kw)
        return cfg

    def _data(self, n=3):
        """示例数据，按 n 次平行裁剪/补齐。"""
        d = copy.deepcopy(self.adsorption.sample_data())
        if n != 3:
            d['zero'] = {'left': (d['zero']['left'] * n)[:n],
                         'right': (d['zero']['right'] * n)[:n]}
            d['water_bubble'] = {'left': (d['water_bubble']['left'] * n)[:n],
                                 'right': (d['water_bubble']['right'] * n)[:n]}
            for r in d['bubble']:
                r['left'] = (r['left'] * n)[:n]
                r['right'] = (r['right'] * n)[:n]
            for r in d['plate']:
                r['gamma'] = (r['gamma'] * n)[:n]
            d['water_plate'] = (d['water_plate'] * n)[:n]
        return d

    def _roundtrip(self, data, cfg, fmt='xlsx', base=None):
        an = self.adsorption.analyze(data, cfg)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ('t.' + fmt)
            self.exportdata.write(an, str(path), fmt)
            res = self.importdata.read(path.name, path.read_bytes(),
                                       base if base is not None else data)
        cfg2 = dict(cfg)
        cfg2.update(res['config'])
        self.analysis.merge_saved(cfg2, res['config'])
        return an, self.adsorption.analyze(res['data'], cfg2), res

    def _assert_same_results(self, a1, a2, label=''):
        for name in ('gamma_inf', 'sigma_gamma_inf', 'q', 'sigma_q'):
            x, y = a1[name], a2[name]
            if x != x or y != y:            # 都是 NaN 也算一致
                self.assertEqual(x != x, y != y, '%s %s: %r vs %r'
                                 % (label, name, x, y))
                continue
            self.assertAlmostEqual(
                x, y, places=15,
                msg='%s：%s 回读后变了（%r → %r）' % (label, name, x, y))
        for r1, r2 in zip(a1['rows'], a2['rows']):
            self.assertAlmostEqual(r1['gamma'], r2['gamma'], places=12,
                                   msg='%s：某行的 γ 回读后变了' % label)
            self.assertAlmostEqual(r1['sigma_gamma'], r2['sigma_gamma'], places=12,
                                   msg='%s：某行的 σ(γ) 回读后变了' % label)

    # ------------------------------------------------------------ 数量
    def test_repeat_counts_survive(self):
        """平行 1 / 2 / 5 / 6 次都要能原样读回（次数来自表头，不写死 3）。"""
        for n in (1, 2, 5, 6):
            an1, an2, res = self._roundtrip(
                self._data(n), self._cfg(repeat_n_bubble=n, repeat_n_plate=n))
            self.assertEqual(res['info']['repeat']['bubble'], n, 'n=%d' % n)
            self.assertEqual(res['info']['repeat']['plate'], n, 'n=%d' % n)
            self.assertEqual(an2['bubble']['repeat_n'], n)
            self.assertEqual(an2['plate']['repeat_n'], n)
            self._assert_same_results(an1['bubble'], an2['bubble'], 'bubble n=%d' % n)
            self._assert_same_results(an1['plate'], an2['plate'], 'plate n=%d' % n)

    def test_two_methods_independent_counts(self):
        """两法次数不同（5 / 2）时各取各的，不许串味。"""
        d = self._data(3)
        d['bubble'] = [dict(r, left=list(r['left']) + [r['left'][-1] + 0.01,
                                                      r['left'][-1] - 0.01],
                            right=list(r['right']) + [r['right'][-1] - 0.01,
                                                      r['right'][-1] + 0.01])
                       for r in d['bubble']]
        d['plate'] = [dict(r, gamma=list(r['gamma'])[:2]) for r in d['plate']]
        an1, an2, res = self._roundtrip(
            d, self._cfg(repeat_n_bubble=5, repeat_n_plate=2))
        self.assertEqual(res['info']['repeat'], {'bubble': 5, 'plate': 2})
        self.assertEqual(an2['bubble']['repeat_n'], 5)
        self.assertEqual(an2['plate']['repeat_n'], 2)

    def test_two_concentration_points(self):
        """只有 2 个浓度点：斜率仍能定出来，回读后数字一致。"""
        d = self._data(3)
        d['bubble'] = d['bubble'][-2:]
        d['plate'] = d['plate'][-2:]
        an1, an2, res = self._roundtrip(d, self._cfg())
        self.assertEqual(res['info']['counts'], {'bubble': 2, 'plate': 2})
        self._assert_same_results(an1['bubble'], an2['bubble'], 'bubble 2pt')
        self._assert_same_results(an1['plate'], an2['plate'], 'plate 2pt')

    def test_single_method_only(self):
        """只有一种方法的数据表，另一种不许被清空成空表里的 NaN 崩掉。"""
        d = self._data(3)
        d['plate'] = []
        d['water_plate'] = []
        an1, an2, res = self._roundtrip(d, self._cfg())
        self.assertEqual(res['info']['counts']['bubble'], 8)
        self.assertEqual(res['info']['counts']['plate'], 0)
        self._assert_same_results(an1['bubble'], an2['bubble'], 'only bubble')

    # ------------------------------------------------------------ 口径
    def test_one_side_mode_keeps_sigma(self):
        """只读左侧：回读后 σ(Δh) 必须仍是「S − 2h」的两倍灵敏度口径。

        这条最容易退化：如果回读把按 S 换算出来的右侧当实测值带回来，
        σ(Δh) 会从 0.0632 掉到 0.0400 左右（两侧独立相减），
        报告里的不确定度会平白小三分之一，而界面不报任何错。
        """
        S = 43.835
        d = copy.deepcopy(self.adsorption.sample_data())
        for r in d['bubble']:
            r['left'] = [S - r['right'][0]] * 3
            r['right'] = []
        d['zero'] = {'left': [S - 22.0] * 3, 'right': []}
        d['water_bubble'] = {'left': [S - 26.36] * 3, 'right': []}
        cfg = self._cfg(height_mode='left', height_sum=S)
        an1, an2, res = self._roundtrip(d, cfg)
        self.assertEqual(res['info']['height_mode'], 'left')
        self.assertAlmostEqual(an2['bubble']['height']['sum'], S, places=9)
        for r1, r2 in zip(an1['bubble']['rows'], an2['bubble']['rows']):
            self.assertAlmostEqual(r1['sigma_dh'], r2['sigma_dh'], places=15,
                                   msg='σ(Δh) 回读后退化了（两侧口径 ≈ 0.040）')
            self.assertAlmostEqual(r1['sigma_gamma'], r2['sigma_gamma'], places=15)
        # 换算出来的那一侧不该被当成实测值带回来
        self.assertEqual(res['data']['bubble'][0]['right'], [])

    def test_config_rows_present_in_export(self):
        """说明表必须带够回读需要的行（吊片法温度/σ/纯水读数）。"""
        an = self.adsorption.analyze(self._data(3), self._cfg())
        sheets = self.exportdata.tables(an)
        info_rows = dict((r[0], r[1]) for r in sheets[0][2] if len(r) >= 2)
        self.assertIn('吊片法温度 /℃', info_rows)
        self.assertIn('吊片法单次读数 σ_γ /(mN·m⁻¹)', info_rows)
        self.assertIn('纯水 γ(吊片法) /(mN·m⁻¹)', info_rows)
        self.assertAlmostEqual(info_rows['吊片法温度 /℃'], 25.0, places=6)

    def test_data_vs_config_split(self):
        """温度/γ_w/σ 属于 data，处理参数属于 config —— 放错边会静默不生效。"""
        cfg = self._cfg()
        res = self._roundtrip(self._data(3), cfg)[2]
        for key in ('temperature_bubble', 'temperature_plate', 'gamma_water',
                    'sigma_read', 'sigma_plate'):
            self.assertNotIn(key, res['config'],
                             '%s 不该出现在 config 里（server._coerce 会丢掉）' % key)
        for key in ('height_mode', 'zero_correction', 'conc_axis',
                    'repeat_n_bubble', 'repeat_n_plate'):
            self.assertIn(key, res['config'], '%s 应该回填到 config' % key)

    # ------------------------------------------------------------ 兼容/报错
    def test_filename_without_extension(self):
        """文件名没后缀时按内容头判格式（zip → xlsx）。"""
        an = self.adsorption.analyze(self._data(3), self._cfg())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'x.xlsx'
            self.exportdata.write(an, str(path), 'xlsx')
            raw = path.read_bytes()
        res = self.importdata.read('未命名-数据', raw, self._data(3))
        self.assertEqual(res['info']['format'], 'xlsx')
        self.assertEqual(res['info']['counts']['bubble'], 8)

    def test_renamed_sheets(self):
        """工作表被改名也要按表头认出来，并在 warnings 里说明。"""
        import openpyxl
        an = self.adsorption.analyze(self._data(3), self._cfg())
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'a.xlsx'
            self.exportdata.write(an, str(src), 'xlsx')
            wb = openpyxl.load_workbook(str(src))
            wb['最大气泡法'].title = 'Sheet1'
            wb['吊片法'].title = 'Sheet2'
            dst = Path(tmp) / 'b.xlsx'
            wb.save(str(dst))
            res = self.importdata.read('b.xlsx', dst.read_bytes(), self._data(3))
        self.assertEqual(res['info']['counts'], {'bubble': 8, 'plate': 8})
        self.assertTrue(any('改名' in w for w in res['warnings']), res['warnings'])

    def test_garbage_file_raises(self):
        """不是数据表就明确报错，不许静默返回空数据。"""
        with self.assertRaises(self.importdata.ImportDataError):
            self.importdata.read('bad.xlsx', b'PK\x03\x04garbage', None)
        with self.assertRaises(self.importdata.ImportDataError):
            self.importdata.read('bad.csv', 'a,b,c\n1,2,3\n'.encode('utf-8'), None)

    def test_csv_roundtrip_warns_and_uses_one_reading(self):
        """csv 只有均值列：读回后按 1 次读数，并且必须给 warning。"""
        an1, an2, res = self._roundtrip(self._data(3), self._cfg(), fmt='csv')
        self.assertEqual(res['info']['format'], 'csv')
        self.assertEqual(res['config'].get('repeat_n_bubble'), 1)
        self.assertTrue(any('csv' in w for w in res['warnings']), res['warnings'])
        # 均值本身要读得回来（导出保留 2 位小数，这里按 0.01 精度比）
        for r1, r2 in zip(an1['plate']['rows'], an2['plate']['rows']):
            self.assertAlmostEqual(r1['gamma'], r2['gamma'], delta=0.02)


if __name__ == '__main__':
    unittest.main()
