# -*- coding: utf-8 -*-
"""前端草稿/撤销的接线检查（真正的交互在浏览器里验证）。"""
from __future__ import annotations

import unittest

from support import REPO_ROOT

DRAFT_APP_TOOLS = (
    '化学动力学工具', '蒸气压工具', '双液系工具', '偶极矩工具', '表面吸附工具',
)
POINT_TOOLS = ('燃烧热工具', '溶解热工具')


class DraftIntegrationTests(unittest.TestCase):
    def test_shared_draft_script_is_loaded_and_used(self):
        for tool in DRAFT_APP_TOOLS:
            html = (REPO_ROOT / tool / 'web' / 'index.html').read_text(encoding='utf-8')
            js = (REPO_ROOT / tool / 'web' / 'app.js').read_text(encoding='utf-8')
            self.assertIn('/static/draft.js', html, tool)
            for call in ('PcalDraft.init(', 'PcalDraft.save()', 'PcalDraft.clear()'):
                self.assertIn(call, js, '%s 缺少 %s' % (tool, call))

    def test_magnetic_inline_script_uses_draft(self):
        tool = '磁化率工具'
        html = (REPO_ROOT / tool / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('/static/draft.js', html)
        self.assertIn('PcalDraft.init(', html)
        self.assertIn('PcalDraft.clear()', html)
        self.assertIn('function readConfig()', html)
        self.assertIn('function applyConfig(', html)

    def test_shared_draft_has_safety_guards(self):
        src = (REPO_ROOT / '_core' / 'web_draft.js').read_text(encoding='utf-8')
        for marker in ('MAX_AGE', 'localStorage.setItem', 'confirm(',
                       'async function init', 'restoring'):
            self.assertIn(marker, src)

    def test_point_modules_have_undo(self):
        for tool in POINT_TOOLS:
            js = (REPO_ROOT / tool / 'web' / 'app.js').read_text(encoding='utf-8')
            for marker in ('function pushUndoAll(', 'async function undoPoints(',
                           'Ctrl+Z', 'DRAFT_KEY', 'function saveDraft('):
                self.assertIn(marker, js, '%s 缺少 %s' % (tool, marker))


if __name__ == '__main__':
    unittest.main()
