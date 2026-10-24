# -*- coding: utf-8 -*-
"""docx 审计器自身的测试：好文档零问题，坏文档能抓到已知毛病。"""
from __future__ import annotations

import os
import tempfile
import unittest

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH

from audit_docx import audit_docx
from support import load_module


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dk = load_module('电化学工具', 'docxkit')
        cls.tmp = tempfile.TemporaryDirectory()
        blank = os.path.join(cls.tmp.name, 'blank.docx')
        docx.Document().save(blank)
        cls.blank = blank

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _good_report(self):
        rb = self.dk.ReportBuilder(self.blank, cover_tail_blanks=None)
        cover_title = rb.doc.add_paragraph()
        cover_title.add_run('物理化学实验报告').font.size = docx.shared.Pt(36)
        rb.heading('1 引言', 1)
        rb.para('这是一段正文。')
        rb.caption('表1 测试数据')
        rb.table(['轮次', 'm_{Ni-1}/g'], [['1', '0.2'], ['2', '0.3']])
        rb.caption('图1 测试曲线')
        rb.equation(r'\frac{a}{b}')
        # 封面信息表：最后一格故意空着，审计器应识别为封面表并跳过
        cover = rb.doc.add_table(rows=3, cols=2)
        cover.cell(0, 0).text = '姓名：'
        cover.cell(0, 1).text = '测试同学'
        cover.cell(1, 0).text = '学号：'
        cover.cell(1, 1).text = '2300000000'
        cover.cell(2, 0).text = '大气压强：'
        cover.cell(2, 1).text = ''
        path = os.path.join(self.tmp.name, 'good.docx')
        rb.save(path)
        return path

    def _bad_report(self):
        doc = docx.Document()
        p = doc.add_paragraph()
        p.add_run('\\lg x').font.size = None
        p.add_run('10⁻³')
        big = doc.add_paragraph()
        big.add_run('正文用了大字号').font.size = docx.shared.Pt(12)

        doc.add_paragraph('图1 第一张图').alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.add_paragraph('图1 重复的图号').alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.add_paragraph('表2 编号从 2 开始').alignment = WD_ALIGN_PARAGRAPH.CENTER

        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = 'a'
        table.cell(0, 1).text = 'b'
        table.cell(1, 0).text = '1'
        table.cell(1, 1).text = ''
        path = os.path.join(self.tmp.name, 'bad.docx')
        doc.save(path)
        return path

    def test_good_report_has_no_issues(self):
        issues = audit_docx(self._good_report())
        self.assertEqual([str(i) for i in issues], [])

    def test_bad_report_reports_known_problems(self):
        issues = audit_docx(self._bad_report())
        codes = {i.code for i in issues}
        for code in ('text.backslash', 'text.unicode_script',
                     'text.font_size', 'caption.duplicate', 'caption.start',
                     'table.trailing_empty'):
            self.assertIn(code, codes, (code, [str(i) for i in issues]))

    def test_missing_file_is_handled_by_cli(self):
        # audit_docx 本身抛 FileNotFoundError，CLI 负责给出可读提示；
        # 这里只确认异常类型稳定，避免以后静默返回空列表。
        with self.assertRaises(Exception):
            audit_docx(os.path.join(self.tmp.name, 'nope.docx'))


if __name__ == '__main__':
    unittest.main()
