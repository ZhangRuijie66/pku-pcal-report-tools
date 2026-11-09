# -*- coding: utf-8 -*-
"""电化学：「点文件清单里的一行」该填给哪个槽位。

守的是 2026-11-09 用户报的真实 bug：

    电化学的点击选择有bug，点击之后只会把数据派给 N₂ 空白

根因（前端 ``assignToSlot()``）：它只在每个槽位的 ``suggestions`` 里找被点的
文件，而 ``suggestions`` 由 ``analysis.resolve_slots`` **仅在登记的文件名找不到
时**才填。七个槽位全部 ``status='default'``（默认文件名都在）时人人都是空数组，
于是所有候选同分 0，``sc > bestScore`` 一次都不成立，``bestKey`` 停在遍历的
第一个槽位 = ``file_n2_blank``（「N₂ 空白」）。点哪个文件都落到同一格。

修法：把打分搬到后端 ``analysis.rank_slots_for_file()``，用与「一键自动匹配」
完全同一套规则（``slot_tail`` + ``dataloc.match_score``）正向打分；前端只负责
按分高的填、分不够就把候选交还给用户。本文件守的就是这套口径。

⚠️ 这些用例必须能在 **status 全是 default** 的状态下通过——那才是用户遇到的
真实状态。只测「文件名对不上、suggestions 有内容」的路径会漏掉这个 bug。
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

#: 槽位默认文件名与目录里真实文件的对应关系（用户点左边的文件 → 该进右边的槽位）
EXPECTED = {
    'N2_1.txt': 'file_n2_blank',
    'N2_2.txt': 'file_n2_02',
    'N2_5.txt': 'file_n2_05',
    'O2_fast.txt': 'file_o2_fast',
    'O2_slow.txt': 'file_o2_slow',
    'O2_still.txt': 'file_o2_still',
    'MeOH.txt': 'file_meoh',
}


class AssignTargetTests(unittest.TestCase):
    """点在文件清单里的文件 → rank_slots_for_file 该把它排到哪个槽位。"""

    @classmethod
    def setUpClass(cls):
        cls.analysis = support.load_module(TOOL, 'analysis')
        cls.dataloc = support.load_module(TOOL, 'dataloc')
        cls.cfg = cls.analysis.default_config()
        cls.cfg['data_dir'] = str(FIXTURES)
        cls.files = cls.dataloc.list_data_files(str(FIXTURES), exts=('.txt',))
        cls.detail = cls.analysis.resolve_slots(str(FIXTURES), cls.cfg, cls.files)

    def test_fixtures_present(self):
        """fixtures 里有数据；缺了后面全是空断言。"""
        self.assertTrue(self.files, 'tests/fixtures/电化学 里没有 txt')

    def test_all_slots_are_default(self):
        """前提：这批数据下七个槽位全部按默认文件名读到（suggestions 全空）。

        这正是 bug 现场的状态。若哪天 fixtures 改了导致状态变化，这条会失败，
        提醒我们别在「非现场状态」下验证修复。
        """
        statuses = {k: v['status'] for k, v in self.detail.items()}
        self.assertEqual(set(statuses.values()), {'default'},
                         '槽位状态已不是全 default：%s' % statuses)
        self.assertEqual([v['suggestions'] for v in self.detail.values()],
                         [[]] * len(self.analysis.SLOT_KEYS),
                         'default 状态下 suggestions 应为空（bug 的成因）')

    def test_each_file_maps_to_its_own_slot(self):
        """核心回归：点哪个文件就填哪个槽位，**不许全落到第一个**。

        修复前这条必失败：七个文件全部返回 'file_n2_blank'。
        """
        got = {}
        for rel in EXPECTED:
            ranked = self.analysis.rank_slots_for_file(rel, self.cfg, self.detail)
            self.assertTrue(ranked, '%s 没算出任何候选' % rel)
            got[rel] = ranked[0]['key']
        self.assertEqual(got, EXPECTED,
                         '点击选择派错槽位：\n  实际 %s\n  期望 %s' % (got, EXPECTED))

    def test_not_everything_collapses_to_first_slot(self):
        """换个说法守同一件事：结果不能只有一个槽位（原 bug 的特征）。"""
        keys = {self.analysis.rank_slots_for_file(rel, self.cfg, self.detail)[0]['key']
                for rel in EXPECTED}
        self.assertGreater(len(keys), 1,
                           '所有文件都派给了同一个槽位：%s' % keys)

    def test_top_score_clears_accept_threshold(self):
        """自己目录里的同名文件，匹配度必须高到「可以直接填」。"""
        accept = self.dataloc.FUZZY_ACCEPT
        for rel in EXPECTED:
            top = self.analysis.rank_slots_for_file(rel, self.cfg, self.detail)[0]
            self.assertGreaterEqual(
                top['score'], accept,
                '%s → %s 只有 %.2f，太低' % (rel, top['key'], top['score']))

    def test_candidates_sorted_and_complete(self):
        """候选覆盖全部 7 个槽位、按分数降序，且带 current（原来是哪个文件）。"""
        ranked = self.analysis.rank_slots_for_file('N2_2.txt', self.cfg, self.detail)
        self.assertEqual(len(ranked), len(self.analysis.SLOT_KEYS))
        scores = [x['score'] for x in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True), '候选没按分数降序')
        self.assertEqual(ranked[0]['current'], 'N2_2.txt')
        for item in ranked:
            self.assertIn('label', item)
            self.assertTrue(item['label'], '槽位缺显示名')

    def test_dissimilar_file_yields_low_score(self):
        """与所有槽位都不像的文件，最高分要低于「敢替你填」的门槛。

        这样前端会走「请你自己挑」的分支，而不是硬塞进某一格。
        """
        ranked = self.analysis.rank_slots_for_file(
            '完全无关的东西.txt', self.cfg, self.detail)
        self.assertTrue(ranked)
        self.assertLess(ranked[0]['score'], self.analysis.ASSIGN_MIN_SCORE,
                        '无关文件分数太高（%.2f），会被静默填进去'
                        % ranked[0]['score'])

    def test_empty_rel(self):
        self.assertEqual(self.analysis.rank_slots_for_file('', self.cfg, self.detail), [])


class AssignEndpointTests(unittest.TestCase):
    """``POST /api/files/assign`` 的返回形状（前端靠它填下拉框）。

    ⚠️ 每个工具的 ``pcal/server.py`` 里都有 ``sys.path.insert(0, ROOT)`` 加
    ``from pcal import …``。导入 server 会把这个工具的 ``pcal`` 以**裸包名**
    注册进 ``sys.modules``，之后别的工具的 server（例如紫外光谱的
    ``from pcal import gcalc_bridge``）就会拿到**电化学的 pcal**，
    报 ``ImportError: cannot import name 'gcalc_bridge'``。

    这是测试装载逻辑的坑，不是产品 bug（真实运行时一个进程只跑一个模块）。
    本类导入 server 前后做快照/还原，别把污染漏给后面的测试文件——
    2026-11-09 加这组用例时就踩了：单独跑紫外光光谱 18 项全绿，
    全量跑却有 3 项 ImportError。
    """

    @classmethod
    def setUpClass(cls):
        cls._mods_before = set(sys.modules)
        cls.server = support.load_module(TOOL, 'server')
        cls.analysis = support.load_module(TOOL, 'analysis')
        # 别让测试碰到用户真实 settings.json / profile.json
        cls._saved = cls.server.STATE.get('config')
        cfg = cls.analysis.default_config()
        cfg['data_dir'] = str(FIXTURES)
        cls.server.STATE['config'] = cfg
        # 单独造一个目录：fixtures 的真实文件 + 一个与所有槽位都不像的 ZZZ.txt
        cls.tmp = tempfile.mkdtemp(prefix='pcal_assign_')
        for name in ('N2_1.txt', 'N2_2.txt', 'O2_slow.txt'):
            shutil.copyfile(FIXTURES / name, Path(cls.tmp) / name)
        (Path(cls.tmp) / 'ZZZ.txt').write_text('x\n', encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.server.STATE['config'] = cls._saved
        shutil.rmtree(cls.tmp, ignore_errors=True)
        # 还原 sys.modules：只删本类导入 server 时新出现的裸 'pcal' 及其子模块
        for name in [m for m in sys.modules if m not in cls._mods_before]:
            if name == 'pcal' or name.startswith('pcal.'):
                del sys.modules[name]

    def _assign(self, rel, dir_=None):
        q = {'dir': [dir_ or str(FIXTURES)]}
        return self.server._assign(q, {'rel': rel})

    def test_assign_returns_best_and_candidates(self):
        r = self._assign('O2_slow.txt')
        self.assertTrue(r['ok'], r)
        self.assertEqual(r['best']['key'], 'file_o2_slow')
        self.assertEqual(len(r['candidates']), len(self.analysis.SLOT_KEYS))

    def test_assign_missing_rel(self):
        r = self.server._assign({}, {})
        self.assertFalse(r['ok'])
        self.assertIn('rel', r['error'])

    def test_assign_file_outside_dir(self):
        r = self._assign('不存在.txt')
        self.assertFalse(r['ok'])
        self.assertIn('不在当前数据目录', r['error'])

    def test_assign_leaves_low_score_without_best(self):
        """分数不够时 ``best`` 必须是 None，前端才会走「请你自己挑」的分支。

        这是「不许静默塞进某一格」的保证：宁可让用户多点一下，也不能像原来
        那样一律塞给 N₂ 空白。
        """
        r = self._assign('ZZZ.txt', self.tmp)
        self.assertTrue(r['ok'], r)
        self.assertIsNone(r['best'],
                          'ZZZ.txt 与所有槽位都不像，却仍然替用户决定了：%r'
                          % (r['best'],))
        self.assertTrue(r['candidates'], '至少要把候选带回去让用户挑')


class AssignRouteTests(unittest.TestCase):
    """路由必须挂在 POST 上（写盘端点不能挂 GET，见项目审计结论 §24.4）。

    用 AST 取 ``Handler.do_GET`` / ``do_POST`` 的函数体再判定——
    直接在整份源码里 search 会命中 ``_assign`` 自己的 docstring，
    那种断言只在「恰好没写进注释」时成立，属于假通过。
    """

    @classmethod
    def setUpClass(cls):
        import ast
        src = (support.REPO_ROOT / TOOL / 'pcal' / 'server.py').read_text(
            encoding='utf-8')
        tree = ast.parse(src)
        cls.bodies = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name != 'Handler':
                continue
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in (
                        'do_GET', 'do_POST'):
                    cls.bodies[item.name] = ast.get_source_segment(src, item) or ''

    def test_methods_found(self):
        self.assertEqual(set(self.bodies), {'do_GET', 'do_POST'},
                         '没找到 Handler.do_GET / do_POST')

    def test_route_is_post_only(self):
        self.assertIn('/api/files/assign', self.bodies['do_POST'],
                      '/api/files/assign 没挂在 do_POST 上')
        self.assertNotIn('/api/files/assign', self.bodies['do_GET'],
                         '/api/files/assign 不能挂在 do_GET 上')

    def test_body_read_once(self):
        """``self._body()`` 只能读一次，第二次会永久阻塞（审计结论 §24.4）。

        精确切出这一个 ``if`` 分支：从 ``/api/files/assign`` 那行到下一个
        ``if u.path ==`` 之前。按固定字数切会把下一个分支的 ``self._body()``
        也算进来，那种断言会一直失败（或换个写法后假通过）。
        """
        seg = self.bodies['do_POST']
        start = seg.index("'/api/files/assign'")
        rest = seg[start:]
        end = rest.find('if u.path ==', 1)
        branch = rest if end < 0 else rest[:end]
        self.assertEqual(branch.count('self._body()'), 1,
                         '这个分支读了 %d 次请求体：%r'
                         % (branch.count('self._body()'), branch))


class AssignFrontendTests(unittest.TestCase):
    """前端必须走这个端点，不能退回「只在 suggestions 里找」的老做法。"""

    @classmethod
    def setUpClass(cls):
        cls.js = (support.REPO_ROOT / TOOL / 'web' / 'app.js').read_text(
            encoding='utf-8')

    def test_frontend_calls_assign_endpoint(self):
        self.assertIn('/api/files/assign', self.js,
                      '前端没有调用 /api/files/assign')

    def test_frontend_no_longer_scans_suggestions(self):
        """老代码的特征：循环所有槽位、只看自己的 suggestions、取第一个最高分。

        ``bestScore = -1`` 起步、同分不更新，是「全落到第一个槽位」的成因。
        """
        seg = self.js[self.js.index('async function assignToSlot'):]
        seg = seg[:seg.index('\n}\n') + 3]
        self.assertNotIn('suggestions', seg,
                         'assignToSlot 又在读 suggestions 了（那正是 bug 成因）')
        self.assertNotIn('bestScore = -1', seg)

    def test_low_score_does_not_silently_assign(self):
        """分不够时不能硬填：必须有「请你自己挑」的分支。"""
        seg = self.js[self.js.index('async function assignToSlot'):]
        seg = seg[:seg.index('\n}\n') + 3]
        self.assertIn('if (!best)', seg,
                      '缺少「没有足够像的槽位」的分支，会静默塞进某一格')


if __name__ == '__main__':
    unittest.main(verbosity=2)
