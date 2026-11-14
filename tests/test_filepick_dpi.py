# -*- coding: utf-8 -*-
"""系统文件/文件夹对话框必须声明 DPI 感知。

守的是 2026-11-14 用户报的真实缺陷：「导入数据选择文件夹界面分辨率太低」。

根因：``filepick.py`` 用子进程开 tkinter 的 ``askdirectory`` / ``askopenfilename``，
但子进程从未声明 DPI 感知。Windows 对「不声明」的进程按 96 DPI 处理、再把整窗
位图拉伸到显示器缩放 —— 用户机器是 200%，于是系统对话框被放大 2 倍，又小又糊。

实测（本机 200%，逻辑分辨率 1440x852）：

    无声明  aware_at_start=0  dialog_dpi=96   size=720x501
    加声明  aware_at_start=0  dialog_dpi=192  size=1440x1002

物理尺寸不变（同一个对话框），但设备像素翻倍、文字按原生分辨率绘制。

这些用例只验「代码串里确实声明了、且声明在开窗之前」——不弹真窗口，
所以能在无桌面环境下跑。真实的 DPI 效果由 ``_tmp/dpi_verify3.py`` 那类
探针人工核对。
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

#: 任何一条能真正让进程变成 DPI 感知的 Windows API
AWARE_APIS = ('SetProcessDpiAwarenessContext', 'SetProcessDpiAwareness',
              'SetProcessDPIAware')


class FilePickDpiTests(unittest.TestCase):
    """共享层 `_core/filepick.py` 的两个对话框代码串。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(support.REPO_ROOT))
        try:
            from _core import filepick
        finally:
            sys.path.pop(0)
        cls.fp = filepick

    def test_prelude_declares_awareness(self):
        """前置代码里必须真的有 DPI 感知调用，且有三级兜底。"""
        prelude = self.fp.dpi_awareness_prelude()
        found = [api for api in AWARE_APIS if api in prelude]
        self.assertTrue(found, '前置代码没有调用任何 DPI 感知 API')
        self.assertGreaterEqual(
            len(found), 2,
            '只有 %s 一种兜底：老系统上会静默退回「不感知」，这个缺陷会复发'
            % found[0])

    def test_prelude_runs_before_window_creation(self):
        """声明必须排在真正的 `root = tk.Tk()` 之前——开窗之后再声明对已建窗口无效。

        ⚠ 不能拿 ``code.index('tk.Tk()')`` 当基准：前置代码的 docstring 里就写着
        「含 tk.Tk()」，会先命中注释里的那次（这个用例第一版就是这么假红的）。
        要匹配真正建窗的那一行。
        """
        real_tk = re.compile(r'^\s*root\s*=\s*tk\.Tk\(\)', re.M)
        for name in ('_DIR_CODE', '_FILE_CODE'):
            code = getattr(self.fp, name)
            mtk = real_tk.search(code)
            self.assertIsNotNone(mtk, '%s 里找不到真正的 root = tk.Tk()' % name)
            # 前置代码末尾对 _pcal_enable_dpi_awareness() 的那次调用
            call = code.find('_pcal_enable_dpi_awareness()\n')
            call = code.rfind('_pcal_enable_dpi_awareness()', 0, mtk.start())
            self.assertGreaterEqual(call, 0,
                                    '%s 在 tk.Tk() 之前没调用 DPI 声明' % name)
            self.assertLess(call, mtk.start(),
                            '%s 的 DPI 声明排在建窗之后（无效）' % name)

    def test_both_dialogs_covered(self):
        """选择文件夹与选择文件都要带前置代码，不能只修一个。"""
        prelude = self.fp.dpi_awareness_prelude()
        for name in ('_DIR_CODE', '_FILE_CODE'):
            code = getattr(self.fp, name)
            self.assertTrue(code.lstrip().startswith(prelude.strip()[:40]),
                            '%s 没带 DPI 前置代码：这个对话框仍会被拉伸' % name)
            compile(code, name, 'exec')

    def test_prelude_is_valid_python(self):
        """前置代码能单独编译（写错缩进会让对话框永远弹不出来）。"""
        compile(self.fp.dpi_awareness_prelude(), 'prelude', 'exec')

    def test_graceful_on_import_failure(self):
        """拿不到 ctypes 时不能抛异常——否则对话框打不开、用户只看到超时。"""
        prelude = self.fp.dpi_awareness_prelude()
        self.assertIn("return 'none'", prelude,
                      '前置代码没有失败出口：无 ctypes 的环境会直接崩')
        self.assertNotIn('raise', prelude,
                         '前置代码不该向外抛异常（宁可退回不感知）')

    def test_synced_to_all_tools(self):
        """11 个工具的 pcal/filepick.py 必须与共享层一致。"""
        canon = (support.REPO_ROOT / '_core' / 'filepick.py').read_bytes()
        canon = canon.replace(b'\r\n', b'\n')
        for tool in TOOLS:
            path = support.REPO_ROOT / tool / 'pcal' / 'filepick.py'
            self.assertTrue(path.exists(), '%s 缺 pcal/filepick.py' % tool)
            data = path.read_bytes().replace(b'\r\n', b'\n')
            self.assertEqual(data, canon,
                             '%s/pcal/filepick.py 与共享层不一致；'
                             '跑 python _core/sync_core.py --apply' % tool)


class GcalcPickDpiTests(unittest.TestCase):
    """高斯计算工具是独立仓库，自己留了一份 `pick_folder`。"""

    def test_gcalc_pick_folder_declares_awareness(self):
        src = (support.REPO_ROOT / '高斯计算工具' / 'gcalc' / 'server.py').read_text(
            encoding='utf-8')
        seg = src[src.index('_DPI_PRELUDE'):src.index('def pick_folder')]
        self.assertTrue(
            any(api in seg for api in AWARE_APIS),
            '高斯计算工具的 _DPI_PRELUDE 没有 DPI 感知调用')
        # 前置代码必须被拼到实际执行的 code 里
        after = src[src.index('def pick_folder'):]
        after = after[:after.index('env = dict')]
        self.assertIn('_DPI_PRELUDE', after,
                      '定义了前置代码却没拼进子进程代码串，等于没改')
        self.assertLess(after.index('_DPI_PRELUDE'), after.index('tk.Tk()'),
                        '高斯计算工具的前置代码排在 tk.Tk() 之后')


class SplashDpiTests(unittest.TestCase):
    """启动画面（`_tools/splash.py`）是同一类问题，但它有额外的坑。

    声明 DPI 感知之后，tk 的坐标变成物理像素，写死的 ``W, H = 440, 150``
    在 200% 机上只剩一半物理尺寸（实测 220x75）。所以必须同时按缩放放大。
    """

    @classmethod
    def setUpClass(cls):
        cls.src = (support.REPO_ROOT / '_tools' / 'splash.py').read_text(
            encoding='utf-8')

    def test_declares_awareness(self):
        self.assertTrue(any(api in self.src for api in AWARE_APIS),
                        'splash 没有声明 DPI 感知：卡片会被拉伸 2 倍发糊')

    def test_declared_before_window(self):
        aware = min((self.src.index(api) for api in AWARE_APIS if api in self.src),
                    default=-1)
        tk_pos = self.src.index('root = tk.Tk()')
        self.assertGreaterEqual(aware, 0)
        self.assertLess(aware, tk_pos, 'splash 的 DPI 声明排在建窗之后（无效）')

    def test_scales_geometry(self):
        """几何尺寸必须按缩放放大，否则声明感知后卡片物理尺寸减半。

        实测（200%）：声明感知但不缩放 → 440x150 设备像素 = 220x75 物理当量，
        比原来的 440x150 缩了一半；缩放后 880x300 设备像素 = 440x150 当量，
        与修复前物理尺寸一致、但按原生分辨率绘制。
        """
        self.assertIn('W_BASE', self.src,
                      '没有保留 96 DPI 设计尺寸基准，无法按缩放换算')
        self.assertIn('winfo_fpixels', self.src,
                      '没有读取实际 DPI，无法算出缩放比例')
        self.assertIn('W = int(round(W_BASE * scale))', self.src,
                      'W 没有按 scale 换算：200% 机上卡片只有一半大')
        self.assertIn('H = int(round(H_BASE * scale))', self.src,
                      'H 没有按 scale 换算：200% 机上卡片只有一半大')
        # 内边距/字号也要跟着放大，否则 200% 上字挤在角落、进度条过短
        self.assertIn('pad(', self.src,
                      '内边距与字号没有跟随缩放（只放大外框会显得空旷）')

    def test_survives_missing_tkinter(self):
        """没有 tkinter 时静默跳过，不能因此让启动失败。"""
        self.assertIn('return 0', self.src)
        idx = self.src.index('import tkinter as tk')
        self.assertIn('return 0', self.src[idx:idx + 400],
                      '拿不到 tkinter 时没有安全退出')


if __name__ == '__main__':
    unittest.main(verbosity=2)