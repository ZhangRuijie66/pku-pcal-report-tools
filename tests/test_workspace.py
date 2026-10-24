# -*- coding: utf-8 -*-
"""工作区快照：文件哈希、配置落盘、11 个服务器都接上了。"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from support import REPO_ROOT, load_module

TOOLS = (
    '燃烧热工具', '溶解热工具', '紫外光谱工具', '化学动力学工具',
    '电化学工具', '电导率工具', '蒸气压工具', '双液系工具',
    '偶极矩工具', '磁化率工具', '表面吸附工具',
)


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = load_module('电导率工具', 'workspace')

    def test_snapshot_hashes_inputs_and_template(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_dir = root / 'data'
            data_dir.mkdir()
            csv = data_dir / 'sample.csv'
            csv.write_text('time(s),Delta_T(K)\n0,0.1\n', encoding='utf-8')
            template = REPO_ROOT / '电导率工具' / 'templates' / '电导率报告模板2026.docx'
            payload = {'config': {'data_dir': str(data_dir)},
                       'rounds': [{'file': 'sample.csv'}]}
            cfg = {'data_dir': str(data_dir), 'student_name': '测试同学',
                   'student_id': '2300000000', 'group': '3', 'group_no': '8'}
            out_dir = root / 'report'
            path = self.ws.save(out_dir, payload, cfg, '测试实验', str(template),
                                extra={'missing': str(root / 'nope.csv')})
            self.assertTrue(Path(path).exists())
            data = json.loads(Path(path).read_text(encoding='utf-8'))

            self.assertEqual(data['schema'], 1)
            self.assertEqual(data['tool'], '测试实验')
            self.assertEqual(data['core']['version'], self.ws.CORE_VERSION)
            self.assertIn('omml.py', data['core']['files'])
            self.assertEqual(data['config']['student_name'], '测试同学')
            self.assertFalse(data['template']['missing'])
            self.assertEqual(data['template']['sha256'],
                             hashlib.sha256(template.read_bytes()).hexdigest())
            self.assertEqual(len(data['files']), 1)
            self.assertEqual(data['files'][0]['path'], str(csv.resolve()))
            self.assertEqual(data['files'][0]['sha256'],
                             hashlib.sha256(csv.read_bytes()).hexdigest())
            self.assertEqual(self.ws.load(out_dir)['tool'], '测试实验')

    def test_all_servers_write_workspace(self):
        for tool in TOOLS:
            src = (REPO_ROOT / tool / 'pcal' / 'server.py').read_text(encoding='utf-8')
            self.assertIn('from pcal import workspace', src, tool)
            self.assertIn('workspace.save(', src, tool)


if __name__ == '__main__':
    unittest.main()
