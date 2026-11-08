# -*- coding: utf-8 -*-
"""入口页端口区间的纯函数守卫（不起服务、不占端口，<2 秒）。

背景（2026-11-08 审计 D P1-2 实测）：
`find_portal_port()` 原来只扫 `range(*PORTAL_PORTS)` = 8700..8729（30 个），
但入口自己挑端口走的是 `_free_port(preferred)` = `range(preferred, preferred+60)`，
能返回到 8759。占住 8700..8729 后入口落到 **8730**，那个端口在自己扫描范围之外，
于是"再点一次快捷方式"会因为找不到已在跑的入口而**再起一套**——实测同时在服务
:8730 与 :8731。

修法（本文件守着这三条）：
1. 扫描宽度 == 挑端口宽度（否则又会出现盲区）；
2. 入口区间与 11 个模块的首选端**口完全不相交**（模块从 8731 起）；
3. 模块端口仍用足够大的后移宽度（60），别被"统一常量"误伤。
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from support import REPO_ROOT

PORTAL_PATH = REPO_ROOT / '物化实验报告工具' / 'portal.py'


def load_portal(name='pcal_portal_ports_test'):
    """按文件路径载入 portal（不 import 包，避免 sys.path 差异）。"""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PORTAL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError('无法载入 %s' % PORTAL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PortalPortSpanTests(unittest.TestCase):
    """单实例守卫的核心不变式：扫得到的端口 == 挑得到的端口。"""

    @classmethod
    def setUpClass(cls):
        cls.portal = load_portal()

    def test_scan_width_equals_free_port_width(self):
        """find_portal_port() 的扫描宽度必须等于入口 _free_port() 的后移宽度。

        这两者一旦不等，入口就会落在自己扫描范围之外的端口上：
        用户在盲区端口上已经有了一个入口，`main()` 的 existing 检查却返回 0，
        于是再起一个入口（两个浏览器标签、两套服务）。
        """
        scan = list(range(*self.portal.PORTAL_PORTS))
        self.assertEqual(
            len(scan), self.portal.PORTAL_SPAN,
            'find_portal_port 扫 %d 个端口，但入口 _free_port 会往后找 %d 个：'
            '相差的 %d 个端口就是"再点一次起第二个入口"的盲区'
            % (len(scan), self.portal.PORTAL_SPAN,
               abs(len(scan) - self.portal.PORTAL_SPAN)))
        # 盲区必须是空的：入口能挑到的最大端口，必须在扫描范围内
        entry_max = self.portal.PORTAL_PORTS[0] + self.portal.PORTAL_SPAN - 1
        self.assertIn(entry_max, scan,
                      '入口能挑到 %d，但扫描只到 %d —— 这个端口就是盲区'
                      % (entry_max, scan[-1]))

    def test_free_port_span_matches_constants(self):
        """_free_port 的默认宽度仍是 FREE_PORT_SPAN（模块端口依赖这个 60）。"""
        self.assertGreaterEqual(self.portal.FREE_PORT_SPAN, 60,
                                '模块端口间隔 10，后移宽度不能小于 60，'
                                '否则相邻模块占位时找不到空闲端口')

    def test_portal_range_does_not_overlap_module_ports(self):
        """入口区间必须与 11 个模块的首选端口完全不相交。

        模块端口从 8731 起（8731/8741/…/8831）。入口区间一旦越界到 8730+，
        就会抢走某个模块的首选端口，把那个模块挤到偏移端口上（用户看到的
        端口和 README/文档里写的不一致）。
        """
        portal_range = set(range(*self.portal.PORTAL_PORTS))
        mod_ports = {m['port']: m['tool'] for m in self.portal.MODULES}
        overlap = sorted(portal_range & set(mod_ports))
        self.assertEqual(
            overlap, [],
            '入口区间 %r 覆盖了模块端口 %r（对应 %r）——'
            '入口会抢走这些模块的首选端口'
            % (self.portal.PORTAL_PORTS, overlap,
               [mod_ports[p] for p in overlap]))

    def test_no_module_port_inside_portal_range_even_after_shift(self):
        """模块端口区间（首选 + 后移）不该与入口区间撞上「首选」。

        这里只断言**首选**端口（上一条已覆盖）与入口区间不相交；
        模块后移是运行时兜底，允许偶尔落到别处，不做硬断言。
        """
        portal_range = set(range(*self.portal.PORTAL_PORTS))
        for mod in self.portal.MODULES:
            self.assertNotIn(mod['port'], portal_range,
                             '%s 的首选端口 %d 落在入口区间里'
                             % (mod['tool'], mod['port']))

    def test_eleven_modules_registered(self):
        """11 个模块都在，端口互不相同（不然两个模块会互相抢端口）。"""
        mods = self.portal.MODULES
        self.assertEqual(len(mods), 11, '入口登记了 %d 个模块，应为 11' % len(mods))
        ports = [m['port'] for m in mods]
        self.assertEqual(len(ports), len(set(ports)),
                         '模块端口有重复：%r' % sorted(ports))
        keys = [m['key'] for m in mods]
        self.assertEqual(len(keys), len(set(keys)), '模块 key 有重复')

    def test_portal_ports_tuple_shape(self):
        """PORTAL_PORTS 是 (lo, hi) 左闭右开，且 lo 是入口首选端口。"""
        lo, hi = self.portal.PORTAL_PORTS
        self.assertIsInstance(lo, int)
        self.assertIsInstance(hi, int)
        self.assertLess(lo, hi, 'PORTAL_PORTS 必须是 (lo, hi) 且 lo < hi')
        self.assertEqual(lo, 8700, '入口首选端口应保持 8700（README 里写的就是它）')
        self.assertGreater(lo, 1023, '入口不该用特权端口（<1024）')


class FreePortSignatureTests(unittest.TestCase):
    """_free_port 的签名约定：入口传 PORTAL_SPAN，模块用默认。"""

    @classmethod
    def setUpClass(cls):
        cls.portal = load_portal('pcal_portal_ports_test2')

    def test_free_port_accepts_span(self):
        import inspect
        sig = inspect.signature(self.portal._free_port)
        self.assertIn('span', sig.parameters,
                      '_free_port 必须能接收 span，否则入口没法只在自己的区间里找端口')

    def test_entry_calls_free_port_with_portal_span(self):
        """源码层面确认 main() 给入口挑端口时传了 PORTAL_SPAN。

        这条挡的是"改了常量但忘了改调用点"——常量相等、调用点仍用默认 60，
        盲区照样存在。
        """
        src = PORTAL_PATH.read_text(encoding='utf-8')
        self.assertIn('_free_port(PORTAL_PORTS[0], PORTAL_SPAN)', src,
                      'main() 里入口挑端口必须显式传 PORTAL_SPAN，'
                      '不能沿用模块的默认宽度 60')

    def test_module_start_uses_default_span(self):
        """模块挑端口仍用默认宽度（不传 span），否则模块端口范围会被砍窄。"""
        src = PORTAL_PATH.read_text(encoding='utf-8')
        self.assertIn("_free_port(mod['port'])", src,
                      '模块挑端口应保持 _free_port(mod[\'port\']) 的默认宽度')


if __name__ == '__main__':
    unittest.main()
