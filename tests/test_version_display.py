# -*- coding: utf-8 -*-
"""发版后版本号显示：真源、各模块副本、以及「进程没重启」的提醒。

## 2026-11-26 用户实测撞到

发完 v1.4.5 后，入口页左上角仍显示「版本：v1.4.3 · 2026-11-25」。
用户原话：「上面的版本号没改，你以后记得改」。

**这是运行态问题，不是代码问题**：`portal.py` 的

    APP_VERSION = str(getattr(pcal_version, 'APP_VERSION', '') or '')

是**模块导入时**从 `pcal/version.py` 读进来的常量。发版把磁盘上的
version.py 改成 1.4.5 之后，21:25 就起来的那个入口页进程内存里还是
1.4.3，不重启永远不会变。

之前的发版脚本收尾只打印「发版完成 / 版本号 / tag」，**没有一句提醒
"旧进程还在跑"**，于是每次发版都可能看到旧版本号。本文件守住三件事：

1. 真源与 11 份副本必须一致（check_version 已覆盖，这里独立再钉一次）；
2. 发版脚本**必须**在收尾时检查并提示运行中的旧服务；
3. 那个检查函数本身要能用（找不到进程时不许抛异常）。
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import unittest

from support import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from _core import version as core_version       # noqa: E402

TOOL = '电导率工具'


def _module_source(name):
    return (REPO_ROOT / name).read_text(encoding='utf-8')


class VersionTruthTests(unittest.TestCase):
    """真源与副本一致（独立于 check_version.py 再钉一次）。"""

    def test_core_version_is_a_three_part_version(self):
        self.assertIsNotNone(core_version.version_tuple(core_version.APP_VERSION))
        self.assertRegex(core_version.APP_VERSION, r'^\d+\.\d+\.\d+$')

    def test_tool_copies_match_core(self):
        """11 个工具的 pcal/version.py 都必须与 _core/version.py 同版本。"""
        import re
        bad = []
        for child in sorted(REPO_ROOT.iterdir()):
            p = child / 'pcal' / 'version.py'
            if not p.is_file():
                continue
            text = p.read_text(encoding='utf-8')
            m = re.search(r"APP_VERSION\s*=\s*'([^']+)'", text)
            got = m.group(1) if m else None
            if got != core_version.APP_VERSION:
                bad.append((child.name, got))
        self.assertEqual(bad, [],
                         '这些工具的版本副本与真源 %s 不一致：%r'
                         % (core_version.APP_VERSION, bad))

    def test_no_stale_version_in_readme_top(self):
        """README 顶部那句版本号不能落后（否则读者以为还是旧版）。"""
        text = _module_source('README.md')
        first_lines = '\n'.join(text.split('\n')[:40])
        self.assertIn('v' + core_version.APP_VERSION, first_lines,
                      'README 顶部没有写着当前版本 v%s'
                      % core_version.APP_VERSION)


class ReleaseScriptRestartHintTests(unittest.TestCase):
    """发版脚本必须在收尾时提醒「旧服务还在跑，重启才会显示新版本」。"""

    def setUp(self):
        self.src = _module_source('make_release.py')
        self.tree = ast.parse(self.src)

    def _func(self, name):
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    def test_has_stale_service_checker(self):
        self.assertIsNotNone(self._func('_stale_service_pids'),
                             'make_release.py 缺 _stale_service_pids()：'
                             '发版后无法发现「还跑着旧版本的服务」')
        self.assertIsNotNone(self._func('_warn_stale_services'),
                             'make_release.py 缺 _warn_stale_services()')

    def test_do_apply_calls_the_warning(self):
        """do_apply 收尾必须真的调用提醒（否则等于没写）。"""
        do_apply = self._func('do_apply')
        self.assertIsNotNone(do_apply)
        called = {n.func.id for n in ast.walk(do_apply)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn('_warn_stale_services', called,
                      'do_apply 没有调用 _warn_stale_services()，'
                      '发完版用户仍会看到旧版本号而不知道为什么')

    def test_warning_tells_how_to_restart(self):
        """提示里要给出可照抄的重启命令，不能只说「请重启」。"""
        warn = self._func('_warn_stale_services')
        consts = [n.value for n in ast.walk(warn)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        joined = '\n'.join(consts)
        self.assertIn('--restart', joined,
                      '提醒里没给出重启命令（python _tools\\launcher.py --restart）')
        self.assertIn('旧', joined, '提醒里应说明是「旧进程」导致版本号不变')

    def test_checker_survives_when_no_service_running(self):
        """没有任何服务在跑时，检查函数必须返回 []，不许抛异常。

        发版可能在没开服务的情况下进行（例如刚 clone 就跑），
        这条路径必须安全。
        """
        spec = importlib.util.spec_from_file_location(
            'make_release_probe', REPO_ROOT / 'make_release.py')
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except SystemExit:                      # 脚本式模块可能直接退出
            self.skipTest('make_release.py 不在可导入状态')
        pids = mod._stale_service_pids()
        self.assertIsInstance(pids, list)
        for p in pids:
            self.assertIsInstance(p, int)


class PortalVersionSourceTests(unittest.TestCase):
    """入口页报版本的方式：必须是「导入即定值」，这正是必须重启的原因。"""

    def test_portal_reads_version_at_import_time(self):
        src = _module_source('物化实验报告工具/portal.py')
        self.assertIn('APP_VERSION', src)
        # 确认它来自模块级常量而不是每次请求重新读文件
        tree = ast.parse(src)
        assigns = [n for n in tree.body
                   if isinstance(n, ast.Assign)
                   and any(getattr(t, 'id', None) == 'APP_VERSION' for t in n.targets)]
        self.assertTrue(assigns,
                        'portal.py 的 APP_VERSION 不是模块级赋值，'
                        '本测试的前提（导入即定值）不成立，需要重新评估重启必要性')


if __name__ == '__main__':
    unittest.main()