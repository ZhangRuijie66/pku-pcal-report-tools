# -*- coding: utf-8 -*-
"""紫外光谱：标定条目可增减 + 每条曲线可选标定的回归测试。

守住的要点：
1. **默认零漂移**：默认配置下标定清单就是出厂三条、曲线分配与旧行为一致，
   报告 3.1 节输出逐字不变（否则用户手上那份报告会莫名其妙变样）。
2. **可增减**：新增的标定要能出现在槽位、能算出 a/b、能在报告里占一节。
3. **逐曲线可选**：改某条曲线的标定只影响那一条，其它曲线数值不动。
4. **不静默出错**：选了不存在的标定要退回默认，绝不 KeyError 或算出空值。
5. **缓存键**：改了标定必须触发重算（曾经漏掉过，改了不生效）。
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support                                        # noqa: E402

TOOL = '紫外光谱工具'
DATA = support.REPO_ROOT / '3 紫外光谱搭建' / '数据'
FIXTURE = support.FIXTURES / '紫外光谱'


def _uv():
    return support.load_module(TOOL, 'uv')


def _analysis_mod():
    return support.load_module(TOOL, 'analysis')


def _data_dir():
    """优先用仓库自带的 fixtures（任何机器上都在），退回课程数据目录。"""
    if FIXTURE.is_dir() and any(FIXTURE.rglob('*.txt')):
        return str(FIXTURE)
    return str(DATA)


HAVE_DATA = os.path.isdir(_data_dir()) and any(
    p.suffix.lower() == '.txt' for p in Path(_data_dir()).rglob('*.txt'))


class CalibrationListTests(unittest.TestCase):
    """清单解析是纯函数，不需要数据文件。"""

    def setUp(self):
        self.uv = _uv()

    def test_default_is_three(self):
        """默认（没有自定义条目）就是出厂三条，顺序不变。"""
        cals = self.uv.effective_calibrations(None)
        self.assertEqual([c['key'] for c in cals],
                         ['d1_long', 'd2_long', 'd2_short'])

    def test_add_custom_appends(self):
        uv = self.uv
        cals = uv.effective_calibrations([
            dict(key='c3', label='第三周长波', file='x/氘灯3.txt'),
        ])
        self.assertEqual([c['key'] for c in cals],
                         ['d1_long', 'd2_long', 'd2_short', 'c3'])
        self.assertTrue(cals[-1].get('custom'))

    def test_custom_same_key_overrides_default(self):
        """同 key 时用户条目覆盖出厂条目（可以把默认标定换成自己重测的谱）。"""
        uv = self.uv
        cals = uv.effective_calibrations([
            dict(key='d2_long', label='重测的长波', file='mine.txt'),
        ])
        got = [c for c in cals if c['key'] == 'd2_long'][0]
        self.assertEqual(got['label'], '重测的长波')
        self.assertEqual(got['file'], 'mine.txt')
        self.assertEqual(len(cals), 3)          # 数量不变，只是覆盖

    def test_bad_entries_dropped(self):
        """没有 key/file、或 key 含非法字符的条目要被丢掉，不能进槽位名。"""
        uv = self.uv
        cals = uv.effective_calibrations([
            dict(key='', file='a.txt'),
            dict(key='ok', file=''),
            dict(key='bad key/with slash', file='a.txt'),
            dict(key='good', file='a.txt'),
        ])
        keys = [c['key'] for c in cals]
        self.assertIn('good', keys)
        self.assertNotIn('bad key/with slash', keys)
        self.assertEqual(len(keys), 4)          # 三条默认 + good

    def test_prior_parsed(self):
        uv = self.uv
        cals = uv.effective_calibrations([
            dict(key='c1', file='a.txt', prior=['0.1257', '422.3']),
            dict(key='c2', file='b.txt', prior='nonsense'),
        ])
        by = {c['key']: c for c in cals}
        self.assertEqual(by['c1']['prior'], (0.1257, 422.3))
        self.assertIsNone(by['c2']['prior'])


class CurveCalMapTests(unittest.TestCase):
    """每条曲线用哪条标定。"""

    def setUp(self):
        self.uv = _uv()

    def test_default_mapping_matches_legacy(self):
        """默认分配必须与改动前写死的 s['cal'] 完全一致。"""
        uv = self.uv
        mapping = uv.curve_cal_map(None, uv.CALIBRATIONS)
        for s in uv.SAMPLES:
            self.assertEqual(mapping[s['key']], s['cal'],
                             '%s 的默认标定变了' % s['key'])

    def test_unknown_cal_falls_back(self):
        """选了不存在的标定 → 退回该曲线的默认值，不是 None/KeyError。"""
        uv = self.uv
        mapping = uv.curve_cal_map({'A4': '已经删掉的标定'}, uv.CALIBRATIONS)
        self.assertEqual(mapping['A4'], uv.CURVE_CAL_DEFAULT['A4'])

    def test_custom_cal_selectable(self):
        uv = self.uv
        cals = uv.effective_calibrations([
            dict(key='c3', label='第三周', file='x.txt')])
        mapping = uv.curve_cal_map({'A4': 'c3'}, cals)
        self.assertEqual(mapping['A4'], 'c3')

    def test_samples_using_cal(self):
        uv = self.uv
        self.assertEqual(uv.samples_using_cal('d1_long', None, uv.CALIBRATIONS),
                         ['A4'])
        # 短波标定覆盖 A1/B1/B1b/B1c/B2
        short = uv.samples_using_cal('d2_short', None, uv.CALIBRATIONS)
        for k in ('A1', 'B1', 'B1b', 'B1c', 'B2'):
            self.assertIn(k, short)


class SlotTests(unittest.TestCase):
    """标定清单要贯通到槽位（否则新加标定的文件映射不出现）。"""

    def setUp(self):
        self.uv = _uv()

    def test_new_cal_gets_slot(self):
        uv = self.uv
        cals = uv.effective_calibrations([
            dict(key='c3', label='第三周长波', file='x/氘灯3.txt')])
        slots = uv.file_slots(None, None, cals)
        keys = [s['key'] for s in slots]
        self.assertIn('cal:c3', keys)
        self.assertIn('cal:c3', uv.all_slot_keys(cals))
        # 默认清单里没有它
        self.assertNotIn('cal:c3', uv.all_slot_keys())

    def test_clean_file_map_keeps_custom_cal(self):
        uv = self.uv
        cals = uv.effective_calibrations([
            dict(key='c3', label='第三周', file='x.txt')])
        cleaned = uv.clean_file_map({'cal:c3': 'x/氘灯3.txt'}, cals)
        self.assertIn('cal:c3', cleaned)
        # 不传 cals 时会被当非法键丢掉——这是刻意的：调用方必须传清单
        self.assertNotIn('cal:c3', uv.clean_file_map({'cal:c3': 'x.txt'}))


@unittest.skipUnless(HAVE_DATA, '没有紫外光谱原始数据')
class EndToEndTests(unittest.TestCase):
    """真的要读数据、算一遍。"""

    def _run(self, **cfg_over):
        Analysis = _analysis_mod().Analysis
        cfg = _analysis_mod().default_config()
        cfg['data_dir'] = _data_dir()
        cfg.update(cfg_over)
        an = Analysis(cfg)
        an.run()
        return an

    def test_default_uses_three_and_legacy_mapping(self):
        an = self._run()
        self.assertEqual(len(an.cal_list), 3)
        uv = _uv()
        for s in uv.SAMPLES:
            self.assertEqual(an.curve_cal[s['key']], s['cal'])

    def test_changing_one_curve_cal_changes_only_that_curve(self):
        """把 A4 换一条标定：A4 的 λmax 要变，其它分子必须纹丝不动。"""
        base = self._run()
        alt = self._run(curve_cal={'A4': 'd2_long'})
        uv = _uv()
        # A4 变了（两条标定的斜率不同，换算后峰位必然有差）
        a4a = base.samples[uv.MOLECULE_DEFAULT['A4']]['peak']['lam']
        a4b = alt.samples[uv.MOLECULE_DEFAULT['A4']]['peak']['lam']
        self.assertNotAlmostEqual(a4a, a4b, places=4,
                                  msg='换标定后 A4 的 λmax 没变，说明没生效')
        # 其它分子完全相同
        for code in ('A1', 'A2', 'A3', 'B1', 'B2'):
            ka = uv.MOLECULE_DEFAULT[code]
            self.assertAlmostEqual(base.samples[ka]['peak']['lam'],
                                   alt.samples[ka]['peak']['lam'], places=9,
                                   msg='%s 不该受 A4 标定改动影响' % code)

    def test_custom_cal_computed_and_report_has_extra_section(self):
        """新增标定要能算出来，并且报告 3.1 多一节。"""
        import tempfile
        uv = _uv()
        # 复用第二周长波的光源谱作为「新标定」的输入
        src = [c for c in uv.CALIBRATIONS if c['key'] == 'd2_long'][0]['file']
        an = self._run(calibrations=[dict(key='my_cal', label='新增标定',
                                          short='新增', file=src)])
        self.assertEqual(len(an.cal_list), 4)
        self.assertIn('my_cal', an.cals)
        self.assertTrue(an.cals['my_cal']['ok'])
        self.assertGreater(an.cals['my_cal']['a'], 0)

        # 报告：3.1.4 必须存在
        import re
        import zipfile
        rpt = support.load_module(TOOL, 'report')
        srv = support.load_module(TOOL, 'server')
        tmp = tempfile.mkdtemp(prefix='uvcal_')
        out = os.path.join(tmp, 'r.docx')
        rpt.build_report(an, an.cfg, out, os.path.join(tmp, 'figs'),
                         srv.TEMPLATE)
        with zipfile.ZipFile(out) as z:
            xml = z.read('word/document.xml').decode('utf-8', 'replace')
        texts = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', xml)
        heads = [t for t in texts if re.match(r'^3\.1\.\d', t)]
        self.assertEqual(len(heads), 4, '报告应出现 4 个 3.1.x 子节：%s' % heads)
        self.assertTrue(heads[3].startswith('3.1.4'), heads)


class CacheKeyTests(unittest.TestCase):
    """改标定必须触发重算（缓存键要覆盖它）。"""

    def test_analysis_cache_key_includes_calibration(self):
        srv = support.load_module(TOOL, 'server')
        import inspect
        src = inspect.getsource(srv._analysis)
        # 缓存键的字典里必须出现这两个键名
        self.assertIn("'calibrations'", src,
                      '_analysis 缓存键没包含 calibrations：改标定不会重算')
        self.assertIn("'curve_cal'", src,
                      '_analysis 缓存键没包含 curve_cal：改曲线标定不会重算')

    def test_coerce_cleans_calibrations(self):
        """前端传上来的自定义条目要清洗（非法 key 不能进槽位名）。"""
        srv = support.load_module(TOOL, 'server')
        cfg = srv._coerce(srv.default_config(), {'config': {
            'calibrations': [dict(key='bad key', file='a.txt'),
                             dict(key='ok', file='b.txt')],
        }})
        keys = [c['key'] for c in cfg['calibrations']]
        self.assertEqual(keys, ['ok'])


class ReportDefaultUnchangedTests(unittest.TestCase):
    """默认三条时，报告 3.1 的标题与「使用该标定」措辞必须是旧版原句。"""

    def test_default_titles_and_notes_pinned(self):
        rpt = support.load_module(TOOL, 'report')
        self.assertEqual(rpt.DEFAULT_CAL_TITLES, {
            'd1_long': '长波范围（第一周）',
            'd2_long': '长波范围（第二周）',
            'd2_short': '短波范围（第二周）',
        })
        self.assertEqual(rpt.DEFAULT_CAL_NOTES['d1_long'],
                         '本实验中 A4 的测量使用该标定结果。')
        self.assertIn('A3 的浓度系列', rpt.DEFAULT_CAL_NOTES['d2_long'])
        self.assertIn('A1、B1、B2', rpt.DEFAULT_CAL_NOTES['d2_short'])

    def test_cn_num_and_peak_word(self):
        rpt = support.load_module(TOOL, 'report')
        self.assertEqual(rpt._cn_num(3), '三')
        self.assertEqual(rpt._cn_num(4), '四')
        self.assertEqual(rpt._n_peak_word(3), '三个')
        self.assertEqual(rpt._n_peak_word(4), '四个')
        self.assertEqual(rpt._n_peak_word(None), '若干')


if __name__ == '__main__':
    unittest.main(verbosity=2)
