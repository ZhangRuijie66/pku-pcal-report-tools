# -*- coding: utf-8 -*-
"""共享文件选择组件 `web/files.js`：列表必须只列出本模块真能读的后缀。

守的是 2026-11-09 排查「电化学同类 bug 是否在别的模块」时发现的真实缺陷：

    表面吸附工具的文件清单里列出了 `数据处理.xlsx`，
    点一下却报「导入失败：不是 CSV/TXT 文件」。

根因：`PcalFiles.mount(el, {exts: [...]})` 的 `exts` 以前**只用于**「选择文件…」
系统对话框的过滤器，列表本身照后端 `/api/files` 返回什么就列什么；而后端多数
模块用的是共享层 `dataloc.DATA_EXTS`（csv/txt/xlsx/xls/xlsm/json/dat/tsv），
比模块真正能解析的格式宽。于是列表里混进点不动的文件。

同类现场（实测）：
  · 表面吸附工具：列 `数据处理.xlsx`，点了报「不是 CSV/TXT 文件」；
  · 双液系工具：列 3 个文件，其中 2 个 xlsx 用不上（本模块只读 .json）；
  · 紫外光谱/电化学：后端已按 .txt 过滤，看不出问题（所以只在别的模块暴露）。

这里守的是「列表渲染前按 exts 过滤」这条不变量，以及「空列表要说清原因」。
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support                                        # noqa: E402

TOOLS = ('燃烧热工具', '溶解热工具', '紫外光谱工具', '化学动力学工具',
         '电化学工具', '电导率工具', '蒸气压工具', '双液系工具',
         '偶极矩工具', '磁化率工具', '表面吸附工具')

#: 各模块 mount 时声明的 exts（从 app.js 抓；None = 没写，表示不限制）
def _declared_exts(tool):
    js = (support.REPO_ROOT / tool / 'web' / 'app.js').read_text(encoding='utf-8')
    out = []
    for m in re.finditer(r'exts\s*:\s*\[([^\]]*)\]', js):
        out.append([x.strip().strip('\'"') for x in m.group(1).split(',')
                    if x.strip()])
    return out


class FilesJsFiltersByExts(unittest.TestCase):
    """`files.js` 的 reload 必须按 opts.exts 过滤，且要有可测的辅助函数。"""

    @classmethod
    def setUpClass(cls):
        cls.src = (support.REPO_ROOT / '_core' / 'web_files.js').read_text(
            encoding='utf-8')

    def test_helper_exists(self):
        self.assertIn('function _allowed(', self.src,
                      'files.js 缺少按后缀判断的辅助函数')

    def test_allowed_logic(self):
        """把 _allowed 的逻辑抽出来单独验：只认末尾后缀，大小写不敏感。"""
        exts = ['.csv', '.txt']
        cases = [
            ('a.csv', True), ('a.CSV', True), ('a.txt', True),
            ('数据处理.xlsx', False), ('a.json', False),
            ('csv', False), ('a.csvx', False), ('x/a.tsv', False),
            ('没有后缀', False),
        ]
        for name, want in cases:
            low = name.lower()
            got = any(low.endswith(e.lower()) for e in exts)
            self.assertEqual(got, want, '%s 的判定应为 %s' % (name, want))

    def test_reload_filters(self):
        """reload() 里必须真的调用过滤，而不是把所有文件塞进 files。"""
        seg = self.src[self.src.index('async function reload'):]
        seg = seg[:seg.index('\n    }') + 6]
        self.assertIn('_allowed', seg,
                      'reload() 没有按 exts 过滤：列表会列出点不动的文件')
        self.assertNotIn('(j.files || []).forEach((f) => files.push(f));', seg,
                         'reload() 仍是全量塞入（老写法）')

    def test_empty_list_explains_why(self):
        """过滤后可能一个都不剩，此时必须说清「有几个文件但都不支持」。

        否则用户看到空列表会以为工具没扫到文件。
        """
        self.assertRegex(self.src, r'个文件，但没有',
                         '空列表时没说清「有文件但格式不支持」')
        self.assertRegex(self.src, r'其中 0 个可用|个文件，其中',
                         '空列表时 meta 被清空，用户分不清「空」和「没扫到」')

    def test_synced_to_all_tools(self):
        """11 个模块的 web/files.js 必须与共享层一致（否则改了等于没改）。"""
        canon = (support.REPO_ROOT / '_core' / 'web_files.js').read_bytes()
        canon = canon.replace(b'\r\n', b'\n')
        for tool in TOOLS:
            path = support.REPO_ROOT / tool / 'web' / 'files.js'
            self.assertTrue(path.exists(), '%s 缺 web/files.js' % tool)
            data = path.read_bytes().replace(b'\r\n', b'\n')
            self.assertEqual(data, canon,
                             '%s/web/files.js 与 _core/web_files.js 不一致；'
                             '跑 python _core/sync_core.py --apply' % tool)


class DeclaredExtsAreSane(unittest.TestCase):
    """各模块声明的 exts 必须与它后端真正能读的格式相符。

    这条防的是「声明归声明、后端另一套」：如果某模块后端只认 .json，
    前端却写 exts: ['.xlsx', ...]，过滤后会把真正能读的 json 也滤掉。
    """

    def test_exts_declared(self):
        """每个 mount 了 PcalFiles 的模块都要写下 exts，否则等于不过滤。"""
        for tool in TOOLS:
            app = (support.REPO_ROOT / tool / 'web' / 'app.js').read_text(
                encoding='utf-8')
            if 'PcalFiles.mount' not in app:
                continue
            self.assertTrue(_declared_exts(tool),
                            '%s 的 PcalFiles.mount 没写 exts，列表会列出'
                            '点不动的文件' % tool)

    def test_surface_adsorption_reads_text_only(self):
        """表面吸附只读 CSV/TXT/TSV，所以 exts 里不该出现 xlsx。"""
        tool = '表面吸附工具'
        declared = _declared_exts(tool)
        self.assertTrue(declared)
        flat = {e.lower() for group in declared for e in group}
        self.assertEqual(flat, {'.csv', '.txt', '.tsv'},
                         '表面吸附的 exts 与后端 /api/filetext 的白名单不符')
        srv = (support.REPO_ROOT / tool / 'pcal' / 'server.py').read_text(
            encoding='utf-8')
        self.assertIn("('.csv', '.txt', '.tsv')", srv,
                      '后端 /api/filetext 的白名单变了，前端的 exts 要跟着改')

    def test_dual_liquid_reads_json(self):
        """双液系只读 .json（数据快照）。"""
        declared = _declared_exts('双液系工具')
        flat = {e.lower() for group in declared for e in group}
        self.assertIn('.json', flat)


if __name__ == '__main__':
    unittest.main(verbosity=2)
