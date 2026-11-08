# -*- coding: utf-8 -*-
"""共享层回归：数据目录可移植定位 + 文件模糊匹配 + 搜索。

守的是两条真实踩过的坑：

1. **模糊匹配不能提前饱和**（紫外光谱 P0）：同名文件在文件夹 ``1/`` 与 ``2/``
   里各有一份，若先算分再 ``min(1.0, score + 同目录分)``，两者都封顶成 1.0，
   排序退化成按路径字母序 → 静默选了错的那份，整份报告数字全错却不报错。
2. **默认数据目录必须一定存在**：可移植包解压到别人电脑上，绝不能
   FileNotFoundError，也不能指到作者机器上的绝对路径。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support                                        # noqa: E402

TOOLS = ('燃烧热工具', '溶解热工具', '紫外光谱工具', '化学动力学工具',
         '电化学工具', '电导率工具', '蒸气压工具', '双液系工具',
         '偶极矩工具', '磁化率工具', '表面吸附工具')


def _load(tool='紫外光谱工具'):
    return support.load_module(tool, 'dataloc')


class TestFuzzyMatch(unittest.TestCase):
    """match_score / rank_candidates / auto_match。"""

    def setUp(self):
        self.dl = _load()

    def test_weights_sum_to_one_and_not_saturated(self):
        """满分也只能到 1.0，且同目录加成必须真的体现在分数差上。"""
        dl = self.dl
        target = '1/2026-10-20 & 10-00-00-A3-0.5.txt'
        same_dir = '1/2026-10-21 & 12-40-01-A3-0.5.txt'
        other_dir = '2/2026-10-21 & 12-40-01-A3-0.5.txt'
        a = dl.match_score(target, same_dir)
        b = dl.match_score(target, other_dir)
        self.assertLessEqual(a, 1.0)
        self.assertLess(b, 1.0)
        # 关键断言：同目录那份分数严格更高（早先的实现会并列）
        self.assertGreater(a, b)

    def test_rank_prefers_same_directory(self):
        dl = self.dl
        target = '1/2026-10-20 & 10-00-00-A3-0.5.txt'
        files = ['2/2026-10-21 & 12-40-01-A3-0.5.txt',
                 '1/2026-10-21 & 12-40-01-A3-0.5.txt',
                 '1/2026-10-21 & 12-41-01-A3-5.txt']
        ranked = dl.rank_candidates(target, files)
        self.assertEqual(ranked[0]['rel'], '1/2026-10-21 & 12-40-01-A3-0.5.txt')
        # A3-5 与 A3-0.5 是不同浓度，不能被判成自动采用
        weak = [r for r in ranked if r['rel'].endswith('A3-5.txt')][0]
        self.assertFalse(weak['auto'])

    def test_timestamp_change_still_auto_matches(self):
        """只改时间戳（换一天重测）应仍然自动采用。"""
        dl = self.dl
        target = '2026-10-14 & 17-01-51-氘灯.txt'
        files = ['2026-11-03 & 09-12-33-氘灯.txt']
        self.assertEqual(dl.auto_match(target, files),
                         '2026-11-03 & 09-12-33-氘灯.txt')

    def test_copy_suffix_stripped(self):
        """`- 副本` / `(2)` 不该把同一份文件判成两个。"""
        dl = self.dl
        self.assertEqual(dl.split_stamp('a/氘灯 - 副本.txt')[1], '氘灯')
        self.assertEqual(dl.split_stamp('a/氘灯(2).txt')[1], '氘灯')

    def test_different_concentration_not_auto(self):
        """A3-0.5 与 A3-5 / A3-50 互不自动采用（浓度差会毁掉整条 Beer 拟合）。"""
        dl = self.dl
        target = 'A3-0.5.txt'
        for other in ('A3-5.txt', 'A3-10.txt', 'A3-50.txt'):
            self.assertNotEqual(dl.auto_match(target, [other]), other,
                                '%s 不该被当成 %s' % (other, target))

    def test_tail_number_kept_by_default(self):
        """尾号 `_数字` 有语义，默认必须保留。

        mod-c 报告的真实 bug：电化学的 N2_1 / N2_2 / N2_5 是三个不同扫速
        （0.1/0.2/0.5 V/s）。剥成 N2 后三个槽位同分并列、互抢同一份文件，
        峰电流与电化学活性面积全错，界面上却看不出区别。
        """
        dl = self.dl
        # 语义后缀必须不同
        tags = {dl.split_stamp('N2_%d.txt' % i)[1] for i in (1, 2, 5)}
        self.assertEqual(len(tags), 3, 'N2_1/2/5 的语义后缀被剥成同一个了：%s' % tags)
        # 互不自动采用
        self.assertIsNone(dl.auto_match('N2_1.txt', ['N2_2.txt']))
        self.assertIsNone(dl.auto_match('N2_1.txt', ['N2_5.txt']))

    def test_tail_number_strippable_on_demand(self):
        """需要剥的时候（确实当副本处理）给开关，不硬编码成唯一行为。"""
        dl = self.dl
        self.assertEqual(dl.split_stamp('氘灯_2.txt')[1], '氘灯_2')
        self.assertEqual(
            dl.split_stamp('氘灯_2.txt', strip_tail_number=True)[1], '氘灯')

    def test_ambiguous_copy_suffix_still_stripped(self):
        """`(2)` / `- 副本` 无歧义，仍然要剥（不然同一份文件算两个）。"""
        dl = self.dl
        self.assertEqual(dl.split_stamp('a/氘灯(2).txt')[1], '氘灯')
        self.assertEqual(dl.split_stamp('a/氘灯 - 副本.txt')[1], '氘灯')

    def test_no_match_returns_none(self):
        dl = self.dl
        self.assertIsNone(dl.auto_match('苯甲酸.csv', ['完全无关的名字.txt']))


class TestSearch(unittest.TestCase):
    """search_files：文件多时要能搜。"""

    def setUp(self):
        self.dl = _load()

    def test_substring_first(self):
        dl = self.dl
        files = ['2026-10-21 & 12-40-01-A3-0.5.txt',
                 '2026-10-21 & 12-41-01-A3-5.txt',
                 '2026-10-21 & 12-50-00-乙醇.txt']
        got = dl.search_files(files, 'A3-5')
        self.assertEqual(got[0], '2026-10-21 & 12-41-01-A3-5.txt')

    def test_subsequence_and_empty(self):
        dl = self.dl
        files = ['2026-10-21 & 12-45-01-A3-0.5.txt', '氘灯.txt']
        # 「a35」不是子串，但按顺序出现在 a3-0.5 里 → 子序列命中
        got = dl.search_files(files, 'a35')
        self.assertTrue(got, '子序列应能命中 a3-0.5')
        self.assertIn('2026-10-21 & 12-45-01-A3-0.5.txt', got)
        # 去掉分隔符后整串也能命中（A3-0.5 → a305）
        self.assertIn('2026-10-21 & 12-45-01-A3-0.5.txt',
                      dl.search_files(files, 'a305'))
        # 空查询返回前 N 项，不报错
        self.assertEqual(len(dl.search_files(files, '')), len(files))

    def test_no_result(self):
        dl = self.dl
        self.assertEqual(dl.search_files(['a.txt'], 'zzzzzz'), [])


class TestListAndResolve(unittest.TestCase):
    """list_data_files / resolve_rel：列目录与路径穿越。"""

    def setUp(self):
        self.dl = _load()

    def test_list_and_traversal(self):
        dl = self.dl
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sub').mkdir()
            (root / 'a.csv').write_text('x', encoding='utf-8')
            (root / 'sub' / 'b.txt').write_text('x', encoding='utf-8')
            (root / 'note.md').write_text('x', encoding='utf-8')
            files = dl.list_data_files(tmp)
            self.assertIn('a.csv', files)
            self.assertIn('sub/b.txt', files)          # 递归 + 正斜杠
            self.assertNotIn('note.md', files)         # 非数据后缀被滤掉
            # 正常相对路径能解析
            self.assertTrue(dl.resolve_rel(tmp, 'sub/b.txt'))
            # 穿越到外面一律拒绝
            self.assertEqual(dl.resolve_rel(tmp, '../../secret.txt'), '')

    def test_empty_dir_safe(self):
        dl = self.dl
        self.assertEqual(dl.list_data_files(''), [])
        self.assertEqual(dl.list_data_files('Z:/不存在的目录'), [])


class TestPortableDataDir(unittest.TestCase):
    """find_data_dir：换机器后必须返回一个存在的目录，且绝不写死盘符。"""

    def setUp(self):
        self.dl = _load()

    def test_returns_existing_dir(self):
        dl = self.dl
        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp) / '某工具'
            tool.mkdir()
            got = dl.find_data_dir(str(tool))
            self.assertTrue(os.path.isdir(got), '必须返回一个存在的目录')

    def test_prefers_saved_dir(self):
        dl = self.dl
        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp) / '某工具'
            tool.mkdir()
            saved = Path(tmp) / '我的数据'
            saved.mkdir()
            got = dl.find_data_dir(str(tool), saved=str(saved))
            self.assertEqual(os.path.normcase(got), os.path.normcase(str(saved)))

    def test_ignores_missing_saved(self):
        """记住的目录被删了（换机器）不能返回它。"""
        dl = self.dl
        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp) / '某工具'
            tool.mkdir()
            got = dl.find_data_dir(str(tool), saved=str(Path(tmp) / '已被删除'))
            self.assertTrue(os.path.isdir(got))
            self.assertNotIn('已被删除', got)

    def test_prefers_suite_data_folder(self):
        """可移植包：同级放一个「数据」文件夹时应优先用它。"""
        dl = self.dl
        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp) / '某工具'
            tool.mkdir()
            data = Path(tmp) / '数据'
            data.mkdir()
            got = dl.find_data_dir(str(tool))
            self.assertEqual(os.path.normcase(got), os.path.normcase(str(data)))


class TestNoHardcodedPaths(unittest.TestCase):
    """共享层源码里不许出现绝对盘符（可移植性底线）。

    只看**真实代码**：文档字符串里的示例路径（`"D:\\\\...\\\\1 燃烧热"`）
    是说明文字，不是运行时行为，不该算违规。
    """

    def test_core_files_have_no_drive_letters(self):
        import ast
        import re
        pattern = re.compile(r"['\"][A-Za-z]:[\\/]")
        core = support.REPO_ROOT / '_core'
        for name in ('dataloc.py', 'filepick.py', 'profile.py', 'workspace.py'):
            path = core / name
            if not path.exists():
                continue
            text = path.read_text(encoding='utf-8')
            tree = ast.parse(text)
            # 收集所有 docstring 的行号区间，跳过去
            doc_lines = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef)):
                    body = getattr(node, 'body', None) or []
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                            and isinstance(body[0].value.value, str)):
                        start = body[0].lineno
                        end = getattr(body[0], 'end_lineno', start)
                        doc_lines.update(range(start, end + 1))
            hits = []
            for lineno, line in enumerate(text.splitlines(), 1):
                if lineno in doc_lines:
                    continue
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                if pattern.search(line):
                    hits.append(stripped[:90])
            self.assertEqual(hits, [], '%s 里有硬编码盘符：%s' % (name, hits[:3]))


class TestAllToolsHaveCore(unittest.TestCase):
    """11 个模块都必须有共享层副本（sync_core 之后）。"""

    def test_each_tool_has_dataloc_and_filepick(self):
        for tool in TOOLS:
            for fname in ('dataloc.py', 'filepick.py'):
                path = support.REPO_ROOT / tool / 'pcal' / fname
                self.assertTrue(path.exists(), '%s 缺少 pcal/%s' % (tool, fname))
            js = support.REPO_ROOT / tool / 'web' / 'files.js'
            self.assertTrue(js.exists(), '%s 缺少 web/files.js' % tool)

    def test_dataloc_behaviour_identical_across_tools(self):
        """同一套断言在任一副本上都要成立（防止副本分叉）。"""
        target = '1/2026-10-20 & 10-00-00-A3-0.5.txt'
        files = ['1/2026-10-21 & 12-40-01-A3-0.5.txt',
                 '2/2026-10-21 & 12-40-01-A3-0.5.txt']
        scores = {}
        for tool in TOOLS:
            dl = support.load_module(tool, 'dataloc')
            scores[tool] = (round(dl.match_score(target, files[0]), 6),
                            round(dl.match_score(target, files[1]), 6))
        values = set(scores.values())
        self.assertEqual(len(values), 1, '各模块 dataloc 行为不一致：%s' % scores)


if __name__ == '__main__':
    unittest.main(verbosity=2)
