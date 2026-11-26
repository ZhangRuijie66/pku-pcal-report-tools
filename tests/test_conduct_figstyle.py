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


# ============================================================ 标签不被裁
def _visible_ticks(ax):
    """只取真正会画出来的刻度。

    ``get_yticklabels()`` 会连视图范围外的刻度一起返回（matplotlib 保留
    但不绘制），直接量会把「6 超出 xlim」这种误报成裁切（实测踩到）。
    """
    out = []
    y0, y1 = ax.get_ylim()
    for v, t in zip(ax.get_yticks(), ax.get_yticklabels()):
        if y0 - 1e-12 <= v <= y1 + 1e-12 and t.get_text():
            out.append(('ytick %s' % t.get_text(), t))
    x0, x1 = ax.get_xlim()
    for v, t in zip(ax.get_xticks(), ax.get_xticklabels()):
        if x0 - 1e-12 <= v <= x1 + 1e-12 and t.get_text():
            out.append(('xtick %s' % t.get_text(), t))
    return out


class AxisLabelClippingTests(unittest.TestCase):
    """正文图的轴标签必须完整落在画布内（2026-11-26 用户同学实测被裁）。

    ## 这个 bug 长什么样

    图3~5（Λm–√c 拟合）的纵轴标签 ``Λₘ / S·m²·mol⁻¹`` 左边少了一截，
    用户看到的是「纵坐标不完整」。

    ## 根因

    matplotlib 默认左边距 ``0.125 * figsize`` = 0.57 in ≈ 41 pt，而这个
    9 pt 的纵轴标签要占 ~44 pt；``report.py`` 又是直接
    ``fig.savefig(p, dpi=DPI)``（**没有** ``bbox_inches='tight'``），
    于是标签左半截落在画布外，存出来的 PNG 就是断的。
    实测修复前该 ylabel 的 ``x0 = -11.8 px``（100 dpi）。

    附录图 7~9 早先调过 ``tight_layout()`` 所以没事，正文图 2~6 一直没调——
    这就是「只有这张图出问题」的原因。

    ## 为什么不能改成 bbox_inches='tight'

    那会改变输出图片的实际尺寸，画布宽就不再等于 Word 里的插入宽
    （``FIG_W_CM = 11.5``），``fontsize=9`` 也就不再是印刷真字号，
    v1.4.1 立的那套规范整体失效。只能在**固定画布内部**重排边距。
    """

    def _an(self):
        """造一份够画图2~图6 的最小分析结果（数值与真实截图同量级）。"""
        import numpy as np

        xs = np.array([1.42, 2.24, 2.84, 3.46, 4.98])
        ys = np.array([0.04167, 0.04156, 0.04095, 0.04122, 0.04046])
        fit = {'x': list(xs), 'y': list(ys), 'k': -0.00032, 'b': 0.04222}

        class _An:
            pass

        an = _An()
        an.fits = {'NaCl': dict(fit), 'HCl': dict(fit), 'NaAc': dict(fit)}
        an.kfit = {'x': [24.3, 22.1, 20.0, 18.4, 17.2],
                   'y': [0.01412, 0.01548, 0.01704, 0.01843, 0.01968],
                   'k': -0.0007, 'b': 0.0311}
        an.tables = {
            'NaCl': [{'c': 50.0, 'kappa_corr': 0.0012},
                     {'c': 100.0, 'kappa_corr': 0.0024}],
            'HCl': [{'c': 50.0, 'kappa_corr': 0.0041},
                    {'c': 100.0, 'kappa_corr': 0.0082}],
            'HAc': [{'c': 50.0, 'kappa_corr': 0.00021}],
        }
        return an

    def _assert_inside(self, fig, name):
        """所有会画出来的文本都必须落在画布矩形内。"""
        import matplotlib.pyplot as plt
        fig.canvas.draw()
        r = fig.canvas.get_renderer()
        W, H = fig.bbox.width, fig.bbox.height
        ax = fig.axes[0]
        targets = [('ylabel', ax.yaxis.label), ('xlabel', ax.xaxis.label)]
        targets += _visible_ticks(ax)
        problems = []
        for label, artist in targets:
            if not artist.get_text():
                continue
            bb = artist.get_window_extent(r)
            if bb.x0 < -0.5:
                problems.append('%s 左边超出 %.1f px' % (label, -bb.x0))
            if bb.x1 > W + 0.5:
                problems.append('%s 右边超出 %.1f px' % (label, bb.x1 - W))
            if bb.y0 < -0.5:
                problems.append('%s 下边超出 %.1f px' % (label, -bb.y0))
            if bb.y1 > H + 0.5:
                problems.append('%s 上边超出 %.1f px' % (label, bb.y1 - H))
        plt.close(fig)
        self.assertEqual(problems, [],
                         '%s 的轴标签被画布裁掉了（这就是用户看到的'
                         '「纵坐标不完整」）：%r' % (name, problems))

    def test_body_figures_have_no_clipped_labels(self):
        """图2~图6 的每一个分支都不许裁标签。"""
        p = _plotting()
        an = self._an()
        self._assert_inside(p.make_kappa_c_figure(an), '图2 κ–c')
        for key in ('NaCl', 'HCl', 'NaAc'):
            self._assert_inside(p.make_kohlrausch_figure(an, key),
                                '图3~5 %s' % key)
        self._assert_inside(p.make_kfit_figure(an), '图6 HAc 拟合')

    def test_empty_branches_have_no_clipped_labels(self):
        """「无数据」分支同样不能裁——标签是画在同一张画布上的。"""
        p = _plotting()
        an = self._an()
        an.fits = {}
        an.kfit = None
        self._assert_inside(p.make_kohlrausch_figure(an, 'HCl'), '图3~5 无数据')
        self._assert_inside(p.make_kfit_figure(an), '图6 无数据')

    def test_layout_keeps_canvas_size(self):
        """修边距不能改变画布尺寸，否则缩放比不再等于 1。"""
        p = _plotting()
        ps = _ps()
        fig = p.make_kohlrausch_figure(self._an(), 'HCl')
        w, h = fig.get_size_inches()
        import matplotlib.pyplot as plt
        plt.close(fig)
        self.assertAlmostEqual(w, ps.FIG_W, places=3,
                               msg='画布宽变了，Word 里的缩放比就不再是 1')
        self.assertAlmostEqual(h, ps.FIG_H, places=3)

    def test_every_figure_lays_out_inside_canvas(self):
        """源码层面确认：每个 make_* 都做过画布内布局，别再有漏网的。

        ⚠ 这条挡的是「新加一张图忘了调边距」——附录图 7~9 当初调了
        ``tight_layout(rect=...)`` 所以没坏，正文图 2~6 一直没调，
        于是只有它出问题。

        判据是**有没有做过布局**，不是「必须调 _layout()」：附录图因为
        三 panel 并排、纵轴标签很长，需要手工指定 ``rect`` 留左边距，
        走的是 ``tight_layout(rect=...)`` 这条等价路径。

        ⚠ 只认 ``make_*`` 函数体：``_layout()`` 辅助函数自己结尾就是
        ``return fig``，``SubFigure`` 之类也各有返回，按行正则全文扫会误报。
        """
        import ast
        src = (REPO_ROOT / TOOL / 'pcal' / 'plotting.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        missing = []
        checked = []
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith('make_'):
                continue
            checked.append(node.name)
            names = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    if isinstance(fn, ast.Name):
                        names.add(fn.id)
                    elif isinstance(fn, ast.Attribute):
                        names.add(fn.attr)
            has_layout = bool(names & {'_layout', 'tight_layout',
                                       'constrained_layout'})
            if not has_layout:
                missing.append((node.name, node.lineno))
        self.assertTrue(checked, '没找到 make_* 函数，检查本测试的前提')
        self.assertEqual(missing, [],
                         '这些函数没做画布内布局，轴标签会被画布裁掉：%r'
                         % (missing,))

    def test_savefig_does_not_use_bbox_tight(self):
        """不许用 bbox_inches='tight' 绕过问题：它会让画布宽 ≠ 插入宽。"""
        src = (REPO_ROOT / TOOL / 'pcal' / 'report.py').read_text(encoding='utf-8')
        self.assertNotIn("bbox_inches='tight'", src,
                         "report.py 用了 bbox_inches='tight'：图的实际尺寸会变，"
                         '画布宽就不再等于 Word 插入宽，fontsize 不再是印刷真字号')


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
