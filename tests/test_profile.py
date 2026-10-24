# -*- coding: utf-8 -*-
"""共享个人档案：合并规则、11 个 server 接线、入口页保存。"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from support import REPO_ROOT

TOOLS = (
    '燃烧热工具', '溶解热工具', '紫外光谱工具', '化学动力学工具',
    '电化学工具', '电导率工具', '蒸气压工具', '双液系工具',
    '偶极矩工具', '磁化率工具', '表面吸附工具',
)


def load_path(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProfileMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_path('pcal_profile_test',
                                REPO_ROOT / '_core' / 'profile.py')

    def test_profile_overrides_local_and_fills_data_dir(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'profile.json'
            path.write_text(json.dumps({
                'student_name': '测试同学', 'student_id': '2300000000',
                'group': '3', 'group_no': '8',
                'data_dirs': {'燃烧热工具': r'D:\data\combustion'},
            }, ensure_ascii=False), encoding='utf-8')
            self.profile.profile_path = lambda: str(path)
            self.profile.tool_dir_name = lambda: '燃烧热工具'
            merged = self.profile.merge_saved({
                'student_name': '本地旧名字', 'data_dir': r'D:\old',
                'pressure_kPa': 101.3,
            })
            self.assertEqual(merged['student_name'], '测试同学')
            self.assertEqual(merged['student_id'], '2300000000')
            self.assertEqual(merged['data_dir'], r'D:\data\combustion')
            self.assertEqual(merged['pressure_kPa'], 101.3)

    def test_missing_or_bad_profile_keeps_local(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'profile.json'
            self.profile.profile_path = lambda: str(path)
            self.profile.tool_dir_name = lambda: '燃烧热工具'
            self.assertEqual(self.profile.merge_saved({'student_name': '本地'}),
                             {'student_name': '本地'})
            path.write_text('{bad json', encoding='utf-8')
            self.assertEqual(self.profile.merge_saved({}), {})

    def test_every_server_uses_profile(self):
        for tool in TOOLS:
            src = (REPO_ROOT / tool / 'pcal' / 'server.py').read_text(encoding='utf-8')
            self.assertIn('from pcal import profile', src, tool)
            self.assertEqual(src.count('profile.merge_saved'), 2, tool)


class PortalProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.portal = load_path('pcal_portal_test',
                               REPO_ROOT / '物化实验报告工具' / 'portal.py')

    def test_save_and_load_filters_unknown_tools(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'profile.json'
            self.portal.PROFILE_PATH = str(path)
            result = self.portal._save_profile({'profile': {
                'student_name': '测试同学', 'student_id': '2300000000',
                'group': '3', 'group_no': '8',
                'data_dirs': {'燃烧热工具': r'D:\data',
                              '不存在的工具': r'D:\nope'},
            }})
            self.assertTrue(result['ok'])
            self.assertEqual(result['profile']['data_dirs'],
                             {'燃烧热工具': r'D:\data'})
            loaded = self.portal._load_profile()
            self.assertEqual(loaded['student_name'], '测试同学')
            self.assertEqual(loaded['data_dirs'], {'燃烧热工具': r'D:\data'})
            payload = self.portal._profile_payload()
            self.assertTrue(payload['ok'])
            self.assertGreaterEqual(len(payload['modules']), 11)
            self.assertIn('燃烧热工具',
                          {m['tool'] for m in payload['modules']})

    def test_portal_routes_include_profile(self):
        src = (REPO_ROOT / '物化实验报告工具' / 'portal.py').read_text(encoding='utf-8')
        for marker in ("'/api/profile'", 'def _save_profile', 'PROFILE_PATH'):
            self.assertIn(marker, src)

    def test_reports_payload_and_path_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'out'
            folder = root / 'student-report'
            folder.mkdir(parents=True)
            docx = folder / 'report.docx'
            docx.write_bytes(b'PK fake')
            self.portal.REPORT_DIR = str(root)
            payload = self.portal._reports_payload()
            self.assertEqual(len(payload['reports']), 1)
            self.assertEqual(payload['reports'][0]['name'], 'report.docx')
            self.assertIsNone(payload['reports'][0]['pdf'])
            self.assertIsNotNone(
                self.portal._valid_report_path(str(docx), '.docx'))
            self.assertIsNone(
                self.portal._valid_report_path(str(Path(td) / 'outside.docx'), '.docx'))
            self.assertIsNone(
                self.portal._valid_report_path(str(docx), '.pdf'))
            result, code = self.portal._convert_pdf({'docx': str(Path(td) / 'x.docx')})
            self.assertEqual(code, 400)
            self.assertFalse(result['ok'])

    def test_pdf_routes_exist(self):
        src = (REPO_ROOT / '物化实验报告工具' / 'portal.py').read_text(encoding='utf-8')
        for marker in ("'/api/reports'", "'/api/pdf'",
                       "'/api/pdf/file'", 'def _convert_pdf'):
            self.assertIn(marker, src)


if __name__ == '__main__':
    unittest.main()
