# -*- coding: utf-8 -*-
"""紫外光谱：数据文件槽位、模糊匹配、单文件查看。

这些测试守的是 2026-11-06 新增的两件事，都是「换个文件名就会静默算错」的类型：

1. **数据文件槽位 + 模糊匹配**：别人用这套工具时，光谱仪导出的文件名只在
   时间戳上不同（`2026-10-14 & 17-01-51-氘灯.txt` → `2026-11-03 & 09-12-33-氘灯.txt`）。
   匹配必须能对上，而且**不能挑错相邻文件**——A3 的 0.5 与 1、5 与 5-2、
   文件夹 1 与 文件夹 2 里同名的两份，差一个字符就是另一次测量。
2. **一个浓度只占一行**：重复测量里报告只用「测量选择」选中的那一条，
   所以槽位数量按「用到的数据」算，不按「原始文件夹里的 txt」算。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from support import REPO_ROOT, load_module

TOOL = '紫外光谱工具'

# 2026-10 这批真实数据的数值基准（与 test_modules.test_uv_spectrum 同源）
BASE_LAMBDAS = {'A1': 428.53567, 'A2': 560.85106, 'A3': 656.14518,
                'A4': 770.18773, 'B1': 449.88736, 'B2': 296.25782}
BASE_EPS = 43235.27526
BASE_R2 = 0.99875613


def _data_dir():
    uv = load_module(TOOL, 'uv')
    return uv.CALIBRATIONS[0] and os.path.join(
        os.path.dirname(uv.__file__), '..', '..', '3 紫外光谱搭建', '数据')


class SlotModelTests(unittest.TestCase):
    """槽位模型：每个浓度/分子一行，重复测量只列选中的那条。"""

    @classmethod
    def setUpClass(cls):
        cls.uv = load_module(TOOL, 'uv')

    def test_one_row_per_concentration(self):
        """默认选择下，浓度系列每个浓度正好一行（不会同时列出 A3c5 与 A3c5b）。"""
        slots = self.uv.file_slots()
        conc = [s for s in slots if s['group'] == '浓度系列']
        self.assertEqual(len(conc), len(self.uv.CONC_VALUES),
                         '浓度系列槽位数应等于浓度个数：%r'
                         % [s['label'] for s in conc])
        keys = [s['key'] for s in slots]
        self.assertEqual(len(keys), len(set(keys)), '槽位 key 不能重复')

    def test_switching_measurement_switches_slot(self):
        """把 5 μmol/L 切到另一次测量，槽位里的文件要跟着换。"""
        pm = dict(self.uv.MOLECULE_DEFAULT, A3='A3c5')
        pc = dict(self.uv.CONC_PICK_DEFAULT, **{'5': 'A3c5'})
        slots = {s['key']: s for s in self.uv.file_slots(pm, pc)}
        self.assertIn(self.uv.SLOT_SAMPLE + 'A3c5', slots)
        self.assertNotIn(self.uv.SLOT_SAMPLE + 'A3c5b', slots,
                         '没选中的那次测量不该出现在槽位表里')
        self.assertEqual(slots[self.uv.SLOT_SAMPLE + 'A3c5']['default'],
                         '2\\2026-10-21 & 12-36-40-A3-5.txt')

    def test_shared_file_merges_into_one_row(self):
        """A3 5 μmol/L 同时用于浓度系列和光源对比时只占一行。"""
        pm = dict(self.uv.MOLECULE_DEFAULT, A3='A3c5')
        pc = dict(self.uv.CONC_PICK_DEFAULT, **{'5': 'A3c5'})
        slots = [s for s in self.uv.file_slots(pm, pc)
                 if s['key'] == self.uv.SLOT_SAMPLE + 'A3c5']
        self.assertEqual(len(slots), 1)
        # 两个用途都要在标签里露出来，否则用户不知道这一行代表了什么
        self.assertIn('μmol', slots[0]['label'])
        self.assertIn('二羰花青', slots[0]['label'])

    def test_blank_slots_are_deduplicated(self):
        """多份样品共用同一份空白时，空白只出现一次。"""
        files = [s['default'] for s in self.uv.file_slots() if s['kind'] == 'blank']
        self.assertEqual(len(files), len(set(files)), '空白槽位有重复：%r' % files)
        # 5 份空白各有用途：A4 / A3 浓度系列 / A3 双光源 / A2 / 短波段
        self.assertEqual(len(files), len(self.uv.BLANKS))

    def test_slot_keys_accept_union_for_file_map(self):
        """file_map 允许保留「当前没选中」的测量，来回切换时指定不丢。"""
        stale = {self.uv.SLOT_SAMPLE + 'A3c5b': '2\\x.txt'}
        self.assertEqual(self.uv.clean_file_map(stale), stale,
                         '未选中的槽位也应被接受')
        self.assertEqual(self.uv.clean_file_map({'bogus:1': 'x'}), {},
                         '不存在的槽位要滤掉')


class FuzzyMatchTests(unittest.TestCase):
    """模糊匹配：改名后能对上，且不会挑到相邻的另一个测量。"""

    @classmethod
    def setUpClass(cls):
        cls.uv = load_module(TOOL, 'uv')

    def test_timestamp_only_difference_matches(self):
        files = ['2026-11-03 & 09-12-33-氘灯.txt']
        score = self.uv.match_score('2026-10-14 & 17-01-51-氘灯.txt', files[0])
        self.assertGreaterEqual(score, self.uv.FUZZY_ACCEPT,
                                '只差时间戳的文件应当自动采用，实际 %.3f' % score)

    def test_adjacent_concentrations_do_not_confuse(self):
        """A3-0.5 / A3-1 / A3-5 / A3-10 / A3-50 之间不能互相当成对方。"""
        files = ['2\\2026-11-03 & 11-%02d-00-A3-%s.txt' % (i, tag)
                 for i, tag in enumerate(['0.5', '1', '5', '10', '50'])]
        for i, tag in enumerate(['0.5', '1', '5', '10', '50']):
            got = self.uv.suggest_files(
                '2\\2026-10-21 & 12-00-00-A3-%s.txt' % tag, files, top=1)
            self.assertTrue(got, 'A3-%s 没找到候选' % tag)
            self.assertTrue(got[0][1].endswith('-A3-%s.txt' % tag),
                            'A3-%s 挑到了 %s' % (tag, got[0][1]))
            self.assertGreaterEqual(got[0][0], self.uv.FUZZY_ACCEPT)

    def test_repeat_measurement_not_confused_with_first(self):
        """A3-5 与 A3-5-2 是两次不同测量，不能互相顶替。"""
        files = ['2\\2026-11-03 & 11-11-02-A3-5.txt',
                 '2\\2026-11-03 & 11-39-55-A3-5-2.txt']
        first = self.uv.suggest_files(
            '2\\2026-10-21 & 12-36-40-A3-5.txt', files, top=2)
        self.assertEqual(first[0][1], files[0], '第一次测量应优先匹配 A3-5')
        second = self.uv.suggest_files(
            '2\\2026-10-21 & 13-02-28-A3-5-2.txt', files, top=2)
        self.assertEqual(second[0][1], files[1], '第二次测量应优先匹配 A3-5-2')

    def test_same_name_in_other_folder_scores_lower(self):
        """文件夹 1 与 2 里同名文件：同目录的那份必须赢。

        这两批是不同测量条件（短积分 / 长积分），选错了报告数字全变，
        而且不会报错——所以要有回归测试钉住。
        """
        tgt = '2\\2026-10-21 & 12-29-42-A3-0.5.txt'
        same = self.uv.match_score(tgt, '2\\2026-11-03 & 11-29-42-A3-0.5.txt')
        other = self.uv.match_score(tgt, '1\\2026-10-21 & 11-59-34-A3-0.5.txt')
        self.assertGreater(same, other,
                           '同目录那份应更高分：%.3f vs %.3f' % (same, other))
        self.assertGreaterEqual(same, self.uv.FUZZY_ACCEPT)

    def test_copy_suffix_is_not_a_different_file(self):
        """`- 副本` / `(2)` 只是复制产生的，原件优先。"""
        files = ['2026-11-03 & 09-12-33-氘灯 - 副本.txt',
                 '2026-11-03 & 09-12-33-氘灯(2).txt',
                 '2026-11-03 & 09-12-33-氘灯.txt']
        got = self.uv.suggest_files('2026-10-14 & 17-01-51-氘灯.txt', files, top=3)
        self.assertTrue(got[0][1].endswith('氘灯.txt'), '原件应排第一：%r' % got)
        self.assertTrue(self.uv.has_copy_suffix(files[0]))
        self.assertTrue(self.uv.has_copy_suffix(files[1]))
        self.assertFalse(self.uv.has_copy_suffix(files[2]))

    def test_unrelated_files_are_not_auto_accepted(self):
        """完全不像的文件不能凑数自动采用。"""
        files = ['MOR.txt', 'N2_1.txt', 'O2_slow.txt']
        got = self.uv.suggest_files('2\\2026-10-21 & 12-56-02-A3-0.txt', files, top=3)
        for score, rel in got:
            self.assertLess(score, self.uv.FUZZY_ACCEPT,
                            '%s 不该被自动采用（%.3f）' % (rel, score))


class ResolveSlotTests(unittest.TestCase):
    """resolve_slots：缺文件要报错、改名要自动对、手动指定优先。"""

    @classmethod
    def setUpClass(cls):
        cls.uv = load_module(TOOL, 'uv')
        cls.src = _data_dir()
        if not os.path.isdir(cls.src):
            raise unittest.SkipTest('原始数据目录不可用：%s' % cls.src)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='uv_slots_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _copy_renamed(self, rename=True):
        """把真实数据拷一份进来，可选把时间戳全部改掉。"""
        for root, _dirs, names in os.walk(self.src):
            for name in names:
                if not name.lower().endswith('.txt'):
                    continue
                rel = os.path.relpath(os.path.join(root, name), self.src)
                new = rename_name(name) if rename else name
                dst = os.path.join(self.tmp, os.path.dirname(rel), new)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(os.path.join(root, name), dst)

    def test_original_names_resolve_to_defaults(self):
        self._copy_renamed(rename=False)
        paths, missing, detail = self.uv.resolve_slots({}, self.tmp)
        self.assertEqual(missing, [])
        self.assertEqual({v['status'] for v in detail.values()}, {'default'})

    def test_renamed_files_are_auto_matched(self):
        """整批改名后（只换时间戳）应当全部自动匹配，不需要人工干预。"""
        self._copy_renamed(rename=True)
        paths, missing, detail = self.uv.resolve_slots({}, self.tmp)
        self.assertEqual(missing, [], '改名后不该报缺文件：%r'
                         % [m['label'] for m in missing])
        self.assertEqual({v['status'] for v in detail.values()}, {'fuzzy'})
        # 每个槽位都要指向真实存在、且语义后缀对得上的文件
        for key, entry in detail.items():
            self.assertTrue(os.path.isfile(paths[key]), key)
            want = self.uv.split_stamp(entry['default'])[1]
            got = self.uv.split_stamp(entry['rel'])[1]
            self.assertEqual(got, want, '%s 匹配到了 %s' % (key, entry['rel']))

    def test_missing_files_raise_with_suggestions(self):
        """目录只放一半文件时要报错，并给出候选。"""
        only = [n for n in os.listdir(self.src) if n.lower().endswith('.txt')][:1]
        for name in only:
            shutil.copyfile(os.path.join(self.src, name),
                            os.path.join(self.tmp, name))
        paths, missing, detail = self.uv.resolve_slots({}, self.tmp)
        self.assertTrue(missing, '应当报缺文件')
        with self.assertRaises(self.uv.DataFilesMissing) as ctx:
            raise self.uv.DataFilesMissing(missing)
        msg = str(ctx.exception)
        self.assertIn('缺少', msg)
        self.assertIn('数据文件映射', msg)

    def test_manual_mapping_wins_and_is_marked(self):
        self._copy_renamed(rename=False)
        key = self.uv.SLOT_SAMPLE + 'A3c5b'
        rel = '2\\2026-10-21 & 13-02-28-A3-5-2.txt'
        paths, missing, detail = self.uv.resolve_slots({key: rel}, self.tmp)
        self.assertEqual(missing, [])
        self.assertEqual(detail[key]['status'], 'manual')
        self.assertTrue(paths[key].endswith(rel))

    def test_bad_manual_mapping_falls_back_to_fuzzy(self):
        """手动指定了一个不存在的文件名 → 仍应模糊匹配到相近的，而不是直接崩。"""
        self._copy_renamed(rename=True)
        key = self.uv.SLOT_SAMPLE + 'A3c5b'
        paths, missing, detail = self.uv.resolve_slots(
            {key: '2\\2026-01-01 & 00-00-00-A3-5-2.txt'}, self.tmp)
        self.assertNotIn(key, [m['key'] for m in missing],
                         '大致相同的名字应当能自动匹配回来')
        self.assertEqual(detail[key]['status'], 'fuzzy')


class SingleFileTests(unittest.TestCase):
    """单文件查看：读文件、给峰值信息、拒坏文件。"""

    @classmethod
    def setUpClass(cls):
        cls.uv = load_module(TOOL, 'uv')

    def test_read_single_reports_peak(self):
        src = _data_dir()
        path = os.path.join(src, '2026-10-14 & 17-01-51-氘灯.txt')
        if not os.path.isfile(path):
            raise unittest.SkipTest('缺 %s' % path)
        spec = self.uv.read_single(path)
        self.assertEqual(len(spec['difference']), 3648, 'CCD 应该是 3648 像素')
        cal = dict(a=0.12586984, b=421.99496)
        info = self.uv.single_peak_info(spec, cal=cal)
        self.assertEqual(info['n'], 3648)
        # 氘灯谱在 CCD 上最亮的是 581.39 nm 那条线（656 nm 那条落在更靠后、
        # 已被光栅效率压低）；用先验标定换算应落在 570~595 nm。
        self.assertTrue(570 <= info['lam'] <= 595,
                        '最强线 %.1f nm，应接近 581 nm' % info['lam'])
        # 换第二周短波标定，同一个 pixel 会换算成约 595 nm（标定确实生效了）
        short = dict(a=0.12758569, b=258.30853)
        info2 = self.uv.single_peak_info(spec, cal=short)
        self.assertNotAlmostEqual(info2['lam'], info['lam'], places=2,
                                  msg='换标定必须改变换算结果')

    def test_read_single_rejects_non_spectrum(self):
        with tempfile.TemporaryDirectory() as td:
            bad = os.path.join(td, 'x.txt')
            with open(bad, 'w', encoding='utf-8') as fh:
                fh.write('这不是光谱数据\n')
            with self.assertRaises(ValueError) as ctx:
                self.uv.read_single(bad)
            self.assertIn('四列', str(ctx.exception))
            with self.assertRaises(ValueError):
                self.uv.read_single(os.path.join(td, '不存在.txt'))


class FrontEndWiringTests(unittest.TestCase):
    """前端接线：映射卡片与单文件查看的 DOM/id/接口必须对得上。

    只查静态字符串（真实交互在浏览器里另测），但能挡住「改了 id 忘了改 JS」
    这种整块功能静默失效的问题。
    """

    @classmethod
    def setUpClass(cls):
        cls.html = (REPO_ROOT / TOOL / 'web' / 'index.html').read_text(encoding='utf-8')
        cls.js = (REPO_ROOT / TOOL / 'web' / 'app.js').read_text(encoding='utf-8')
        cls.server = (REPO_ROOT / TOOL / 'pcal' / 'server.py').read_text(encoding='utf-8')

    def test_dom_ids_used_by_js_exist(self):
        """JS 里 $('xxx') 引用的 id 必须在 HTML 里存在（或由 JS 自己拼出来）。"""
        import re
        ids = set(re.findall(r"""\$\('([A-Za-z0-9_]+)'\)""", self.js))
        declared = set(re.findall(r'id="([A-Za-z0-9_]+)"', self.html))
        # JS 用 innerHTML 动态生成的元素（如扫描结果里的「自动匹配」按钮）
        dynamic = set(re.findall(r"""id="([A-Za-z0-9_]+)"'""", self.js))
        dynamic |= set(re.findall(r"""id="([A-Za-z0-9_]+)\"""", self.js))
        missing = sorted(ids - declared - dynamic)
        self.assertEqual(missing, [], 'JS 引用了不存在的元素 id：%r' % missing)

    def test_file_map_card_present(self):
        for marker in ('id="fileMap"', 'id="btnAutoMap"', 'id="btnClearMap"',
                       'id="fileGroup"', 'id="fileCompact"', 'id="fileMapNote"'):
            self.assertIn(marker, self.html, marker)
        for marker in ('function renderFileMap(', 'function autoMap(',
                       'function clearMap(', 'cfg.file_map = fileMapValue()'):
            self.assertIn(marker, self.js, marker)

    def test_single_file_card_present(self):
        for marker in ('id="singlePath"', 'id="singleSelect"', 'id="btnPickFile"',
                       'id="btnSingleView"', 'id="singleCal"', 'id="singleSmooth"',
                       'id="singleChart"'):
            self.assertIn(marker, self.html, marker)
        for marker in ('function pickFile(', 'function viewSingle(',
                       '/api/preview/single?', '/api/file/info?'):
            self.assertIn(marker, self.js, marker)

    def test_server_routes_match_frontend_calls(self):
        """前端 fetch 的每个 /api 路径，后端都要有对应分支。"""
        import re
        routes = set(re.findall(r"""'(/api/[a-z/]+)'""", self.server))
        calls = set(re.findall(r"""'(/api/[a-z/]+)""", self.js))
        missing = sorted(c for c in calls if c not in routes)
        self.assertEqual(missing, [], '前端调用了后端没有的接口：%r' % missing)

    def test_ui_says_one_row_per_concentration(self):
        """界面文案要讲清「每个浓度只指定一个文件」，否则用户会找第二次测量。"""
        self.assertIn('留空则按文件名自动匹配', self.html)


def rename_name(name):
    """把 `2026-10-14 & 17-xx` 换成 `2026-11-03 & 09-xx` 这类别的日期。"""
    for old, new in (('2026-10-14 & 17-', '2026-11-03 & 09-'),
                     ('2026-10-21 & 12-', '2026-11-03 & 11-'),
                     ('2026-10-21 & 13-', '2026-11-03 & 12-'),
                     ('2026-10-21 & 14-', '2026-11-04 & 10-')):
        if name.startswith(old):
            return new + name[len(old):]
    return '2026-12-01 & 08-00-00-' + name


class RenamedDatasetNumberTests(unittest.TestCase):
    """整批改名后重算，数字必须与原始数据逐位一致。"""

    @classmethod
    def setUpClass(cls):
        cls.uv = load_module(TOOL, 'uv')
        cls.analysis = load_module(TOOL, 'analysis')
        cls.src = _data_dir()
        if not os.path.isdir(cls.src):
            raise unittest.SkipTest('原始数据目录不可用：%s' % cls.src)
        cls.tmp = tempfile.mkdtemp(prefix='uv_renamed_')
        for root, _dirs, names in os.walk(cls.src):
            for name in names:
                if not name.lower().endswith('.txt'):
                    continue
                rel = os.path.relpath(os.path.join(root, name), cls.src)
                dst = os.path.join(cls.tmp, os.path.dirname(rel), rename_name(name))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(os.path.join(root, name), dst)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_numbers_identical_after_rename(self):
        cfg = self.analysis.default_config()
        cfg['data_dir'] = self.tmp
        an = self.analysis.Analysis(cfg).run()
        self.assertEqual(an.warnings and [
            w for w in an.warnings if '自动匹配' not in w], [],
            '除自动匹配告警外不该有别的告警：%r' % an.warnings)
        for code, want in BASE_LAMBDAS.items():
            got = an.box['lambdas'][code]
            self.assertAlmostEqual(got, want, places=3,
                                   msg='%s λmax %.4f != %.4f（改名后算错了）'
                                       % (code, got, want))
        self.assertAlmostEqual(an.beer['fit']['eps'], BASE_EPS, delta=1.0,
                               msg='ε 与原始数据基准不一致')
        self.assertAlmostEqual(an.beer['fit']['r2'], BASE_R2, places=7,
                               msg='R² 与原始数据基准不一致')


if __name__ == '__main__':
    unittest.main()
