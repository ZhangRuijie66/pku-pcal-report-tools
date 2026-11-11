# -*- coding: utf-8 -*-
"""电化学：按**语义**匹配数据文件名（中文命名 / 尾号扫速）。

守的是 2026-11-11 用户报的真实情况：

    请你根据我的电化学数据名称再优化模糊匹配

他今年 CHI 导出的文件名是 ``氮气1/氮气2/氮气5``、``快速搅拌/低速搅拌/不搅拌``、
``CH3OH``，而槽位默认名是 ``N2_1 / N2_2 / N2_5 / O2_fast / O2_slow / O2_still /
MeOH``。原来的匹配只有字符串相似度，实测七个槽位的最高分是 0.11~0.25，
**全部 ambiguous**，「一键自动匹配」一个都填不进去，只能手动点七次。

修法：给每个槽位加一条**语义判据**（``analysis.SLOT_SPEC``），
先把文件名归到体系族（N₂ / O₂ / 甲醇），再用族内判别量定具体是哪一份：

* N₂ 组用**扫速**：文件名尾号 ``1/2/5`` → 0.1/0.2/0.5 V·s⁻¹，
  并优先用 CHI 文件头里的 ``Scan Rate (V/s)`` 交叉核对（仪器写的硬证据）；
* O₂ 组用**搅拌条件**词（快速 / 低速 / 不搅拌），``不搅拌`` 类必须先判，
  否则会被「搅拌」这一族吃掉、和「快速搅拌」同分；
* 甲醇只有一份，族命中即可。

本文件同时守住三条「宁可不匹配，也不许静默选错」的底线：
语义硬冲突不许自动采用、并列候选不按路径字母序默选、名字命中但文件头
对不上要说清。这三条都是本项目反复踩过的坑（见 SKILL §25.2）。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support                                        # noqa: E402

TOOL = '电化学工具'
FIXTURES = support.FIXTURES / '电化学'

#: 用户今年的真实文件名 → 该进的槽位（2026-11-11 实测的那批）
USER_FILES = {
    '氮气1.txt': 'file_n2_blank',
    '氮气2.txt': 'file_n2_02',
    '氮气5.txt': 'file_n2_05',
    '快速搅拌.txt': 'file_o2_fast',
    '低速搅拌.txt': 'file_o2_slow',
    '不搅拌.txt': 'file_o2_still',
    'CH3OH.txt': 'file_meoh',
}


def _write(path, text='placeholder\n'):
    Path(path).write_text(text, encoding='utf-8')


class SemanticProfileTests(unittest.TestCase):
    """``analysis.semantic_profile``：文件名 → 族 / 扫速 / 搅拌条件。"""

    @classmethod
    def setUpClass(cls):
        cls.analysis = support.load_module(TOOL, 'analysis')

    def test_chinese_families(self):
        a = self.analysis
        self.assertEqual(a.semantic_profile('氮气1.txt')['family'], 'n2')
        self.assertEqual(a.semantic_profile('氧气.txt')['family'], 'o2')
        self.assertEqual(a.semantic_profile('甲醇.txt')['family'], 'meoh')
        self.assertEqual(a.semantic_profile('CH3OH.txt')['family'], 'meoh')

    def test_english_families(self):
        a = self.analysis
        self.assertEqual(a.semantic_profile('N2_1.txt')['family'], 'n2')
        self.assertEqual(a.semantic_profile('O2_slow.txt')['family'], 'o2')
        self.assertEqual(a.semantic_profile('MeOH.txt')['family'], 'meoh')

    def test_scan_from_tail_number(self):
        """尾号 1/2/5 = 0.1/0.2/0.5 V·s⁻¹（2025 与今年两种命名都是这个口径）。"""
        a = self.analysis
        self.assertAlmostEqual(a.semantic_profile('N2_1.txt')['scan'], 0.1)
        self.assertAlmostEqual(a.semantic_profile('N2_2.txt')['scan'], 0.2)
        self.assertAlmostEqual(a.semantic_profile('N2_5.txt')['scan'], 0.5)
        self.assertAlmostEqual(a.semantic_profile('氮气2.txt')['scan'], 0.2)

    def test_scan_from_explicit_rate(self):
        """直接写扫速的命名也要认，包括 mV 写法。"""
        a = self.analysis
        self.assertAlmostEqual(a.semantic_profile('氮气-0.2V.txt')['scan'], 0.2)
        self.assertAlmostEqual(a.semantic_profile('N2 0.5.txt')['scan'], 0.5)
        self.assertAlmostEqual(a.semantic_profile('氮气200mV.txt')['scan'], 0.2)

    def test_scan_strips_family_word_first(self):
        """``N2`` 里的 2 不能被当成 0.2 V·s⁻¹。

        这是最容易写错的一处：先剥族关键词再找扫速线索，否则 ``N2_1`` 会先
        命中那个 ``2``，三份 N₂ 数据全部被判成 0.2 V·s⁻¹。
        """
        a = self.analysis
        # 只有名字里的 _1 有意义；剥掉 N2 之后不应残留 0.2
        self.assertAlmostEqual(a.semantic_profile('N2_1.txt')['scan'], 0.1)
        # 不带尾号时，纯 N2 不应凭空判出扫速
        self.assertIsNone(a.semantic_profile('氮气.txt')['scan'])

    def test_stir_conditions(self):
        a = self.analysis
        self.assertEqual(a.semantic_profile('快速搅拌.txt')['cond'], 'fast')
        self.assertEqual(a.semantic_profile('低速搅拌.txt')['cond'], 'slow')
        self.assertEqual(a.semantic_profile('不搅拌.txt')['cond'], 'still')
        self.assertEqual(a.semantic_profile('O2_still.txt')['cond'], 'still')

    def test_nostir_beats_stir(self):
        """``不搅拌`` 必须判成 still，不能被「搅拌」吃掉判成 fast/slow。

        别名表里 still 排在最前就是为了这个；顺序错了会让「不搅拌」和
        「快速搅拌」同族同分，于是并列、谁也不 adop。
        """
        a = self.analysis
        for name in ('不搅拌.txt', '无搅拌.txt', '静止.txt', '静置-氧气.txt'):
            self.assertEqual(a.semantic_profile(name)['cond'], 'still', name)

    def test_stir_implies_o2_family(self):
        """只写「搅拌」没写「氧气」，也应归到 O₂ 组（N₂ 实验全程静置）。"""
        a = self.analysis
        self.assertEqual(a.semantic_profile('低速搅拌.txt')['family'], 'o2')

    def test_n2_has_no_stir_condition(self):
        """N₂ 组的搅拌条件不参与判别（文件名叫「氮气不搅拌」也不该干扰）。"""
        a = self.analysis
        prof = a.semantic_profile('氮气不搅拌.txt')
        self.assertEqual(prof['family'], 'n2')
        self.assertIsNone(prof['cond'])

    def test_unrelated_name(self):
        a = self.analysis
        prof = a.semantic_profile('随便什么.txt')
        self.assertIsNone(prof['family'])
        self.assertIsNone(prof['scan'])


class ResolveWithSemanticTests(unittest.TestCase):
    """``resolve_slots``：用户的真实文件名应全部自动匹配（fuzzy），不靠手点。"""

    @classmethod
    def setUpClass(cls):
        cls.analysis = support.load_module(TOOL, 'analysis')

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='pcal_echem_alias_'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _resolve(self):
        cfg = self.analysis.default_config()
        cfg['data_dir'] = str(self.tmp)
        return self.analysis.resolve_slots(str(self.tmp), cfg)

    def test_user_filenames_auto_match(self):
        """核心回归：七个中文文件名 → 七个正确槽位，全部自动采用。

        修复前这条必失败：七个槽位的 status 全是 ambiguous、rel 全是 None。
        """
        for name in USER_FILES:
            _write(self.tmp / name)
        detail = self._resolve()
        got = {k: v['rel'] for k, v in detail.items()}
        want = {slot: name for name, slot in USER_FILES.items()}
        self.assertEqual(got, want, '语义匹配派错槽位：\n  实际 %s\n  期望 %s'
                         % (got, want))
        for key, entry in detail.items():
            self.assertEqual(entry['status'], 'fuzzy',
                             '%s 没被自动采用：%s' % (key, entry['status']))
            self.assertGreaterEqual(entry['score'], 0.90)

    def test_scores_before_fix_would_have_failed(self):
        """把「纯字符串相似度」算一遍，确认它确实过不了门槛。

        这条防的是「以后有人删掉语义层、只看 dataloc.match_score」——
        一旦删掉，上面那条会失败，但失败信息会指向槽位对不上；这条则直接
        说明根因是字符串相似度不够（用户报告的就是这个）。
        """
        dataloc = support.load_module(TOOL, 'dataloc')
        accept = dataloc.FUZZY_ACCEPT
        pairs = [('N2_1.txt', '氮气1.txt'), ('O2_slow.txt', '低速搅拌.txt'),
                 ('MeOH.txt', 'CH3OH.txt')]
        for probe, real in pairs:
            s = dataloc.match_score(probe, real)
            self.assertLess(s, accept,
                            '字符串相似度 %.2f 竟然过了门槛（%.2f），'
                            '说明语义层可能不是必需的——请复核这条测试的前提'
                            % (s, accept))

    def test_all_slots_resolve_to_distinct_files(self):
        """七个槽位不许抢同一份文件（抢了就是「两条曲线用同一份数据」）。"""
        for name in USER_FILES:
            _write(self.tmp / name)
        detail = self._resolve()
        rels = [v['rel'] for v in detail.values() if v.get('rel')]
        self.assertEqual(len(rels), len(set(rels)), '有槽位共用同一份文件：%s' % rels)

    def test_missing_family_reports_missing(self):
        """只放了 N₂ 的三份，O₂ 与甲醇槽位必须如实报缺，不许乱塞。"""
        for name in ('氮气1.txt', '氮气2.txt', '氮气5.txt'):
            _write(self.tmp / name)
        detail = self._resolve()
        for key in ('file_o2_fast', 'file_o2_slow', 'file_o2_still', 'file_meoh'):
            entry = detail[key]
            self.assertIn(entry['status'], ('ambiguous', 'missing'),
                          '%s 没有对应文件却被填了 %s' % (key, entry['rel']))
            self.assertIsNone(entry['rel'])

    def test_semantic_conflict_is_not_auto_adopted(self):
        """只有 0.5 V·s⁻¹ 的 N₂ 数据时，0.1/0.2 的槽位**不许**自动采用它。

        宁可留在 ambiguous 让用户挑：把 0.5 的曲线填进 0.2 的槽位，表 1 的
        峰电流-扫速关系里就混进一条错位点，报告数字全错而界面上毫无异常。
        """
        _write(self.tmp / '氮气5.txt')
        detail = self._resolve()
        for key in ('file_n2_blank', 'file_n2_02'):
            self.assertNotEqual(detail[key]['status'], 'fuzzy',
                                '%s 自动采用了 0.5 V·s⁻¹ 的数据' % key)

    def test_tie_is_not_silently_picked(self):
        """两个文件同样匹配（同族同扫速）时判成 ambiguous，不按字母序默选。"""
        _write(self.tmp / '氮气.txt')
        _write(self.tmp / '氮气b.txt')
        detail = self._resolve()
        self.assertEqual(detail['file_n2_blank']['status'], 'ambiguous')
        self.assertIsNone(detail['file_n2_blank']['rel'])
        self.assertIn('多个', detail['file_n2_blank']['why'])


class HeaderCrossCheckTests(unittest.TestCase):
    """CHI 文件头是**硬证据**：名字说 0.2、文件头说 0.5，要能看出来。"""

    @classmethod
    def setUpClass(cls):
        cls.analysis = support.load_module(TOOL, 'analysis')
        cls.echem = support.load_module(TOOL, 'echem')

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='pcal_echem_hdr_'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_peek_params_reads_scan_rate(self):
        """``echem.peek_params`` 只读文件头就能拿到扫速，不解析数据区。"""
        p = self.echem.peek_params(str(FIXTURES / 'N2_2.txt'))
        self.assertAlmostEqual(p.get('scan_rate'), 0.2, places=6)
        self.assertIn('high_e', p)

    def test_peek_params_tolerates_junk(self):
        """不是 CHI 格式 / 文件不存在时返回空 dict，绝不抛异常。"""
        bad = self.tmp / 'x.txt'
        bad.write_text('这不是 CHI 导出的文件\n', encoding='utf-8')
        self.assertEqual(self.echem.peek_params(str(bad)), {})
        self.assertEqual(self.echem.peek_params(str(self.tmp / '不存在.txt')), {})
        self.assertEqual(self.echem.peek_params(''), {})

    def test_header_beats_misleading_name(self):
        """名字写成 N2_2、内容其实是 0.5 V·s⁻¹ → 必须靠文件头识别出来。

        把文件改名成槽位默认名是极常见的操作，纯看名字永远发现不了。
        """
        shutil.copyfile(FIXTURES / 'N2_1.txt', self.tmp / 'N2_1.txt')
        shutil.copyfile(FIXTURES / 'N2_5.txt', self.tmp / 'N2_2.txt')
        shutil.copyfile(FIXTURES / 'N2_5.txt', self.tmp / 'N2_5.txt')
        cfg = self.analysis.default_config()
        cfg['data_dir'] = str(self.tmp)
        detail = self.analysis.resolve_slots(str(self.tmp), cfg)
        bad = detail['file_n2_02']
        self.assertEqual(bad['status'], 'default', '名字命中应优先采用')
        self.assertTrue(bad.get('mismatch'), '文件头不符却没报出来')
        self.assertIn('0.5', bad['mismatch'])
        self.assertIn('0.2', bad['mismatch'])
        # 正确的那个不该误报
        self.assertFalse(detail['file_n2_05'].get('mismatch'))

    def test_mismatch_shows_up_in_warnings(self):
        """告警要流到 ``Analysis.warnings``，否则报告里看不到。"""
        shutil.copyfile(FIXTURES / 'N2_1.txt', self.tmp / 'N2_1.txt')
        shutil.copyfile(FIXTURES / 'N2_5.txt', self.tmp / 'N2_2.txt')
        shutil.copyfile(FIXTURES / 'N2_5.txt', self.tmp / 'N2_5.txt')
        cfg = self.analysis.default_config()
        cfg['data_dir'] = str(self.tmp)
        an = self.analysis.Analysis(cfg)
        an.run()
        hit = [w for w in an.warnings if '请核对' in w or 'v·s⁻¹' in w]
        self.assertTrue(hit, '扫速不符没有进告警：%s' % an.warnings)


class AssignWithSemanticTests(unittest.TestCase):
    """``rank_slots_for_file``：点一下中文文件名，也该派给它自己的槽位。"""

    @classmethod
    def setUpClass(cls):
        cls.analysis = support.load_module(TOOL, 'analysis')

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='pcal_echem_assign2_'))
        for name in USER_FILES:
            _write(self.tmp / name)
        self.cfg = self.analysis.default_config()
        self.cfg['data_dir'] = str(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_click_chinese_file_picks_right_slot(self):
        got = {}
        for rel, expected in USER_FILES.items():
            ranked = self.analysis.rank_slots_for_file(rel, self.cfg)
            self.assertTrue(ranked, '%s 没有候选' % rel)
            got[rel] = ranked[0]['key']
            top = ranked[0]
            self.assertGreaterEqual(
                top['score'], self.analysis.ASSIGN_MIN_SCORE,
                '%s → %s 分数太低（%.2f）' % (rel, top['key'], top['score']))
        self.assertEqual(got, USER_FILES, '点击派错槽位：\n  实际 %s\n  期望 %s'
                         % (got, USER_FILES))

    def test_conflict_is_explained(self):
        """明显不对的槽位，why 里要写清「是另一组的数据」，而不是只给个低分。"""
        ranked = self.analysis.rank_slots_for_file('快速搅拌.txt', self.cfg)
        n2 = [r for r in ranked if r['key'].startswith('file_n2')]
        self.assertTrue(n2)
        for r in n2:
            self.assertLess(r['score'], 0.5)
            self.assertIn('不匹配', r['why'])

    def test_unrelated_file_still_low(self):
        _write(self.tmp / '完全无关的东西.txt')
        ranked = self.analysis.rank_slots_for_file('完全无关的东西.txt', self.cfg)
        self.assertLess(ranked[0]['score'], self.analysis.ASSIGN_MIN_SCORE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
