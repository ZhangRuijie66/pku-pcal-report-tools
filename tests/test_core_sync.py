# -*- coding: utf-8 -*-
"""确认 11 个工具的核心排版件与 canonical 完全一致，行为也一致。"""
from __future__ import annotations

import unittest

import docx

from support import REPO_ROOT, load_module

TOOLS = (
    '燃烧热工具', '溶解热工具', '紫外光谱工具', '化学动力学工具',
    '电化学工具', '电导率工具', '蒸气压工具', '双液系工具',
    '偶极矩工具', '磁化率工具', '表面吸附工具',
)
FILES = ('omml.py', 'docxkit.py', 'workspace.py', 'profile.py')
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


if __name__ == '__main__':
    unittest.main()
