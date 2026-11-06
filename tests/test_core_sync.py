# -*- coding: utf-8 -*-
"""确认 11 个工具的核心排版件与版本号真源一致，行为也一致。"""
from __future__ import annotations

import importlib.util
import re
import sys
import unittest

import docx

from support import REPO_ROOT, load_module, load_pcal

TOOLS = (
    '燃烧热工具', '溶解热工具', '紫外光谱工具', '化学动力学工具',
    '电化学工具', '电导率工具', '蒸气压工具', '双液系工具',
    '偶极矩工具', '磁化率工具', '表面吸附工具',
)
FILES = ('version.py', 'omml.py', 'docxkit.py', 'workspace.py', 'profile.py')
WEB_TOOLS = ('化学动力学工具', '蒸气压工具', '双液系工具',
             '偶极矩工具', '表面吸附工具', '磁化率工具')
WEB_FILES = ('web_draft.js',)
CORE = REPO_ROOT / '_core'

OMML_CORPUS = (
    r'\lg x',
    r'\frac{n^{2}h}{8mL^{2}}',
    r'\frac{m}{M(KNO_{3})}',
    r'K^{\ominus}',
    r'0.0023\ K',
    r'0.01214\ S\cdot m^{2}\cdot mol^{-1}',
    r'H_{2}O',
    r'h_{ii}',
    r'\Delta_{vap}H_{m}',
    r'\Gamma\Xi\Upsilon',
    r'\left( \frac{a}{b} \right)',
)


def normalized(path):
    return path.read_text(encoding='utf-8').replace('\r\n', '\n')


def load_module_spec(path, name):
    """按文件路径载入单个模块（不经包，用于 canonical 的 _core/version.py）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError('无法载入 %s' % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# `_core` 没有 __init__.py（是命名空间包），这里按文件路径载入 sync_core。
sync_core = load_module_spec(CORE / 'sync_core.py', 'pcal_sync_core')


def header_runs(dk, header):
    doc = docx.Document()
    p = doc.add_paragraph()
    dk.ReportBuilder._write_header(p, header, 10.5)
    return [(r.text, bool(r.italic), bool(r.font.superscript),
             bool(r.font.subscript)) for r in p.runs]


class CoreSyncTests(unittest.TestCase):
    def test_every_copy_matches_canonical(self):
        for tool in TOOLS:
            for name in FILES:
                with self.subTest(tool=tool, file=name):
                    self.assertEqual(
                        normalized(REPO_ROOT / tool / 'pcal' / name),
                        normalized(CORE / name),
                        '%s/%s 与 canonical 不一致，运行 '
                        'python _core/sync_core.py --apply' % (tool, name))
        for tool in WEB_TOOLS:
            with self.subTest(tool=tool, file='draft.js'):
                self.assertEqual(
                    normalized(REPO_ROOT / tool / 'web' / 'draft.js'),
                    normalized(CORE / 'web_draft.js'),
                    '%s/web/draft.js 与 canonical 不一致' % tool)

    def test_omml_behavior_is_identical(self):
        baseline = None
        for tool in TOOLS:
            omml = load_module(tool, 'omml')
            got = tuple(omml.to_omml_body(tex) for tex in OMML_CORPUS)
            if baseline is None:
                baseline = got
            else:
                self.assertEqual(got, baseline, '%s 的 OMML 输出与其它工具不同' % tool)

    def test_docxkit_behavior_is_identical(self):
        baseline = None
        for tool in TOOLS:
            dk = load_module(tool, 'docxkit')
            got = (
                tuple(map(tuple, dk._split_caption_runs('A–c'))),
                tuple(map(tuple, dk._split_caption_runs('N', '2'))),
                tuple(map(tuple, dk._split_caption_runs('Q', 's'))),
                dk._sub_chunks('ij'),
                dk._sub_chunks('sam'),
                tuple(header_runs(dk, 'm_{Ni-1}/g')),
                tuple(header_runs(dk, 't_{1/2} / s')),
                tuple(header_runs(dk, [
                    ('ln(', {}), ('p', {'italic': True}),
                    ('/p^{⊖})', {}),
                ])),
            )
            if baseline is None:
                baseline = got
            else:
                self.assertEqual(got, baseline,
                                 '%s 的题注/表头行为与其它工具不同' % tool)

    def test_canonical_keeps_known_fixes(self):
        omml_src = normalized(CORE / 'omml.py')
        for marker in (r"r'\ominus'", '_tail_is_symbolic',
                       "all(c in 'ij'", "'vap'", "'pF'", "'D'"):
            self.assertIn(marker, omml_src, 'omml 缺少修复标记：%s' % marker)
        docx_src = normalized(CORE / 'docxkit.py')
        for marker in ('rows = list(rows)', 'isinstance(text, (list, tuple))',
                       "sub['italic'] = True", "all(c in 'ij'", 'cut = None'):
            self.assertIn(marker, docx_src, 'docxkit 缺少修复标记：%s' % marker)
        ws_src = normalized(CORE / 'workspace.py')
        for marker in ('def snapshot(', 'def save(', 'sha256_file', 'CORE_VERSION'):
            self.assertIn(marker, ws_src, 'workspace 缺少：%s' % marker)

    # ------------------------------------------------------------ 版本号独占真源
    def test_canonical_version_is_single_source(self):
        """`_core/version.py` 是真源：APP_VERSION 只能在这里定义一次。"""
        src = normalized(CORE / 'version.py')
        self.assertEqual(src.count('APP_VERSION = '), 1,
                         '_core/version.py 里 APP_VERSION 应该只定义一次')
        self.assertRegex(src, r"APP_VERSION = '\d+\.\d+\.\d+'")
        self.assertRegex(src, r"RELEASE_DATE = '\d{4}-\d{2}-\d{2}'")

    def test_every_tool_version_behaves_identically(self):
        """11 个工具的 pcal/version.py 与 canonical 行为一致（不只是字节一致）。"""
        canonical = load_module_spec(REPO_ROOT / '_core' / 'version.py',
                                     'canonical_version_behaviour')
        baseline = (canonical.APP_VERSION, canonical.RELEASE_DATE,
                    canonical.tag_for(canonical.APP_VERSION),
                    canonical.changelog_filename(canonical.APP_VERSION),
                    canonical.version_tuple('v1.0.10'),
                    canonical.is_newer('1.0.10', '1.0.9'))
        self.assertIsNotNone(baseline[4])
        for tool in TOOLS:
            with self.subTest(tool=tool):
                mod = load_module(tool, 'version')
                got = (mod.APP_VERSION, mod.RELEASE_DATE,
                       mod.tag_for(mod.APP_VERSION),
                       mod.changelog_filename(mod.APP_VERSION),
                       mod.version_tuple('v1.0.10'),
                       mod.is_newer('1.0.10', '1.0.9'))
                self.assertEqual(got, baseline,
                                 '%s 的 pcal/version.py 行为与 canonical 不同' % tool)
                self.assertEqual(mod.APP_VERSION, canonical.APP_VERSION)

    def test_every_tool_exposes_package_version(self):
        """各工具 `pcal.__version__` 必须等于真源 APP_VERSION。"""
        canonical = load_module_spec(REPO_ROOT / '_core' / 'version.py',
                                     'canonical_version_for_init')
        for tool in TOOLS:
            with self.subTest(tool=tool):
                module = sys.modules[load_pcal(tool)]
                self.assertTrue(hasattr(module, '__version__'),
                                '%s/pcal/__init__.py 没有 __version__' % tool)
                self.assertEqual(module.__version__, canonical.APP_VERSION,
                                 '%s/pcal 的 __version__ 不是真源版本' % tool)

    def test_tool_init_refers_to_version_module(self):
        """`pcal/__init__.py` 的 __version__ 应引用 pcal/version.py，而不是硬编码。"""
        pattern = re.compile(
            r'^[ \t]*from[ \t]+\.version[ \t]+import[ \t]+APP_VERSION'
            r'[ \t]+as[ \t]+__version__[ \t]*$', re.M)
        for tool in TOOLS:
            with self.subTest(tool=tool):
                src = normalized(REPO_ROOT / tool / 'pcal' / '__init__.py')
                self.assertRegex(
                    src, pattern,
                    '%s/pcal/__init__.py 的 __version__ 应写成 '
                    'from .version import APP_VERSION as __version__' % tool)
                self.assertNotRegex(
                    src, r"^[ \t]*__version__[ \t]*=[ \t]*['\"]",
                    '%s/pcal/__init__.py 还在硬编码 __version__' % tool)

    def test_manifest_records_every_synced_file(self):
        """`_core/core_manifest.json` 必须记下所有 FILES（含 version.py）。"""
        import json
        data = json.loads((CORE / 'core_manifest.json').read_text(encoding='utf-8'))
        for name in FILES:
            with self.subTest(file=name):
                self.assertIn(name, data['files'],
                              'core_manifest.json 的 files 里缺 %s' % name)
                self.assertEqual(data['files'][name], sync_core.canonical_digest(name),
                                 '%s 的清单哈希与 canonical 不一致' % name)
        self.assertIn('web_draft.js', data['web_files'])
        self.assertEqual(tuple(data['tools']), TOOLS)


class SyncRewriteTests(unittest.TestCase):
    """`_core/sync_core.py` 的改写逻辑：保留 docstring/__all__/行尾风格。"""

    def test_rewrite_replaces_hardcoded_version(self):
        src = ('# -*- coding: utf-8 -*-\n'
               '"""某工具。"""\n\n'
               "__version__ = '1.0.0'\n")
        got = sync_core.rewrite_init_text(src)
        self.assertIn('from .version import APP_VERSION as __version__', got)
        self.assertNotIn("__version__ = '1.0.0'", got)
        self.assertIn('"""某工具。"""', got)

    def test_rewrite_inserts_after_docstring_keeping_all(self):
        src = ('# -*- coding: utf-8 -*-\n'
               '"""某工具。"""\n\n'
               "__all__ = ['a', 'b']\n")
        got = sync_core.rewrite_init_text(src)
        self.assertIn('from .version import APP_VERSION as __version__', got)
        self.assertIn("__all__ = ['a', 'b']", got)
        # 插在 docstring 之后、__all__ 之前
        self.assertLess(got.index('from .version'), got.index('__all__'))
        # 改完还能被 Python 正常解析
        compile(got, '<test>', 'exec')

    def test_rewrite_keeps_existing_import_untouched(self):
        src = ('# -*- coding: utf-8 -*-\n'
               '"""某工具。"""\n\n'
               'from .version import APP_VERSION as __version__\n\n'
               "__all__ = ['a']\n")
        self.assertEqual(sync_core.rewrite_init_text(src), src)

    def test_rewrite_is_idempotent(self):
        src = '# -*- coding: utf-8 -*-\n"""某工具。"""\n\n__version__ = \'0.1.0\'\n'
        once = sync_core.rewrite_init_text(src)
        self.assertEqual(sync_core.rewrite_init_text(once), once)

    def test_init_version_state_detects_hardcoded(self):
        import tempfile
        from pathlib import Path as _Path
        with tempfile.TemporaryDirectory() as tmp:
            path = _Path(tmp) / '__init__.py'
            path.write_text("# -*- coding: utf-8 -*-\n"
                            "__version__ = '1.0.0'\n", encoding='utf-8')
            state, why = sync_core.init_version_state(path)
            self.assertEqual(state, 'DIFF', '硬编码 1.0.0 应报 DIFF（要求改成引用真源）')
            self.assertIn('硬编码', why)
            path.write_text("# -*- coding: utf-8 -*-\n"
                            '"""没有版本号。"""\n', encoding='utf-8')
            state, _why = sync_core.init_version_state(path)
            self.assertEqual(state, 'MISSING')
            path.write_text('# -*- coding: utf-8 -*-\n'
                            'from .version import APP_VERSION as __version__\n',
                            encoding='utf-8')
            state, _why = sync_core.init_version_state(path)
            self.assertEqual(state, 'OK')

    def test_write_preserves_crlf(self):
        """写入必须保留目标文件原有的 CRLF/LF 风格。"""
        import tempfile
        from pathlib import Path as _Path
        with tempfile.TemporaryDirectory() as tmp:
            path = _Path(tmp) / 'x.py'
            path.write_bytes(b'# -*- coding: utf-8 -*-\r\n__version__ = \'1.0.0\'\r\n')
            text = 'line1\nline2\n'
            sync_core.write_text_with_same_newline(path, text)
            self.assertEqual(path.read_bytes(), b'line1\r\nline2\r\n')
            # LF 目标保持 LF
            path.write_bytes(b'a\nb\n')
            sync_core.write_text_with_same_newline(path, text)
            self.assertEqual(path.read_bytes(), b'line1\nline2\n')

    def test_digest_ignores_line_endings(self):
        """比较时忽略 CRLF/LF，避免整文件因换行符差异出现在 git diff 里。"""
        import tempfile
        from pathlib import Path as _Path
        with tempfile.TemporaryDirectory() as tmp:
            lf = _Path(tmp) / 'lf.py'
            crlf = _Path(tmp) / 'crlf.py'
            lf.write_bytes(b'a\nb\n')
            crlf.write_bytes(b'a\r\nb\r\n')
            self.assertEqual(sync_core.digest(lf), sync_core.digest(crlf))


if __name__ == '__main__':
    unittest.main()
