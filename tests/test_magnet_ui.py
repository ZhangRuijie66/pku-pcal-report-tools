# -*- coding: utf-8 -*-
"""磁化率界面与其它模块模板的一致性检查。"""
from __future__ import annotations

import unittest

from support import REPO_ROOT

TOOL = REPO_ROOT / '磁化率工具'


class MagnetUiTests(unittest.TestCase):
    def test_standard_layout(self):
        html = (TOOL / 'web' / 'index.html').read_text(encoding='utf-8')
        for marker in ('<header>', '<main>', 'class="panel"', 'class="content"',
                       'id="btnExport"', 'id="chartKind"',
                       '/static/draft.js', '/static/app.js'):
            self.assertIn(marker, html)
        # 不再使用旧版的紫色渐变卡片模板
        self.assertNotIn('linear-gradient(135deg, #667eea', html)

    def test_frontend_actions(self):
        js = (TOOL / 'web' / 'app.js').read_text(encoding='utf-8')
        for marker in ('function renderSummary(', 'function renderTable(',
                       'function drawChart(', 'async function importData(',
                       'async function exportReport(', 'PcalDraft.init(',
                       'PcalDraft.save()', 'PcalDraft.clear()'):
            self.assertIn(marker, js)

    def test_server_has_preview_and_sample(self):
        src = (TOOL / 'pcal' / 'server.py').read_text(encoding='utf-8')
        for marker in ("'/api/preview'", "'/api/sample'", "'/static/'",
                       'def _preview_png(', 'def _placeholder_png('):
            self.assertIn(marker, src)

    def test_charts_are_scatter_not_bar(self):
        src = (TOOL / 'pcal' / 'plotting.py').read_text(encoding='utf-8')
        self.assertIn('ax.scatter(', src)
        self.assertNotIn('ax.bar(', src)
        self.assertIn('DPI_PREVIEW', src)
        self.assertIn('反磁性样品', src)


if __name__ == '__main__':
    unittest.main()
