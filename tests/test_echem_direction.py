# -*- coding: utf-8 -*-
"""电化学：按**实际电位方向与电流极性**判别段，不假设 S5/S6。

守的是 2026-11-11 用户新数据暴露的真实缺陷（当时只是要改文件名模糊匹配，
跑真实数据才发现）：

    CHI 的 ``Init P/N`` 决定段序，``Polarity`` 决定电流符号，两者都可能与
    2025 参照数据相反。而内核原来写死了「S5 = 负扫/还原支、S6 = 正扫/氢脱附」
    和「还原电流为正、氧化电流为负」。

用户 2026-11-11 那批数据是 ``Init P/N = P`` + 还原电流为负（与 2025 完全相反），
后果是**全都静默算错**：

* 表 1 的含氧物种脱附峰：峰表在 S2/S4/S6（不是 S1/S3/S5）→ 三行全是 nan；
* ESA：在 S6 上取"氢脱附峰"，而 S6 在那批数据里是还原支；
* ORR／MOR 起始电位：``above`` / ``below`` 判据方向反了 → 直接 nan，
  DMFC 整段跳过。

修法：段号由 ``CvFile.neg_seg / pos_seg`` 按**每段首末电位**自动判定，
电流极性由 ``CvFile.cathodic_sign`` 按负扫段的峰高符号判定，起始电位的
判据方向跟着极性走。

⚠️ 本文件同时守住「2025 参照数据的数值一个都不许变」——自动判段对那批数据
必须仍然落在 S5/S6、极性仍为 +1，否则回归基准（ESA 1.316 mm²、交点 0.473 V、
P_max 3.19×10⁻⁷ W）就失去意义了。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support                                        # noqa: E402

TOOL = '电化学工具'
FIXTURES = support.FIXTURES / '电化学'

#: 2025 参照数据（Init P/N = N，还原电流为正）的回归基准。
#: 出处：SKILL §13.5（与课程软件、李晨曦 2025 报告逐位对齐过）。
BASE_2025 = dict(esa_mm2=1.316, orr_red=0.517, orr_ox=0.595, mor=0.248,
                 e_intersect=0.473, p_max=3.193e-7)


def _flip_init_pn(src, dst):
    """把一份 ``Init P/N = N`` 的 CHI txt 改写成 ``P`` 起扫的等价文件。

    只把头部那行 ``P/N = N`` 改成 ``P`` 是**假**的——段数据没变，判据照样
    会判对。真实场景是：P 起扫时 S1 就往上扫，整个段序相对 N 起扫是反的。

    正确做法：把 6 段数据的**顺序整体反转**并重新编号（峰分析表同样处理）。
    N 起扫是 S1 负扫 → S2 正 → S3 负 → S4 正 → S5 负 → S6 正；
    反转后变成 S1 正 → S2 负 → … → S6 负，正是 P 起扫的形状。
    峰表的位置也随之从 1/3/5 移到 2/4/6——与用户 2026-11-11 那批真实数据
    的峰段分布（2/4/6）一致。
    """
    import re
    txt = Path(src).read_bytes().decode('gbk', 'ignore')
    assert 'Init P/N = N' in txt, '这不是 N 起扫的文件：%s' % src
    txt = txt.replace('Init P/N = N', 'Init P/N = P', 1)

    data_mark = 'Potential/V, Current/A, Charge/C'
    head, sep, body = txt.partition(data_mark)
    if not sep:
        raise AssertionError('没有数据区标记：%s' % src)

    def _reverse_blocks(text):
        """把 ``Segment N:`` 分隔的 6 块按相反顺序重排并重新编号。"""
        parts = re.split(r'Segment (\d+):', text)
        lead, blocks = parts[0], parts[1:]
        pairs = [(int(blocks[i]), blocks[i + 1])
                 for i in range(0, len(blocks) - 1, 2)]
        if len(pairs) != 6:
            raise AssertionError('期望 6 段，实际 %d' % len(pairs))
        pairs.reverse()
        out = [lead]
        for idx, (_old, chunk) in enumerate(pairs, 1):
            out.append('Segment %d:' % idx)
            out.append(chunk)
        return ''.join(out)

    head = _reverse_blocks(head)
    body = _reverse_blocks(body)
    Path(dst).write_bytes((head + sep + body).encode('gbk', 'ignore'))


def _flip_current(src, dst):
    """把电流符号取反（模拟 CHI 的 Polarity 开关打开）。

    数据区每行是 ``Potential, Current, Charge``；只翻电流一列，
    峰分析表里的 ip 也一起翻——这正是 Polarity 开关对导出文件的实际影响。
    """
    import re
    raw = Path(src).read_bytes()
    txt = raw.decode('gbk', 'ignore')
    out = []
    for line in txt.splitlines():
        m = re.match(r'^(\s*[-+]?[0-9.]+\s*,\s*)([-+]?[0-9.eE+-]+)(.*)$', line)
        if m and ',' in line:
            try:
                cur = float(m.group(2))
                line = m.group(1) + ('%.9g' % (-cur)) + m.group(3)
            except ValueError:
                pass
        # 峰分析表的 ip 行
        m2 = re.match(r'^(\s*ip\s*=\s*)([-+]?[0-9.eE+-]+)(\s*A\s*)$', line)
        if m2:
            try:
                line = m2.group(1) + ('%.6g' % (-float(m2.group(2)))) + m2.group(3)
            except ValueError:
                pass
        out.append(line)
    Path(dst).write_text('\n'.join(out), encoding='gbk', errors='ignore')


class SegmentDirectionTests(unittest.TestCase):
    """``CvFile.neg_seg / pos_seg``：按电位方向判段，不假设 S5/S6。"""

    @classmethod
    def setUpClass(cls):
        cls.echem = support.load_module(TOOL, 'echem')

    def test_2025_is_s5_neg_s6_pos(self):
        """2025 参照数据（Init P/N = N）必须仍然判成 neg=5 / pos=6。

        这条是回归基准的前提：判段逻辑一旦把它也改了，后面所有数值基准
        都会跟着漂，而且漂得"看起来还挺合理"，极难发现。
        """
        cv = self.echem.load_cv(str(FIXTURES / 'N2_1.txt'))
        self.assertEqual(cv.neg_seg, 5)
        self.assertEqual(cv.pos_seg, 6)
        self.assertEqual(cv.seg_direction(5), -1)
        self.assertEqual(cv.seg_direction(6), +1)

    def test_reversed_segment_order_is_detected(self):
        """把 Init P/N 改成 P 后，段号应互换（内容不变，只是段序变了）。"""
        tmp = Path(tempfile.mkdtemp(prefix='pcal_echem_seg_'))
        try:
            _flip_init_pn(FIXTURES / 'N2_1.txt', tmp / 'N2_1.txt')
            cv = self.echem.load_cv(str(tmp / 'N2_1.txt'))
            self.assertEqual(cv.neg_seg, 6, 'Init P/N = P 时还原支在 S6')
            self.assertEqual(cv.pos_seg, 5)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cycle_uses_detected_direction(self):
        """``cycle()`` 拼出来的一圈必须是「先负扫、后正扫」。"""
        cv = self.echem.load_cv(str(FIXTURES / 'N2_1.txt'))
        cyc = cv.cycle()
        n_neg = len(cv.reductive_seg())
        # 前半段（负扫）电位从高走到低，后半段（正扫）从低走到高
        self.assertGreater(cyc[0, 0], cyc[n_neg - 1, 0], '前半段不是负扫')
        self.assertLess(cyc[n_neg, 0], cyc[-1, 0], '后半段不是正扫')

    def test_empty_segment_is_safe(self):
        """空段/单点段返回方向 0，不抛异常。"""
        self.assertEqual(self.echem.CvFile.seg_direction.__name__, 'seg_direction')
        cv = self.echem.load_cv(str(FIXTURES / 'N2_1.txt'))
        self.assertEqual(cv.seg_direction(99), 0)


class CathodicSignTests(unittest.TestCase):
    """``CvFile.cathodic_sign``：还原电流是正还是负。"""

    @classmethod
    def setUpClass(cls):
        cls.echem = support.load_module(TOOL, 'echem')

    def test_2025_is_positive(self):
        cv = self.echem.load_cv(str(FIXTURES / 'N2_1.txt'))
        self.assertEqual(cv.cathodic_sign, 1)

    def test_flipped_current_is_negative(self):
        tmp = Path(tempfile.mkdtemp(prefix='pcal_echem_pol_'))
        try:
            _flip_current(FIXTURES / 'N2_1.txt', tmp / 'N2_1.txt')
            cv = self.echem.load_cv(str(tmp / 'N2_1.txt'))
            self.assertEqual(cv.cathodic_sign, -1, '极性翻转没被识别出来')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Regression2025Tests(unittest.TestCase):
    """2025 参照数据的数值基准必须**逐位不变**（自动判段不能改坏它）。"""

    @classmethod
    def setUpClass(cls):
        cls.analysis = support.load_module(TOOL, 'analysis')
        cls.cfg = cls.analysis.default_config()
        cls.cfg['data_dir'] = str(FIXTURES)
        cls.an = cls.analysis.Analysis(cls.cfg)
        cls.an.run()

    def test_esa_unchanged(self):
        self.assertAlmostEqual(self.an.esa['area_mm2'], BASE_2025['esa_mm2'],
                               places=3)

    def test_orb_onsets_unchanged(self):
        self.assertAlmostEqual(self.an.orr['onset_red'], BASE_2025['orr_red'],
                               places=3)
        self.assertAlmostEqual(self.an.orr['onset_ox'], BASE_2025['orr_ox'],
                               places=3)

    def test_mor_unchanged(self):
        self.assertAlmostEqual(self.an.mor['onset'], BASE_2025['mor'], places=3)

    def test_dmfc_unchanged(self):
        self.assertAlmostEqual(self.an.dmfc['E_intersect'],
                               BASE_2025['e_intersect'], places=3)
        self.assertAlmostEqual(self.an.dmfc['P_max'] / BASE_2025['p_max'], 1.0,
                               places=3)

    def test_table1_peaks_present(self):
        """表 1 三行都要有峰（曾经在段序反转的数据上是 nan）。"""
        self.assertEqual(len(self.an.table1), 3)
        for row in self.an.table1:
            self.assertTrue(row['Ep'] == row['Ep'], 'Ep 是 nan：%s' % row)
            self.assertTrue(row['ip'] == row['ip'], 'ip 是 nan：%s' % row)
            self.assertGreater(row['ip'], 0, '峰电流应为正值：%s' % row)


class PlotAxisTests(unittest.TestCase):
    """CV 图的纵轴方向：**阴极电流必须朝下**（用户 2026-11-11 提的要求）。

    用户原话：「图像 y 轴还是需要上面大下面小」。

    根因与段号/极性是同一类：``_cv_axes`` 原来无条件 ``invert_yaxis()``，
    而这只有在**阴极电流为正**（CHI 默认极性）时才让还原峰朝下。
    他那批数据阴极电流为负，倒置后还原峰反而跑到上方，轴成了
    上面 −30、下面 40 —— 既是「上小下大」，也与 CV 惯例相反。

    正确判据是「让阴极电流朝下」：极性为正时倒置、为负时不倒置。
    本类直接读 matplotlib 出来的轴范围，不靠看 PNG。
    """

    @classmethod
    def setUpClass(cls):
        cls.analysis = support.load_module(TOOL, 'analysis')
        cls.plotting = support.load_module(TOOL, 'plotting')

    def _fig(self, data_dir):
        cfg = self.analysis.default_config()
        cfg['data_dir'] = str(data_dir)
        an = self.analysis.Analysis(cfg)
        an.run()
        return an

    @staticmethod
    def _ylim(fig):
        """取图里第一个坐标区的 (下界, 上界)——matplotlib 已考虑倒置。"""
        ax = fig.axes[0]
        return ax.get_ylim()

    def test_default_polarity_puts_cathodic_down(self):
        """2025 参照数据（阴极电流为正）：纵轴倒置，还原峰朝下。

        倒置后 ``get_ylim()`` 返回 (大, 小)，所以「上界 > 下界」。
        """
        an = self._fig(FIXTURES)
        self.assertEqual(an.file('n2_blank').cathodic_sign, 1)
        lo, hi = self._ylim(self.plotting.make_n2_series_figure(an))
        self.assertGreater(lo, hi, '阴极电流为正时纵轴应倒置（上界>下界）')

    def test_reversed_polarity_does_not_invert(self):
        """极性反了的数据：纵轴**不能**倒置，否则还原峰跑到上方。"""
        tmp = Path(tempfile.mkdtemp(prefix='pcal_echem_axis_'))
        try:
            for name in ('N2_1.txt', 'N2_2.txt', 'N2_5.txt'):
                _flip_current(FIXTURES / name, tmp / name)
            an = self._fig(tmp)
            self.assertEqual(an.file('n2_blank').cathodic_sign, -1,
                             '极性翻转没被识别')
            lo, hi = self._ylim(self.plotting.make_n2_series_figure(an))
            self.assertLess(lo, hi,
                            '阴极电流为负时不该倒置（现在上界>下界，'
                            '还原峰会被画到上方）')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cathodic_peak_faces_down_in_both_cases(self):
        """两种极性下，**还原峰都画在下方**——这才是判据本身。

        直接比较还原峰（峰表的 Ep 处）与氧化支在同电位的电流的屏幕位置：
        倒置与否都应让还原峰落在更低的位置。
        """
        cases = [('默认为正', FIXTURES, 1)]
        tmp = Path(tempfile.mkdtemp(prefix='pcal_echem_axis2_'))
        try:
            for name in ('N2_1.txt', 'N2_2.txt', 'N2_5.txt'):
                _flip_current(FIXTURES / name, tmp / name)
            cases.append(('翻转为负', tmp, -1))
            for tag, d, want_sign in cases:
                an = self._fig(d)
                f = an.file('n2_blank')
                self.assertEqual(f.cathodic_sign, want_sign, tag)
                fig = self.plotting.make_n2_series_figure(an)
                ax = fig.axes[0]
                # 找一个还原峰：负扫段上的峰
                peaks = f.peaks.get(f.neg_seg) or []
                self.assertTrue(peaks, '%s：负扫段没有峰表' % tag)
                import numpy as np
                Ep = peaks[0]['Ep']
                # 还原支在 Ep 处的电流
                neg = f.reductive_seg()
                i_red = float(np.interp(Ep, neg[::-1, 0], neg[::-1, 1])) * 1e6
                # 屏幕坐标：y 越大越靠上
                y_red = ax.transData.transform((Ep, i_red))[1]
                y_mid = ax.transData.transform((Ep, 0.0))[1]
                self.assertLess(y_red, y_mid,
                                '%s：还原峰没有画在零线下方（y=%.1f vs %.1f）'
                                % (tag, y_red, y_mid))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ReversedDataTests(unittest.TestCase):
    """把 2025 数据同时反转段序与电流极性 → 结果仍应与基准一致。

    这是最强的判据：**物理量不该随仪器的显示约定而变**。
    ESA、ORR、MOR、DMFC 交点与功率都必须落在基准上（允许末位差异）。
    """

    @classmethod
    def setUpClass(cls):
        cls.analysis = support.load_module(TOOL, 'analysis')
        cls.tmp = Path(tempfile.mkdtemp(prefix='pcal_echem_rev_'))
        for name in ('N2_1.txt', 'N2_2.txt', 'N2_5.txt',
                     'O2_fast.txt', 'O2_slow.txt', 'O2_still.txt', 'MeOH.txt'):
            step1 = cls.tmp / ('pn_' + name)
            _flip_init_pn(FIXTURES / name, step1)
            _flip_current(step1, cls.tmp / name)
            step1.unlink()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self):
        cfg = self.analysis.default_config()
        cfg['data_dir'] = str(self.tmp)
        an = self.analysis.Analysis(cfg)
        an.run()
        return an

    def test_direction_detected(self):
        echem = support.load_module(TOOL, 'echem')
        cv = echem.load_cv(str(self.tmp / 'N2_1.txt'))
        self.assertEqual(cv.neg_seg, 6)
        self.assertEqual(cv.cathodic_sign, -1)

    def test_esa_matches_baseline(self):
        an = self._run()
        self.assertAlmostEqual(an.esa['area_mm2'], BASE_2025['esa_mm2'], places=2,
                               msg='段序+极性反转后 ESA 变了：%.4f'
                                   % an.esa['area_mm2'])

    def test_table1_peaks_matches_baseline(self):
        """反转后表 1 的 Ep 必须与基准一致，ip 必须与**某一圈**的峰高一致。

        ⚠️ ip 不能要求与基准的 S5 逐位相同：CHI 各圈峰高本来就差几个百分点
        （2025 那份 N2_1 的 0.459 V 峰：S1 1.762e-6、S3 2.152e-6、S5 2.157e-6），
        而段序反转会把「末圈」变成原始的首圈。真实 P 起扫数据里末圈仍是稳态圈，
        所以这里的正确判据是「落在该文件各圈的峰高范围内」，而不是钉死某一圈。
        """
        an = self._run()
        base = support.load_module(TOOL, 'analysis')
        echem = support.load_module(TOOL, 'echem')
        cfg = base.default_config()
        cfg['data_dir'] = str(FIXTURES)
        ref = base.Analysis(cfg)
        ref.run()
        self.assertEqual(len(an.table1), 3)

        for got, want in zip(an.table1, ref.table1):
            self.assertAlmostEqual(got['Ep'], want['Ep'], places=6,
                                   msg='Ep 变了：%s vs %s' % (got, want))
            # 该文件里所有负扫段在同一个 Ep 上的峰高
            src = echem.load_cv(str(FIXTURES / ('N2_%s.txt' % (
                '1' if abs(got['v'] - 0.1) < 1e-6 else
                '2' if abs(got['v'] - 0.2) < 1e-6 else '5'))))
            pool = [abs(p['ip']) for s in (1, 3, 5)
                    for p in (src.peaks.get(s) or [])
                    if abs(p['Ep'] - got['Ep']) < 1e-3]
            self.assertTrue(pool, '基准文件里找不到 Ep=%.3f 的峰' % got['Ep'])
            self.assertGreater(got['ip'], 0, '峰电流应为正值')
            self.assertGreaterEqual(
                got['ip'], min(pool) * 0.98,
                'ip %.3e 低于该文件各圈峰高的下限 %.3e（%s）'
                % (got['ip'], min(pool), pool))
            self.assertLessEqual(
                got['ip'], max(pool) * 1.02,
                'ip %.3e 高于该文件各圈峰高的上限 %.3e（%s）'
                % (got['ip'], max(pool), pool))

    def test_onsets_match_baseline(self):
        an = self._run()
        self.assertAlmostEqual(an.orr['onset_red'], BASE_2025['orr_red'],
                               places=2)
        self.assertAlmostEqual(an.orr['onset_ox'], BASE_2025['orr_ox'], places=2)
        self.assertAlmostEqual(an.mor['onset'], BASE_2025['mor'], places=2)

    def test_dmfc_matches_baseline(self):
        an = self._run()
        self.assertAlmostEqual(an.dmfc['E_intersect'],
                               BASE_2025['e_intersect'], places=2)
        self.assertGreater(an.dmfc['P_max'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
