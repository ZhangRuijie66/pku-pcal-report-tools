# -*- coding: utf-8 -*-
"""紫外光谱：高斯 TD-DFT 结果读取界面的「选择文件夹…」按钮。

用户 2026-11-09 要求「给高斯结果读取加一个选择文件夹的按钮」。这类改动
前端最容易出的三种漏法，逐条钉住：

1. **按钮在 HTML 里但没绑事件**（点了没反应，控制台也不报错）；
2. **绑了事件但点完不回填**（窗口选完，输入框还是空的）；
3. **选完不持久化**（刷新页面就丢，每次开工具都要重选）——
   `gcalc_logs_dir` 必须同时出现在 PROC_FIELDS 与 EL_ID 里，
   少一个都会导致 readConfig/fillConfig 漏掉它。

第 3 条是这次真正修掉的隐患：后端 `/api/gcalc/read` 一直支持 `?dir=`，
PERSIST_KEYS 里也有 `gcalc_logs_dir`，但前端从来没把它读出来/填回去。
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support                                        # noqa: E402

TOOL = '紫外光谱工具'
WEB = support.REPO_ROOT / TOOL / 'web'


def _html():
    return (WEB / 'index.html').read_text(encoding='utf-8')


def _js():
    return (WEB / 'app.js').read_text(encoding='utf-8')


class GcalcPickButtonTests(unittest.TestCase):

    def test_button_in_html(self):
        html = _html()
        self.assertIn('id="btnGcalcPick"', html, '缺少选择文件夹按钮')
        m = re.search(r'<button[^>]*id="btnGcalcPick"[^>]*>([^<]*)</button>', html)
        self.assertIsNotNone(m, '按钮标签写错')
        self.assertIn('选择文件夹', m.group(1))

    def test_button_next_to_logs_input(self):
        """按钮必须挨着日志目录输入框，否则用户找不到它管的是哪个栏。"""
        html = _html()
        i_in = html.find('id="gcalcLogs"')
        i_btn = html.find('id="btnGcalcPick"')
        self.assertGreater(i_in, -1)
        self.assertGreater(i_btn, i_in, '按钮应排在日志目录输入框之后')
        # 同一张卡片内（下一个 section 之前）
        nxt = html.find('</section>', i_in)
        self.assertLess(i_btn, nxt, '按钮跑到别的卡片里了')

    def test_button_bound(self):
        js = _js()
        self.assertIn("$('btnGcalcPick').onclick", js, '按钮没有绑定事件')
        self.assertIn('function pickGcalcLogs', js, '缺少处理函数')

    def test_pick_targets_logs_input(self):
        """处理函数必须把结果填进 gcalcLogs，不能填错栏。"""
        js = _js()
        m = re.search(r'function pickGcalcLogs\(\)\s*\{(.*?)\n\}', js, re.S)
        self.assertIsNotNone(m, '找不到 pickGcalcLogs 函数体')
        self.assertIn("'gcalcLogs'", m.group(1))

    def test_generic_pick_helper(self):
        """数据目录与日志目录共用一个通用函数，避免各抄一份。"""
        js = _js()
        self.assertIn('function pickFolderInto', js)
        # 数据目录的旧函数仍要能用（不能因为重构把原有按钮弄坏）
        self.assertIn('function pickDir', js)
        m = re.search(r'async function pickDir\(\)\s*\{(.*?)\n\}', js, re.S)
        self.assertIsNotNone(m)
        self.assertIn('pickFolderInto', m.group(1))

    def test_pickdir_endpoint_used(self):
        """走的是现成的 /api/pickdir，不用新造接口。"""
        js = _js()
        m = re.search(r'async function pickFolderInto\(.*?\n\}', js, re.S)
        self.assertIsNotNone(m)
        self.assertIn('/api/pickdir', m.group(0))

    def test_logs_dir_persisted(self):
        """gcalc_logs_dir 必须在 PROC_FIELDS 与 EL_ID 里，否则刷新就丢。"""
        js = _js()
        m = re.search(r'const PROC_FIELDS = \[(.*?)\];', js, re.S)
        self.assertIsNotNone(m, '找不到 PROC_FIELDS')
        self.assertIn("'gcalc_logs_dir'", m.group(1),
                      '没进 PROC_FIELDS → readConfig/fillConfig 不会带上它')

        m2 = re.search(r'const EL_ID = \{(.*?)\};', js, re.S)
        self.assertIsNotNone(m2, '找不到 EL_ID')
        self.assertIn('gcalc_logs_dir', m2.group(1),
                      'EL_ID 里没映射到 gcalcLogs，读写会落到不存在的 id 上')
        self.assertIn("'gcalcLogs'", m2.group(1))

    def test_auto_found_dir_backfilled(self):
        """自动找到日志目录时要回填，否则界面看不出读了哪个文件夹。"""
        js = _js()
        m = re.search(r'async function readGcalc\(\)\s*\{(.*?)\n\}', js, re.S)
        self.assertIsNotNone(m, '找不到 readGcalc 函数体')
        body = m.group(1)
        self.assertIn('r.dir', body)
        self.assertIn("$('gcalcLogs').value", body)

    def test_backend_supports_dir_param(self):
        """后端 /api/gcalc/read 必须接受 ?dir=，且返回实际用的目录。"""
        server = (support.REPO_ROOT / TOOL / 'pcal' / 'server.py').read_text(
            encoding='utf-8')
        self.assertIn("'/api/gcalc/read'", server)
        bridge = (support.REPO_ROOT / TOOL / 'pcal' / 'gcalc_bridge.py').read_text(
            encoding='utf-8')
        self.assertIn("dir=folder", bridge, 'read_results 应回传实际目录')
        analysis = (support.REPO_ROOT / TOOL / 'pcal' / 'analysis.py').read_text(
            encoding='utf-8')
        self.assertIn("'gcalc_logs_dir'", analysis,
                      'gcalc_logs_dir 应在 PERSIST_KEYS 里，否则存不下来')


if __name__ == '__main__':
    unittest.main(verbosity=2)
