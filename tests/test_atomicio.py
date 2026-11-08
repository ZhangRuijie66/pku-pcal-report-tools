# -*- coding: utf-8 -*-
"""_core/atomicio.py 的回归测试：原子写、坏文件留证、读盘语义。

背景（2026-11-07 审计的 5 条 P0 全指向这里）：
原来的写法是

    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh)

`open(..., 'w')` **先把文件截断成 0 字节**，然后才轮到 `json.dump`。只要序列化
中途抛异常（数据里混进 numpy 标量、set、自定义对象，或磁盘写满），用户的实验
读数就留在半截状态。审计时实测：180 B 的文件崩成 176 B，内容全丢，而且全项目
**没有任何备份**。

所以这里的断言核心只有一句：**写失败时，原文件必须逐字节不变。**
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from support import REPO_ROOT, load_module

TOOL = '表面吸附工具'


class AtomicWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.io = load_module(TOOL, 'atomicio')
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def path(self, name='data.json'):
        return os.path.join(self.tmp.name, name)

    def test_write_then_read_roundtrip(self):
        p = self.path('ok.json')
        payload = {'bubble': [{'h_l': [1.23, 1.24]}], 'note': '真实读数'}
        self.io.atomic_write_json(p, payload)
        with open(p, encoding='utf-8') as fh:
            self.assertEqual(json.load(fh), payload)

    def test_failed_serialization_leaves_original_untouched(self):
        """★ 核心断言：序列化失败时原文件逐字节不变。

        这是旧写法真正丢数据的场景——旧代码 `open(w)` 已经把文件清空，
        异常才抛出来，内容已经没了。
        """
        p = self.path('keep.json')
        original = {'k': '用户的真实实验读数' * 20}
        self.io.atomic_write_json(p, original)
        with open(p, 'rb') as fh:
            before = fh.read()

        bad = {'k': 'x', 'oops': {1, 2, 3}}      # set 不能 JSON 序列化
        with self.assertRaises(TypeError):
            self.io.atomic_write_json(p, bad)

        with open(p, 'rb') as fh:
            after = fh.read()
        self.assertEqual(before, after, '写失败后原文件必须逐字节不变')

    def test_failed_write_leaves_no_temp_file(self):
        """失败后不能留下 `.~write-*.tmp` 垃圾。"""
        p = self.path('tmpclean.json')
        self.io.atomic_write_json(p, {'a': 1})
        with self.assertRaises(TypeError):
            self.io.atomic_write_json(p, {'oops': {1, 2}})
        leftovers = [n for n in os.listdir(self.tmp.name)
                     if n.startswith('.~write-')]
        self.assertEqual(leftovers, [], '失败后残留临时文件：%r' % leftovers)

    def test_nan_does_not_corrupt_json(self):
        """NaN 落盘后仍是 Python 能读的，但浏览器 JSON.parse 会失败——
        记录当前行为，提醒调用方别把 NaN 塞进用户数据。"""
        p = self.path('nan.json')
        self.io.atomic_write_json(p, {'x': float('nan')})
        with open(p, encoding='utf-8') as fh:
            raw = fh.read()
        self.assertIn('NaN', raw)


class QuarantineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.io = load_module(TOOL, 'atomicio')
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_quarantine_renames_and_preserves_bytes(self):
        p = os.path.join(self.tmp.name, '电导率数据.json')
        broken = b'{"temp_c": 21.3, "kcl_la'
        with open(p, 'wb') as fh:
            fh.write(broken)

        moved = self.io.quarantine(p)

        self.assertIsNotNone(moved)
        self.assertFalse(os.path.exists(p), '坏文件应被移走')
        self.assertTrue(os.path.exists(moved))
        self.assertIn('.corrupt-', os.path.basename(moved))
        with open(moved, 'rb') as fh:
            self.assertEqual(fh.read(), broken, '坏文件必须原样保留，能捞回来')

    def test_quarantine_missing_file_returns_none(self):
        self.assertIsNone(
            self.io.quarantine(os.path.join(self.tmp.name, 'nope.json')))


class ReadJsonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.io = load_module(TOOL, 'atomicio')
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_missing_returns_default(self):
        self.assertEqual(
            self.io.read_json(os.path.join(self.tmp.name, 'none.json'), {'d': 1}),
            {'d': 1})

    def test_corrupt_raises_instead_of_silently_defaulting(self):
        """★ 核心断言：坏文件必须报错，不能被当成 default 静默覆盖。

        旧代码 `except (OSError, ValueError): pass` 正是「打开页面 → 真实读数
        消失」那条 P0 的入口。
        """
        p = os.path.join(self.tmp.name, 'broken.json')
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write('{"temp_c": 21.3, "kc')
        with self.assertRaises(self.io.CorruptFileError):
            self.io.read_json(p, {'silently': 'default'})

    def test_valid_reads_back(self):
        p = os.path.join(self.tmp.name, 'good.json')
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump({'a': [1, 2]}, fh)
        self.assertEqual(self.io.read_json(p, None), {'a': [1, 2]})


class CoreSyncTests(unittest.TestCase):
    def test_atomicio_is_synced_to_every_tool(self):
        """atomicio 必须在 sync_core 的 FILES 里，并已同步到 11 个工具。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'sync_core', REPO_ROOT / '_core' / 'sync_core.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        names = [name for name, _ in mod.FILES]
        self.assertIn('atomicio.py', names)
        for tool in mod.TOOLS:
            self.assertTrue((REPO_ROOT / tool / 'pcal' / 'atomicio.py').is_file(),
                            '%s 缺 pcal/atomicio.py' % tool)


if __name__ == '__main__':
    unittest.main()
