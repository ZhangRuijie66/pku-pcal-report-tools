# -*- coding: utf-8 -*-
"""版本号真源（_core/version.py）与一致性检查（_core/check_version.py）的回归测试。

原则：**绝不改动仓库里的真文件**。
`_core/version.py` 只用 spec 载入后做纯函数断言；`check_version.run_checks()`
要造坏数据的用例全部在 `tempfile.TemporaryDirectory` 里的临时副本上做。
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from support import REPO_ROOT

TOOLS = (
    '燃烧热工具', '溶解热工具', '紫外光谱工具', '化学动力学工具',
    '电化学工具', '电导率工具', '蒸气压工具', '双液系工具',
    '偶极矩工具', '磁化率工具', '表面吸附工具',
)
SCAN_TARGETS = (
    '物化实验报告工具/portal.py',
    '_tools/launcher.py',
    'README.md',
    'make_portable.py',
)
COPIED_ROOT_FILES = ('_core/version.py', '_core/sync_core.py',
                     '_core/core_manifest.json')
COPIED_ROOT_DIRS = ('更新日志',)


def load_by_path(name, path):
    """按文件路径载入模块（不 import 包，避免动到 sys.path 的行为差异）。"""
    path = Path(path)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError('无法载入 %s' % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


version = load_by_path('pcal_canonical_version', REPO_ROOT / '_core' / 'version.py')
check_version = load_by_path('pcal_check_version',
                            REPO_ROOT / '_core' / 'check_version.py')


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)


def read(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


def make_repo_copy(dst):
    """在 dst 造一份「干净的安装根」最小副本（只含一致性检查要用到的文件）。"""
    dst = Path(dst)
    for rel in COPIED_ROOT_FILES:
        src = REPO_ROOT / rel
        if src.is_file():
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    for rel in COPIED_ROOT_DIRS:
        src = REPO_ROOT / rel
        if src.is_dir():
            shutil.copytree(src, dst / rel)
    for tool in TOOLS:
        for name in ('version.py', '__init__.py'):
            src = REPO_ROOT / tool / 'pcal' / name
            if not src.is_file():
                continue
            target = dst / tool / 'pcal' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    for rel in SCAN_TARGETS:
        src = REPO_ROOT / rel
        if src.is_file():
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    return dst


def levels_vs_titles(results):
    return [(level, title) for level, title, _detail in results]


def fails(results):
    return [(title, detail) for level, title, detail in results if level == 'fail']


def assert_fail(testcase, results, keyword, extra=''):
    """断言有 fail，且某条 fail 的标题+详情里含 keyword。"""
    bad = fails(results)
    testcase.assertTrue(bad, '本应报 fail，实际：%r' % (levels_vs_titles(results),))
    hit = [item for item in bad if keyword in item[0] or keyword in item[1]]
    testcase.assertTrue(
        hit, '没有任何 fail 提到 %r，实际 fail：%r%s' % (keyword, bad, extra))
    return hit


class VersionPureTests(unittest.TestCase):
    """`_core/version.py` 的版本号算术语义。"""

    def test_version_tuple_normal(self):
        self.assertEqual(version.version_tuple('1.0.0'), (1, 0, 0))
        self.assertEqual(version.version_tuple('v1.0.10'), (1, 0, 10))
        self.assertEqual(version.version_tuple('  V2.3.4  '), (2, 3, 4))
        self.assertEqual(version.version_tuple('10.20.30'), (10, 20, 30))

    def test_version_tuple_invalid(self):
        for bad in (None, '', '1.0', '1.0.0.0', 'v1.0.x', '1.0.0-rc1',
                    'v2.0.0-rc1', 'abc', '1.1', '3.10'):
            with self.subTest(text=bad):
                self.assertIsNone(version.version_tuple(bad))

    def test_normalize(self):
        self.assertEqual(version.normalize('v1.0.0'), '1.0.0')
        self.assertEqual(version.normalize('1.2.3'), '1.2.3')
        self.assertEqual(version.normalize(' v1.0.10 '), '1.0.10')
        # 解析不了时原样返回（去空白），不抛异常
        self.assertEqual(version.normalize('dev'), 'dev')
        self.assertEqual(version.normalize(None), '')

    def test_is_newer_semantic_order(self):
        # 关键：按整数比，不是按字符串比
        self.assertTrue(version.is_newer('1.0.10', '1.0.9'))
        self.assertFalse(version.is_newer('1.0.9', '1.0.10'))
        self.assertTrue(version.is_newer('v1.0.1', '1.0.0'))
        self.assertTrue(version.is_newer('1.1.0', '1.0.99'))
        self.assertTrue(version.is_newer('2.0.0', '1.99.99'))
        self.assertFalse(version.is_newer('1.0.0', '1.0.0'))
        self.assertFalse(version.is_newer('0.9.9', '1.0.0'))

    def test_is_newer_invalid_is_never_update(self):
        for candidate, current in (('abc', '1.0.0'), ('1.0.0', 'abc'),
                                   (None, '1.0.0'), ('1.0.0', None),
                                   ('v2.0.0-rc1', '1.0.0')):
            with self.subTest(candidate=candidate, current=current):
                self.assertFalse(version.is_newer(candidate, current))

    def test_tag_for(self):
        self.assertEqual(version.tag_for('1.0.0'), 'v1.0.0')
        self.assertEqual(version.tag_for('v1.0.10'), 'v1.0.10')

    def test_changelog_filename(self):
        self.assertEqual(version.changelog_filename('1.0.0'), 'CHANGELOG_v1_0_0.md')
        self.assertEqual(version.changelog_filename('v1.0.10'),
                         'CHANGELOG_v1_0_10.md')
        self.assertEqual(version.changelog_relpath('1.0.0'),
                         '更新日志/CHANGELOG_v1_0_0.md')
        # 4.10 与 4.1 不能撞名
        self.assertNotEqual(version.changelog_filename('4.10.0'),
                            version.changelog_filename('4.1.0'))

    def test_bump(self):
        self.assertEqual(version.bump('1.0.0', 'patch'), '1.0.1')
        self.assertEqual(version.bump('1.0.9', 'patch'), '1.0.10')
        self.assertEqual(version.bump('1.0.0', 'minor'), '1.1.0')
        self.assertEqual(version.bump('1.2.3', 'minor'), '1.3.0')
        self.assertEqual(version.bump('1.2.3', 'major'), '2.0.0')
        self.assertEqual(version.bump('v1.2.3', 'patch'), '1.2.4')
        self.assertEqual(version.bump('1.2.3'), '1.2.4')          # 默认 patch
        with self.assertRaises(ValueError):
            version.bump('1.2.3', 'release')                     # 未知类型要报错

    def test_summary_matches_declaration(self):
        info = version.summary()
        self.assertEqual(info['version'], version.APP_VERSION)
        self.assertEqual(info['tag'], 'v' + version.APP_VERSION)
        self.assertEqual(info['changelog'],
                         '更新日志/' + version.changelog_filename(version.APP_VERSION))
        self.assertEqual(info['release_date'], version.RELEASE_DATE)


class CheckVersionRealRepoTests(unittest.TestCase):
    """在真实仓库上跑一致性检查：只允许 ok/warn，不允许 fail。"""

    def test_no_fail_in_real_repo(self):
        results = check_version.run_checks(REPO_ROOT)
        self.assertTrue(results, 'run_checks 必须返回结果')
        bad = fails(results)
        self.assertEqual(bad, [], '真实仓库的版本号检查有 fail：%r' % (bad,))
        for level, title, detail in results:
            self.assertIn(level, ('ok', 'warn'))
            self.assertIsInstance(title, str)
            self.assertIsInstance(detail, str)

    def test_real_repo_version_matches_declaration(self):
        """check_version 解析出来的版本号必须等于 import 出来的版本号。"""
        info = check_version.read_declared_version(REPO_ROOT)
        self.assertEqual(info['version'], version.APP_VERSION)
        self.assertEqual(info['date'], version.RELEASE_DATE)
        self.assertEqual(check_version.current_version(REPO_ROOT),
                         version.version_tuple(version.APP_VERSION))

    def test_main_returns_zero_on_real_repo(self):
        out = []
        with contextlib.redirect_stdout(_Collector(out)):
            code = check_version.main([])
        self.assertEqual(code, 0, '真实仓库 check_version.main() 应为 0：%s'
                         % ''.join(out))
        text = ''.join(out)
        self.assertIn('OK', text)
        self.assertIn('0 FAIL', text)
        self.assertNotIn('[FAIL]', text)
        self.assertNotIn('✗', text)

    def test_glyph_fallback_for_gbk(self):
        """GBK 控制台没有 ✓/⚠/✗ → 必须退回 [OK]/[WARN]/[FAIL]。"""
        with contextlib.redirect_stdout(_Collector([], encoding='gbk')):
            symbols = check_version.console_glyphs()
        self.assertEqual(symbols, {'ok': '[OK]', 'warn': '[WARN]',
                                   'fail': '[FAIL]'})
        with contextlib.redirect_stdout(_Collector([], encoding='utf-8')):
            symbols = check_version.console_glyphs()
        self.assertEqual(symbols['ok'], '✓')


class _Collector:
    """给 contextlib.redirect_stdout 用的假 stdout（可以限定编码）。"""

    def __init__(self, sink, encoding='utf-8'):
        self._sink = sink
        self.encoding = encoding

    def write(self, text):
        if self.encoding:
            text.encode(self.encoding)        # 模拟 GBK 控制台会抛 UnicodeEncodeError
        self._sink.append(text)

    def flush(self):
        pass


class CheckVersionBrokenCopyTests(unittest.TestCase):
    """在临时副本上逐项破坏，对应 check 必须报 fail。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_repo_copy(Path(self._tmp.name) / 'repo')

    def run_checks(self):
        return check_version.run_checks(self.root)

    # 0. 副本本身是干净的（否则后面的破坏用例没有意义）
    def test_clean_copy_has_no_fail(self):
        results = self.run_checks()
        self.assertEqual(fails(results), [],
                         '临时副本基线就有 fail：%r' % (fails(results),))

    # 1. 删掉当前版本的 CHANGELOG
    def test_missing_changelog_fails(self):
        name = version.changelog_filename(version.APP_VERSION)
        (self.root / '更新日志' / name).unlink()
        results = self.run_checks()
        hit = assert_fail(self, results, '更新日志')
        self.assertTrue(any('CHANGELOG' in detail or '更新日志' in title
                            for title, detail in hit),
                        '应指出更新日志缺失：%r' % (hit,))

    # 2. 更新日志里出现比当前更高的版本（版本回退/漏改）
    def test_future_changelog_version_fails(self):
        higher = version.bump(version.APP_VERSION, 'minor')
        write(self.root / '更新日志' /
              version.changelog_filename(higher),
              '# v%s\n\n- **类型**：功能\n' % higher)
        hit = assert_fail(self, self.run_checks(), '版本回退')
        self.assertTrue(any(higher in detail for _title, detail in hit),
                        '应指出更高版本 %s：%r' % (higher, hit))

    # 3. 某个工具的 pcal/version.py 与真源不同步
    def test_tool_version_copy_differs_fails(self):
        tool = TOOLS[-1]
        path = self.root / tool / 'pcal' / 'version.py'
        text = read(path)
        write(path, text.replace("APP_VERSION = '%s'" % version.APP_VERSION,
                                "APP_VERSION = '0.0.9'", 1))
        hit = assert_fail(self, self.run_checks(), '工具版本副本')
        self.assertTrue(any(tool in detail for _title, detail in hit),
                        '应指出是哪个工具：%r' % (hit,))

    # 4. 某个工具的 __version__ 写错
    def test_tool_init_version_wrong_fails(self):
        tool = TOOLS[0]
        path = self.root / tool / 'pcal' / '__init__.py'
        write(path, '# -*- coding: utf-8 -*-\n"""测试用。"""\n\n'
                    "__version__ = '0.0.1'\n")
        hit = assert_fail(self, self.run_checks(), '工具 __version__')
        self.assertTrue(any(tool in detail for _title, detail in hit),
                        '应指出是哪个工具：%r' % (hit,))

    # 5. 工具的 __init__.py 干脆没有 __version__
    def test_tool_init_missing_version_fails(self):
        tool = TOOLS[1]
        write(self.root / tool / 'pcal' / '__init__.py',
              '# -*- coding: utf-8 -*-\n"""没有 __version__ 的包。"""\n')
        hit = assert_fail(self, self.run_checks(), '工具 __version__')
        self.assertTrue(any(tool in detail for _title, detail in hit),
                        '应指出是哪个工具：%r' % (hit,))

    # 6. 清单被清空 / 缺 version.py
    def test_empty_manifest_fails(self):
        path = self.root / '_core' / 'core_manifest.json'
        write(path, json.dumps({'version': '1.0.0', 'files': {}},
                               ensure_ascii=False, indent=2) + '\n')
        assert_fail(self, self.run_checks(), '核心清单')

    def test_manifest_without_version_entry_fails(self):
        path = self.root / '_core' / 'core_manifest.json'
        data = json.loads(read(path))
        data['files'].pop('version.py', None)
        write(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        hit = assert_fail(self, self.run_checks(), '核心清单')
        self.assertTrue(any('version.py' in detail for _title, detail in hit),
                        '应指出缺 version.py：%r' % (hit,))

    def test_manifest_hash_mismatch_fails(self):
        path = self.root / '_core' / 'core_manifest.json'
        data = json.loads(read(path))
        data['files']['version.py'] = '0' * 64
        write(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        assert_fail(self, self.run_checks(), '核心清单')

    # 7. README 里残留旧版本号（旧版本 = 更新日志里出现过的版本）
    def test_stale_version_string_in_readme_fails(self):
        old = '0.9.0'
        write(self.root / '更新日志' / version.changelog_filename(old),
              '# v%s\n\n- **类型**：修复\n' % old)
        readme = self.root / 'README.md'
        write(readme, read(readme) + '\n历史版本：v%s\n' % old)
        hit = assert_fail(self, self.run_checks(), '旧版本号残留')
        self.assertTrue(any(old in detail for _title, detail in hit),
                        '应指出残留的旧版本号 %s：%r' % (old, hit))

    # 8. 「无关」的小版本号（1.1 版本库号、3.10 Python 版本）不许误判
    def test_unrelated_small_versions_are_ignored(self):
        readme = self.root / 'README.md'
        write(readme, read(readme) + '\n需要 Python 3.10、SQLite 1.1 版本库。\n')
        self.assertEqual(fails(self.run_checks()), [])

    # 9. CHANGELOG 首行不是 `# v<cur>`
    def test_changelog_bad_first_line_fails(self):
        name = version.changelog_filename(version.APP_VERSION)
        path = self.root / '更新日志' / name
        write(path, '# 更新说明\n\n- **类型**：功能\n')
        assert_fail(self, self.run_checks(), '更新日志内容')

    # 10. CHANGELOG 缺少「类型：」一行
    def test_changelog_missing_type_line_fails(self):
        name = version.changelog_filename(version.APP_VERSION)
        path = self.root / '更新日志' / name
        write(path, '# v%s\n\n- **日期**：2026-11-07\n' % version.APP_VERSION)
        hit = assert_fail(self, self.run_checks(), '更新日志内容')
        self.assertTrue(any('类型' in detail for _title, detail in hit),
                        '应指出缺「类型」：%r' % (hit,))

    # 11. APP_VERSION 写成两段式
    def test_two_part_app_version_fails(self):
        path = self.root / '_core' / 'version.py'
        text = read(path)
        write(path, text.replace("APP_VERSION = '%s'" % version.APP_VERSION,
                                "APP_VERSION = '1.0'", 1))
        assert_fail(self, self.run_checks(), '版本真源')

    def test_bad_release_date_fails(self):
        path = self.root / '_core' / 'version.py'
        text = read(path)
        write(path, text.replace("RELEASE_DATE = '%s'" % version.RELEASE_DATE,
                                "RELEASE_DATE = '2026/11/07'", 1))
        hit = assert_fail(self, self.run_checks(), '版本真源')
        self.assertTrue(any('RELEASE_DATE' in detail for _title, detail in hit),
                        '应指出 RELEASE_DATE：%r' % (hit,))

    # 12. main() 在坏副本上应该返回 1（并在 GBK 控制台退回 [FAIL] 而不是崩）
    def test_main_returns_one_on_broken_copy(self):
        name = version.changelog_filename(version.APP_VERSION)
        (self.root / '更新日志' / name).unlink()
        out = []
        with contextlib.redirect_stdout(_Collector(out, encoding='gbk')):
            code = check_version.main(['--root', str(self.root)])
        self.assertEqual(code, 1, '坏副本上 main() 应返回 1：%s' % ''.join(out))
        text = ''.join(out)
        self.assertIn('[FAIL]', text)
        self.assertNotIn('✗', text)           # GBK 控制台不许出现画不出来的符号

    def test_missing_version_source_does_not_crash(self):
        (self.root / '_core' / 'version.py').unlink()
        results = self.run_checks()
        assert_fail(self, results, '版本真源')


class CheckVersionRobustnessTests(unittest.TestCase):
    """单个检查抛异常也要有结果，不能整个中断。"""

    def test_checks_list_shape(self):
        self.assertIsInstance(check_version.CHECKS, list)
        self.assertEqual(len(check_version.CHECKS), 8,
                         '契约列了 8 项检查，实际 %d 项'
                         % len(check_version.CHECKS))
        for check in check_version.CHECKS:
            self.assertTrue(callable(check))

    def test_run_checks_survives_missing_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = check_version.run_checks(Path(tmp) / 'nope')
            self.assertTrue(results)
            self.assertTrue(any(level == 'fail' for level, _t, _d in results))

    def test_run_checks_result_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo_copy(Path(tmp) / 'repo')
            for item in check_version.run_checks(root):
                self.assertEqual(len(item), 3)
                level, title, detail = item
                self.assertIn(level, ('ok', 'warn', 'fail'))
                self.assertTrue(title)
                self.assertIsInstance(detail, str)


if __name__ == '__main__':
    unittest.main()
