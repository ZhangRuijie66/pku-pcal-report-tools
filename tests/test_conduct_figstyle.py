# -*- coding: utf-8 -*-
"""电导率：绘图样式统一 + 附录三张组内图（2026-11-20 用户要求）。

用户原话：「优化一下画图格式，全文需要统一，包括字体、字号等」，
随后定下 A1/C/E 三张图放附录、正文补充说明。

## 为什么这些测试值得写

matplotlib 的 ``fontsize=9`` 只是**画布上**的 9 pt。图片插进 Word 时按
``width_cm`` 缩放，缩放比 = 插入宽度 ÷ 画布宽度。画布 6.2 in（15.75 cm）
却按 12.5 cm 插入时，缩放比 0.794，设 10 pt 实印 7.94 pt；另一张画布
5.6 in（14.22 cm）按 11.5 cm 插入则实印 8.08 pt。同一份报告里图的字号
差 1.8%——这就是用户说「需要统一」时看到的毛病。

这类回归**肉眼很难发现**（差 1.8% 不并排看不出来），但用
「画布宽 == 插入宽」这条等式一测就露，所以必须钉住。
"""
from __future__ import annotations

import math
import unittest

from support import REPO_ROOT, load_module

TOOL = '电导率工具'
FIXTURES = REPO_ROOT / 'tests' / 'fixtures' / '电导率'
SHARED_XLSX = FIXTURES / '共享数据表.xlsx'

_have_openpyxl = True
try:
    import openpyxl                                    # noqa: F401
except ImportError:                                    # pragma: no cover
    _have_openpyxl = False


def _ps():
    return load_module(TOOL, 'plotstyle')


def _plotting():
    return load_module(TOOL, 'plotting')


# ============================================================ 尺寸一致性
class PlotStyleConsistencyTests(unittest.TestCase):
    """画布宽度必须等于报告里的插入宽度，缩放比才是 1。"""

    def test_canvas_width_matches_insert_width(self):
        """``plotstyle.FIG_W``（英寸）换算回厘米，必须等于 ``FIG_W_CM``。"""
        ps = _ps()
        self.assertAlmostEqual(ps.FIG_W * 2.54, ps.FIG_W_CM, places=2,
                               msg='FIG_W 与 FIG_W_CM 不自洽，缩放比就不是 1')

    def test_report_uses_the_same_width(self):
        """报告里所有作图插图的 width_cm 都要用 ``plotting.ps.FIG_W_CM``。

        例外只有图1（预习笔记扫描件 INTRO_JPG），它不是 matplotlib 画的，
        不受这套规范约束。
        """
        src = (REPO_ROOT / TOOL / 'pcal' / 'report.py').read_text(encoding='utf-8')
        # 逐个 width_cm= 取值，看是否都指向 plotting.ps.FIG_W_CM（或图1 的 11.0）
        import re
        vals = re.findall(r'width_cm=([^\n,)]+)', src)
        bad = []
        for v in vals:
            v = v.strip()
            if 'FIG_W_CM' in v:
                continue
            if v in ('11.0',):      # 图1 扫描件，允许
                continue
            bad.append(v)
        self.assertEqual(bad, [],
                         '这些 width_cm 没用统一的 FIG_W_CM：%r' % (bad,))

    def test_font_sizes_are_uniform(self):
        """字号只从 plotstyle 取，不许在 plotting.py 里另写 fontsize=10/11。

        ⚠ 只扫**代码**，不扫注释与 docstring：模块 docstring 里就写着
        「不要再单独传 fontsize=10/11」这句说明，天真地用正则全文搜会
        把它当成违规（实测踩到）。
        """
        import ast
        import re
        src = (REPO_ROOT / TOOL / 'pcal' / 'plotting.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        # 收集所有字符串常量（docstring / 普通字符串）的行号，扫的时候跳过
        str_lines = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.lineno:
                    str_lines.add(node.lineno)
                # 多行字符串占的前几行也跳过
                n = node.value.count('\n')
                for k in range(1, n + 1):
                    str_lines.add(node.lineno + k)
        bad = []
        for i, line in enumerate(src.split('\n'), 1):
            if i in str_lines:
                continue
            code = line.split('#', 1)[0]
            for m in re.finditer(r'fontsize=(\d+(?:\.\d+)?)', code):
                bad.append((i, m.group(1)))
        self.assertEqual(bad, [],
                         'plotting.py 里出现了硬编码字号 %r，应改用 '
                         'ps.FS_TICK / FS_LABEL / FS_LEGEND / FS_ANNOT'
                         % (bad,))

    def test_no_mathtext_chinese(self):
        """中文不得放进 $...$：mathtext 走 STIX，没有中文字形，会渲染成方框。

        实测踩过：ylabel 写 ``$\\Lambda_m^{\\infty}$ 相对CRC理论值偏差 / %``
        时，中文那半串全是方框。
        """
        src = (REPO_ROOT / TOOL / 'pcal' / 'plotting.py').read_text(encoding='utf-8')
        import re
        # 找 $...$ 之间是否含中日韩字符
        for m in re.finditer(r'\$([^$]+)\$', src):
            inner = m.group(1)
            if any('\u4e00' <= ch <= '\u9fff' for ch in inner):
                self.fail('mathtext 里出现中文：$%s$' % inner)


# ============================================================ 图的产出
@unittest.skipUnless(_have_openpyxl, '需要 openpyxl 才能解析 xlsx')
class AppendixFigureTests(unittest.TestCase):
    """附录三张图要真的能生成，且尺寸符合规范。"""

    @classmethod
    def setUpClass(cls):
        ana = load_module(TOOL, 'analysis')
        cls.shared = ana.analyze_shared(str(SHARED_XLSX), me_index=5)

    def _render(self, fig):
        import io
        import matplotlib.pyplot as plt
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100)
        plt.close(fig)
        buf.seek(0)
        return buf

    def test_scatter_figure(self):
        p = _plotting()
        fig = p.make_group_scatter_figure(self.shared)
        self._render(fig)

    def test_kappa_deviation_figure(self):
        p = _plotting()
        fig = p.make_group_kappa_figure(self.shared)
        self._render(fig)

    def test_kpair_figure(self):
        p = _plotting()
        fig = p.make_kpair_figure(self.shared)
        self._render(fig)

    def test_figure_width_is_standard(self):
        """渲染出来的画布宽度（英寸）应等于 FIG_W。"""
        p = _plotting()
        ps = _ps()
        for fn in (p.make_group_scatter_figure,
                   p.make_group_kappa_figure,
                   p.make_kpair_figure):
            fig = fn(self.shared)
            self.assertAlmostEqual(fig.get_size_inches()[0], ps.FIG_W,
                                   places=3,
                                   msg='%s 的画布宽度不是 FIG_W' % fn.__name__)
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_paired_figure_needs_no_me(self):
        """没认领「我的数据」时也要能出图（不崩、不高亮任何人）。"""
        ana = load_module(TOOL, 'analysis')
        shared = ana.analyze_shared(str(SHARED_XLSX))
        self.assertIsNone((shared.get('match') or {}).get('index'))
        p = _plotting()
        for fn in (p.make_group_scatter_figure,
                   p.make_group_kappa_figure,
                   p.make_kpair_figure):
            self._render(fn(shared))


# ============================================================ 正文/附录
class AppendixSectionTests(unittest.TestCase):
    """附录文字与图号约定。"""

    def test_appendix_uses_renumbered_figures(self):
        """附录图号接正文排（正文到图6，附录从图7 起）。

        tests/audit_docx.py 会检查图号从 1 开始且**连续**，
        接不上就报 caption.gap。
        """
        src = (REPO_ROOT / TOOL / 'pcal' / 'report.py').read_text(encoding='utf-8')
        self.assertIn('图7', src)
        self.assertIn('图8', src)
        self.assertIn('图9', src)
        # 正文要有指向附录的说明（用户要求「正文中补充说明」）
        self.assertIn('附录图7', src)

    def test_appendix_skipped_without_shared_data(self):
        """没读共享数据表时整节省略，不能印一个空标题。"""
        src = (REPO_ROOT / TOOL / 'pcal' / 'report.py').read_text(encoding='utf-8')
        self.assertIn('if appendix_pngs:', src,
                      '附录必须以「有没有图」为开关，否则会印空标题')
