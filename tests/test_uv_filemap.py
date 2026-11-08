# -*- coding: utf-8 -*-
"""紫外光谱：数据文件清单的「按内容识别」与映射界面可用性。

两条用户当场提出的要求（2026-11-08）：

1. **未匹配上、但格式正确的 txt 也要出现在选项列表里。**
   原来 `spectrum_files()` 只按 `.txt` 后缀收，于是换了命名习惯的导出文件
   （`.dat`、无后缀、被重命名过）压根不进下拉框，用户只看到「没找到」。

2. **映射界面要有实时查找框。**
   `index.html` 里的 `fileSearch` 输入框 + `app.js` 的 `renderFileMap` 关键字过滤。
   顺带修掉一个真 bug：加「数据文件映射」卡片时误把 `<section class="card">`
   提前闭合，封面字段落到卡片外、丢了白框（用户报「这里的框没了」）。
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest

from support import REPO_ROOT, load_module

TOOL = '紫外光谱工具'
WEB = REPO_ROOT / TOOL / 'web'

GOOD = '1\t100\t10\t90\n2\t105\t11\t94\n3\t110\t12\t98\n4\t115\t13\t102\n'


class SpectrumFileDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uv = load_module(TOOL, 'uv')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        cls._write('a-氘灯.txt', GOOD)
        cls._write('b-大写.TXT', GOOD)
        cls._write('c-数据.dat', GOOD)          # 以前会漏
        cls._write('d-无后缀', GOOD)             # 以前会漏
        cls._write('e-坏.txt', '这不是光谱\n随便几行\n')
        cls._write('f-讲义.pdf', GOOD)           # 非数据扩展名，应排除
        cls._write('g-假.dat', 'hello world\nfoo\n')   # 内容不是四列，应排除
        cls._write(os.path.join('sub', 'h-子目录.txt'), GOOD)
        cls._write('i-空格分隔.dat', '1 100 10 90\n2 105 11 94\n3 110 12 98\n')
        cls._write('j-逗号.csv', '1,100,10,90\n2,105,11,94\n3,110,12,98\n')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def _write(cls, name, content):
        path = os.path.join(cls.dir, name)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(content)

    def _rels(self):
        return [os.path.relpath(p, self.dir).replace('\\', '/')
                for p in self.uv.spectrum_files(self.dir)]

    def test_dat_with_valid_content_is_listed(self):
        """换了命名习惯的 .dat 也要出现在清单里（用户要求的核心一条）。"""
        self.assertIn('c-数据.dat', self._rels())

    def test_extensionless_file_with_valid_content_is_listed(self):
        self.assertIn('d-无后缀', self._rels())

    def test_uppercase_txt_suffix_is_listed(self):
        self.assertIn('b-大写.TXT', self._rels())

    def test_space_and_comma_delimited_are_accepted(self):
        rels = self._rels()
        self.assertIn('i-空格分隔.dat', rels)
        self.assertIn('j-逗号.csv', rels)

    def test_non_data_extensions_are_excluded(self):
        self.assertNotIn('f-讲义.pdf', self._rels())

    def test_non_spectrum_content_is_excluded(self):
        """扩展名像数据、内容不是四列数值的，不能混进候选。"""
        self.assertNotIn('g-假.dat', self._rels())

    def test_plain_txt_is_still_listed_even_if_content_odd(self):
        """.txt 保持原有行为：不做内容校验（历史行为，别收紧成回归）。"""
        rels = self._rels()
        self.assertIn('a-氘灯.txt', rels)
        self.assertIn('e-坏.txt', rels)

    def test_recursive_subdirectory(self):
        self.assertTrue(any(r.endswith('h-子目录.txt') for r in self._rels()))

    def test_empty_or_missing_dir_is_safe(self):
        self.assertEqual(self.uv.spectrum_files(''), [])
        self.assertEqual(self.uv.spectrum_files(os.path.join(self.dir, 'nope')), [])


class FileMapUiTests(unittest.TestCase):
    """映射界面的结构约束——纯静态检查，不起服务器。"""

    @classmethod
    def setUpClass(cls):
        cls.html = (WEB / 'index.html').read_text(encoding='utf-8')
        cls.js = (WEB / 'app.js').read_text(encoding='utf-8')

    def test_section_tags_are_balanced(self):
        """`<section>` 与 `</section>` 必须配平。

        加「数据文件映射」那次把 `</section>` 提前闭合，封面字段掉到卡片外面、
        丢了白底边框（用户报「这里的框没了」）。这类错误浏览器不报错、只静默变形。
        """
        self.assertEqual(
            len(re.findall(r'<section\b', self.html)),
            len(re.findall(r'</section>', self.html)))

    def test_cover_fields_are_inside_a_card(self):
        """封面字段必须在某个 `<section class="card">` 里面。"""
        pos_student = self.html.find('id="student_name"')
        self.assertGreater(pos_student, 0, '找不到 student_name')
        last_card = self.html.rfind('<section class="card"', 0, pos_student)
        self.assertGreater(last_card, 0, '封面字段前面没有 card 开头')
        between = self.html[last_card:pos_student]
        self.assertNotIn('</section>', between,
                         '封面字段落在卡片外面了（</section> 提前闭合）')

    def test_search_box_exists_and_is_wired(self):
        self.assertIn('id="fileSearch"', self.html)
        self.assertIn("$('fileSearch')", self.js)
        self.assertIn('oninput', self.js)

    def test_render_file_map_filters_by_keyword(self):
        """renderFileMap 必须真的用上查找框的值。"""
        body = self.js[self.js.find('function renderFileMap'):]
        body = body[:body.find('\nfunction ', 10) + 1 or len(body)]
        self.assertIn('fileSearch', body)
        self.assertIn('filter', body)


if __name__ == '__main__':
    unittest.main()
