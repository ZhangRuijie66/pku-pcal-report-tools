# -*- coding: utf-8 -*-
"""PDF 导出：路径复用/强制重转/错误提示（不调用真实 Word）。"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from support import REPO_ROOT


def load_pdf():
    path = REPO_ROOT / '_core' / 'pdf.py'
    spec = importlib.util.spec_from_file_location('pcal_pdf_test', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PdfUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pdf = load_pdf()

    def test_fake_word_and_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            docx = Path(td) / '报告.docx'
            docx.write_bytes(b'PK fake docx')
            calls = []

            def runner(source, target, timeout):
                calls.append((source, target, timeout))
                Path(target).write_bytes(b'%PDF-1.4 fake')

            out = self.pdf.convert(docx, runner=runner)
            self.assertTrue(out.endswith('.pdf'))
            self.assertTrue(Path(out).exists())
            self.assertEqual(len(calls), 1)
            self.pdf.convert(docx, runner=runner)       # 比 docx 新 → 复用
            self.assertEqual(len(calls), 1)
            self.pdf.convert(docx, force=True, runner=runner)
            self.assertEqual(len(calls), 2)

    def test_invalid_docx_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'x.txt'
            path.write_text('x')
            with self.assertRaises(self.pdf.PdfError):
                self.pdf.convert(path, runner=lambda *a: None)

    def test_powershell_script_passes_paths_via_env(self):
        self.assertIn('PCAL_DOCX', self.pdf.PS_SCRIPT)
        self.assertIn('PCAL_PDF', self.pdf.PS_SCRIPT)
        self.assertIn('SaveAs2', self.pdf.PS_SCRIPT)


if __name__ == '__main__':
    unittest.main()
