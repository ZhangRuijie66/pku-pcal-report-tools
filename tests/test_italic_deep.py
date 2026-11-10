# -*- coding: utf-8 -*-
"""正斜体回归：2026-11-10 用户报告的三个具体缺陷。

## 用户原话

> 这份报告正斜体又有问题了
> 还有有的H+的H是斜体

`tests/check_italic.py` 当时报「共 0 处」——因为它只查「该正体却写成斜体」
一个方向，而且只认拉丁字母。真实缺陷三类，它一条都覆盖不到：

| 缺陷 | check_italic 为什么看不到 |
| --- | --- |
| 表 3「线性化关系」列 α 排成正体 | 那是数据单元格，脚本只看 run 不看语义 |
| 正文 `α–t`、`ln(α−α∞)` 的 α 排成正体 | 只查「斜体用错」，不查「正体用错」 |
| `c(H⁺)` 的 H 排成斜体 | 只认 `[A-Za-z]{2,}` 整词，单字母元素不判 |

本文件把这三类钉死，全部在 **docx 的 XML 层**断言（不依赖渲染）。
"""
from __future__ import annotations

import sys
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support                                        # noqa: E402

TOOL = '化学动力学工具'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
ITALIC = {'italic': True}


def _dk():
    return support.load_module(TOOL, 'docxkit')


def _runs(p):
    """[(text, italic, vert)]。p 可以是 docx Paragraph 或 Element。"""
    el = getattr(p, '_p', p)          # 兼容 Paragraph 对象
    out = []
    for r in el.findall('.//' + W + 'r'):
        txt = ''.join(x.text or '' for x in r.findall(W + 't'))
        if not txt:
            continue
        rpr = r.find(W + 'rPr')
        it = False
        vert = None
        if rpr is not None:
            i = rpr.find(W + 'i')
            # ⚠ 必须看 w:val：python-docx 给「显式不斜体」写的是 <w:i w:val="0"/>
            it = i is not None and i.get(W + 'val') not in ('0', 'false')
            va = rpr.find(W + 'vertAlign')
            if va is not None:
                vert = va.get(W + 'val')
        out.append((txt, it, vert))
    return out


class HeaderSymbolTests(unittest.TestCase):
    """表头/单元格里的量符号：c(H⁺) 只斜 c，(H⁺) 整块正体。"""

    def test_split_header_symbol_c_h_plus(self):
        f = _dk()._split_header_symbol
        self.assertEqual(f('c(H^{+})'), [('c', True), ('(H^{+})', False)])

    def test_split_header_symbol_plain_var_stays_italic(self):
        f = _dk()._split_header_symbol
        for t in ('c_{suc}', 'k_{1}', 't_{1/2}', 'R^{2}', 'n', 'c_{nom}',
                  'α_{suc}'):
            segs = f(t)
            self.assertTrue(all(it for _, it in segs), '%s 应整块斜体' % t)

    def test_split_header_symbol_codes_upright(self):
        """6M、3M、A3 是组别/样品编号，正体。"""
        f = _dk()._split_header_symbol
        for t in ('6M', '3M', 'A3', 'B2'):
            self.assertEqual(f(t), [(t, False)], '%s 是编号，应正体' % t)

    def test_write_header_renders_h_upright(self):
        """整条链路：_write_header('c(H^{+}) / (mol·L^{-1})') 里 H 不斜。"""
        from docx import Document
        doc = Document()
        p = doc.add_paragraph()
        _dk().ReportBuilder._write_header(p, 'c(H^{+}) / (mol·L^{-1})', 10.5)
        runs = _runs(p)
        h_runs = [it for txt, it, _ in runs if 'H' in txt]
        self.assertTrue(h_runs, '没渲染出 H')
        self.assertFalse(any(h_runs), 'c(H⁺) 的 H 被排成了斜体：%s' % runs)
        # c 必须仍是斜体
        c_runs = [it for txt, it, _ in runs if txt.strip().startswith('c')]
        self.assertTrue(c_runs and c_runs[0], 'c 应斜体：%s' % runs)


class CellSegmentsTests(unittest.TestCase):
    """表 3「线性化关系」列：α、t 斜体，ln 与 – 正体。"""

    def _cell_runs(self, value):
        from docx import Document
        doc = Document()
        p = doc.add_paragraph()
        rb = _dk().ReportBuilder.__new__(_dk().ReportBuilder)
        rb.doc = doc
        rb._write_cell(p, value, 10.5)
        return _runs(p)

    def test_alpha_dash_t(self):
        runs = self._cell_runs([('t', 'α', ITALIC), ('t', '–', {}),
                                ('t', 't', ITALIC)])
        text = ''.join(t for t, _, _ in runs)
        self.assertEqual(text, 'α–t', '片段列表被印成了 %r（疑似把元组当文本）' % text)
        flags = {t: it for t, it, _ in runs}
        self.assertTrue(flags.get('α'), 'α 应斜体：%s' % runs)
        self.assertTrue(flags.get('t'), 't 应斜体：%s' % runs)
        self.assertFalse(flags.get('–'), '– 应正体：%s' % runs)

    def test_ln_stays_upright_in_cell(self):
        runs = self._cell_runs(
            [('t', 'ln', {}), ('t', '(α−α', ITALIC), ('t', '∞', {}),
             ('t', ')', ITALIC), ('t', '–', {}), ('t', 't', ITALIC)])
        text = ''.join(t for t, _, _ in runs)
        self.assertIn('ln', text)
        ln = [it for t, it, _ in runs if t == 'ln']
        self.assertTrue(ln and not ln[0], 'ln 是函数名，应正体：%s' % runs)

    def test_single_segment_tuple_not_mistaken_for_list(self):
        """('t', 'k_{1}', ITALIC) 是**一个片段**，不能当片段列表。

        2026-11-10 踩过：判据疏忽导致整串被印成 "ttt"。
        """
        runs = self._cell_runs(('t', 'k_{1}', ITALIC))
        text = ''.join(t for t, _, _ in runs)
        self.assertEqual(text, 'k1', '单片段被印成 %r' % text)
        self.assertTrue(runs[0][1], 'k 应斜体')


class ScriptItalicTests(unittest.TestCase):
    """上下标：变量斜体、数字/说明文字正体、元素符号正体。"""

    def _render(self, text, italic):
        from docx import Document
        doc = Document()
        p = doc.add_paragraph()
        _dk().add_rich_text(p, text, {'size': 10.5, 'italic': italic})
        return _runs(p)

    def test_superscript_variable_n_is_italic(self):
        """c(H⁺)ⁿ 的指数 n 是反应级数（变量），必须斜体。

        以前 _write_script 只在底数为斜体时才按块判，底数正体（化学式）
        就把上标 n 也排成正体。用户 2026-11-10 抓到。
        """
        runs = self._render('(H^{+})^{n}', False)
        n_runs = [(it, v) for t, it, v in runs if t == 'n']
        self.assertTrue(n_runs, '没渲染出 n：%s' % runs)
        self.assertTrue(n_runs[0][0], '上标 n 应斜体：%s' % runs)
        self.assertEqual(n_runs[0][1], 'superscript')

    def test_superscript_digit_upright(self):
        runs = self._render('R^{2}', True)
        d = [(it, v) for t, it, v in runs if t == '2']
        self.assertTrue(d and not d[0][0], 'R² 的 2 应正体：%s' % runs)

    def test_element_subscript_upright(self):
        """k_H 的 H 是「氢离子」，正体；但 Q_V 的 V 是变量，斜体。"""
        runs = self._render('k_{H}', False)
        h = [(it, v) for t, it, v in runs if t == 'H']
        self.assertTrue(h and not h[0][0], 'k_H 的 H 应正体：%s' % runs)

        runs = self._render('Q_{V}', True)
        v = [(it, vv) for t, it, vv in runs if t == 'V']
        self.assertTrue(v and v[0][0], 'Q_V 的 V 应是变量（斜体）：%s' % runs)

    def test_label_subscript_upright(self):
        """t_{1M} 的 1M 是组别标签，整块正体（不能把 M 排成斜体）。"""
        runs = self._render('t_{1M}', True)
        sub = [(t, it) for t, it, v in runs if v == 'subscript']
        self.assertTrue(sub, '没有下标 run：%s' % runs)
        self.assertFalse(any(it for _, it in sub),
                         '下标 1M 应整块正体：%s' % runs)


class CaptionItalicTests(unittest.TestCase):
    """图题：k_{1}–c(H⁺) 里 k、c 斜体，下标与 (H⁺) 正体。"""

    def _caption_runs(self, text, next_body=None):
        f = _dk()._split_caption_runs
        return f(text, next_body=next_body)

    def test_k1_caption_base_is_italic(self):
        """k_{1} 的底数 k 是量符号 → 斜体。

        以前题注切分器看到「单字母 + 纯数字下标」就判为化学物种排正体，
        于是图 6 的题注印出正体 k（用户抓到的正斜体问题之一）。
        """
        segs = self._caption_runs('k_{1}–c(H^{+}) 非线性拟合', next_body='1')
        k_italic = [it for seg, it in segs if seg == 'k']
        self.assertTrue(k_italic and k_italic[0], 'k 应斜体：%s' % segs)
        c_italic = [it for seg, it in segs if seg == 'c']
        self.assertTrue(c_italic and c_italic[0], 'c 应斜体：%s' % segs)

    def test_chem_species_caption_stays_upright(self):
        """N_{2}、O_{2} 是化学物种，整块正体（不能被当成量符号）。

        ⚠ 题注里常写成 ``N_{2} 的吸收峰``——字母后面紧跟 ``_``，不是文本末尾。
        判据若要求「字母在末尾」，N₂ 的 N 会被排成斜体（真实缺陷，已修）。
        """
        for t in ('N_{2} 的吸收峰', 'O_{2} 的峰'):
            segs = self._caption_runs(t, next_body='2')
            seg_text = ''.join(seg for seg, _ in segs)
            self.assertIn('N' if 'N' in t else 'O', seg_text)
            flags = [it for seg, it in segs if 'N' in seg or 'O' in seg]
            self.assertTrue(flags and not any(flags),
                            '%s 的化学物种字母应正体：%s' % (t, segs))

    def test_group_label_in_caption_upright(self):
        """「表2 1M、2M、3M 盐酸下…」里的 M 是编号，正体。

        切分器会把整段合成一个片段（M 前面贴数字 → 正体），所以断言
        「所有含 M 的片段都不斜」即可。
        """
        segs = self._caption_runs('表2  1M、2M、3M 盐酸下的数据')
        m_flags = [it for seg, it in segs if 'M' in seg]
        self.assertTrue(m_flags, '没切出含 M 的片段：%s' % segs)
        self.assertFalse(any(m_flags), '组别编号 M 应正体：%s' % segs)


class EndToEndTests(unittest.TestCase):
    """真生成一份报告，断言三类缺陷都不再出现。"""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.mkdtemp(prefix='ital_')
        cls._mods_before = set(sys.modules)
        k = support.load_module(TOOL, 'kinetics')
        ana = support.load_module(TOOL, 'analysis')
        rep = support.load_module(TOOL, 'report')
        cfg = ana.default_config()
        cfg.update({'student_name': '测', 'student_id': '1', 'group': '3',
                    'group_no': '8', 'date': 'd', 'room_temp': 22.0,
                    'pressure': 101.3, 'alpha_inf_mode': 'measured',
                    'order_group': '4M'})
        cls.an = k.analyze(k.sample_data(), cfg)
        cls.cfg = cfg
        cls.out = str(Path(cls.tmp) / 'r.docx')
        rep.build_report(cls.an, cfg, cls.out,
                         str(Path(cls.tmp) / 'fig'),
                         str(support.REPO_ROOT / TOOL / 'templates'
                             / '化学动力学报告模板2026.docx'))
        z = zipfile.ZipFile(cls.out)
        cls.doc = ET.fromstring(z.read('word/document.xml'))
        cls.paras = list(cls.doc.find('.//' + W + 'body').iter(W + 'p'))

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)
        for name in [m for m in sys.modules if m not in cls._mods_before]:
            if name == 'pcal' or name.startswith('pcal.'):
                del sys.modules[name]

    def _all_text(self):
        return '\n'.join(
            ''.join(t.text or '' for t in p.findall('.//' + W + 't'))
            for p in self.paras)

    def test_no_h_italic_in_c_h_plus(self):
        """全篇 c(H⁺) 里的 H 都不能是斜体。"""
        bad = []
        for pi, p in enumerate(self.paras):
            runs = _runs(p)
            for k, (txt, it, vert) in enumerate(runs):
                if txt.strip() == 'H' and it:
                    nxt = runs[k + 1][0].strip()[:1] if k + 1 < len(runs) else ''
                    prev = runs[k - 1][0].strip() if k > 0 else ''
                    # 只有 H 紧跟 + / 上标、且前一个不是变量时才是化学物种
                    if nxt in ('+', '⁺') or prev.endswith('('):
                        bad.append((pi, prev, nxt))
        self.assertEqual(bad, [], 'c(H⁺) 的 H 被排成斜体：%s' % bad[:5])

    def test_table3_expr_column_alpha_italic(self):
        """表 3 线性化关系列的 α 必须是斜体。"""
        found = False
        for p in self.paras:
            runs = _runs(p)
            txt = ''.join(t for t, _, _ in runs)
            if txt.strip() in ('α–t', 'ln(α−α∞)–t', '1/(α−α∞)–t'):
                found = True
                alphas = [it for t, it, _ in runs if 'α' in t]
                self.assertTrue(alphas and all(alphas),
                                '表 3 %r 的 α 应斜体：%s' % (txt, runs))
        self.assertTrue(found, '没找到表 3 的线性化关系单元格')

    def test_no_stray_markup(self):
        """正文不能漏出 markdown 的 ** 或字面下标记号。"""
        text = self._all_text()
        self.assertNotIn('**', text)
        self.assertNotIn('_{', text)
        self.assertNotIn('^{', text)

    def test_mlabel_not_italic_in_body(self):
        """正文里的 6M/4M 是组别编号，M 不能斜体。"""
        bad = []
        for pi, p in enumerate(self.paras):
            for txt, it, vert in _runs(p):
                if vert is None and txt.strip() in ('6M', '4M', '3M', '2M', '5M'):
                    if it:
                        bad.append((pi, txt))
        self.assertEqual(bad, [], '组别编号被排成斜体：%s' % bad[:5])


if __name__ == '__main__':
    unittest.main()
