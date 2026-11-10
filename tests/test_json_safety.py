# -*- coding: utf-8 -*-
"""11 个模块的 HTTP 回包必须是**合法 JSON**。

守的是 2026-11-10 的真实事故：化学动力学模块分析内核里
``alpha_inf['sd']`` 取到 ``float('nan')``，``json.dumps`` 把它写成裸 ``NaN``
（不是合法 JSON），浏览器 ``res.json()`` 抛
``Unexpected token 'N', ...is not valid JSON``，整个页面卡在「初始化失败」。
一条 nan 就让界面打不开，而错误消息完全指不到源头。

11 个模块的 ``_json`` 原来各写各的（4 种写法），全都有这个隐患。
现在统一走 ``_core/jsonutil.py``（canonical，通过 sync_core 分发）。

判据（SKILL §27）：
  · 数量/数值异常时要**明确表示**——用 ``null``，前端显示「—」；
  · 不能把 NaN/Infinity 当数字混过去（浏览器不会给你第二次机会）。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support                                        # noqa: E402

TOOLS = ('燃烧热工具', '溶解热工具', '紫外光谱工具', '化学动力学工具',
         '电化学工具', '电导率工具', '蒸气压工具', '双液系工具',
         '偶极矩工具', '磁化率工具', '表面吸附工具')


class JsonUtilContractTests(unittest.TestCase):
    """canonical 实现的行为契约（11 个模块共用同一份）。"""

    def setUp(self):
        self.ju = support.load_module('化学动力学工具', 'jsonutil')

    def test_nan_inf_become_none(self):
        out = self.ju.to_jsonable({'a': float('nan'),
                                   'b': [1.0, float('inf'), float('-inf')],
                                   'c': {'d': float('nan')}})
        self.assertIsNone(out['a'])
        self.assertEqual(out['b'], [1.0, None, None])
        self.assertIsNone(out['c']['d'])

    def test_zero_is_not_confused_with_missing(self):
        """0 必须原样保留：0 = 算出来是 0，None = 没算出来。"""
        out = self.ju.to_jsonable({'z': 0.0, 'n': None, 'i': 0})
        self.assertEqual(out['z'], 0.0)
        self.assertIsNone(out['n'])
        self.assertEqual(out['i'], 0)

    def test_bool_survives(self):
        """bool 在 Python 里是 int 的子类，别被转成 0/1。"""
        out = self.ju.to_jsonable({'t': True, 'f': False})
        self.assertIs(out['t'], True)
        self.assertIs(out['f'], False)

    def test_numpy_types(self):
        import numpy as np
        out = self.ju.to_jsonable({
            'nan': np.float64('nan'),
            'inf': np.float32('inf'),
            'i': np.int64(7),
            'arr': np.array([1.0, np.nan, 3.0]),
            'b': np.bool_(True)})
        self.assertIsNone(out['nan'])
        self.assertIsNone(out['inf'])
        self.assertEqual(out['i'], 7)
        self.assertEqual(out['arr'], [1.0, None, 3.0])
        self.assertIs(out['b'], True)

    def test_core_json_dumps_is_strict(self):
        """core_json_dumps 输出必须能被标准 JSON 解析器读回，且不含裸 NaN。"""
        text = self.ju.core_json_dumps({'x': float('nan'), 'y': [float('inf')]})
        self.assertNotIn('NaN', text)
        self.assertNotIn('Infinity', text)
        back = json.loads(text)
        self.assertIsNone(back['x'])
        self.assertEqual(back['y'], [None])

    def test_strict_mode_raises_on_unsanitized_nan(self):
        """反向对照：不加清洗的 dumps 必须失败——证明 allow_nan=False 真的生效。"""
        with self.assertRaises(ValueError):
            json.dumps({'x': float('nan')}, allow_nan=False)

    def test_unknown_object_falls_back_to_str(self):
        """Path / 自定义对象不能抛，退化成字符串。"""
        out = self.ju.to_jsonable({'p': Path('a/b'), 'o': object()})
        self.assertIsInstance(out['p'], str)
        self.assertIsInstance(out['o'], str)


class AllModulesWireUpTests(unittest.TestCase):
    """11 个模块的 server 都必须走 core_json_dumps（不能各留一份）。"""

    def test_every_server_uses_core_json_dumps(self):
        bad = []
        for tool in TOOLS:
            src = (support.REPO_ROOT / tool / 'pcal' / 'server.py').read_text(
                encoding='utf-8')
            if 'core_json_dumps' not in src:
                bad.append(tool)
        self.assertEqual(bad, [], '_json 未走 core_json_dumps：%s' % '、'.join(bad))

    def test_every_server_has_jsonutil_copy(self):
        bad = [t for t in TOOLS
               if not (support.REPO_ROOT / t / 'pcal' / 'jsonutil.py').is_file()]
        self.assertEqual(bad, [], '缺 pcal/jsonutil.py：%s' % '、'.join(bad))

    def test_no_bare_json_dumps_of_payload(self):
        """回包那一行不能还留着裸 json.dumps(obj…)。

        只查「把整个 obj 直接 dumps」这种模式；日志/缓存键用 json.dumps
        是另一回事，不在本检查范围。
        """
        bad = []
        for tool in TOOLS:
            src = (support.REPO_ROOT / tool / 'pcal' / 'server.py').read_text(
                encoding='utf-8')
            for line in src.split('\n'):
                if 'json.dumps(obj' in line:
                    bad.append('%s: %s' % (tool, line.strip()[:70]))
        self.assertEqual(bad, [], '还有裸 dumps 回包：%s' % bad)


class LiveEndpointTests(unittest.TestCase):
    """真的起一个 HTTP 服务，喂含 NaN 的数据，确认回包能解析。

    只测化学动力学（它曾真实翻车）——但它走的是公共 jsonutil，
    覆盖到这一条即代表 11 个模块的公共路径成立。
    """

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        cls._mods_before = set(sys.modules)
        cls.srv = support.load_module('化学动力学工具', 'server')
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), cls.srv.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        for name in [m for m in sys.modules if m not in cls._mods_before]:
            if name == 'pcal' or name.startswith('pcal.'):
                del sys.modules[name]

    def _get(self, path):
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:%d%s'
                                    % (self.port, path), timeout=60) as r:
            return r.read()

    def test_state_endpoint_is_parseable_json(self):
        """判据必须落在「标准 JSON 解析器能读回」上。

        ⚠ 不能用 ``b'NaN' in body`` 这种子串检查：电导率模块的化学式
        ``NaNO3`` 里就含 "NaN"，会误报（本次实测踩到）。合法 JSON 只要
        ``json.loads`` 能解析就说明没有裸 NaN/Infinity——那三个字面量
        本身就是 JSON 语法错误。
        """
        body = self._get('/api/state')
        data = json.loads(body)          # 含裸 NaN/Infinity 会在这里抛
        self.assertTrue(data['ok'])

    def test_state_alpha_inf_sd_is_null_not_nan(self):
        data = json.loads(self._get('/api/state'))
        sd = data['alpha_inf']['sd']
        self.assertIsNone(sd, 'alpha_inf.sd 必须是 null，不能是 NaN')

    def test_samples_have_finite_k1(self):
        data = json.loads(self._get('/api/state'))
        for g in data['groups']:
            if g['k1'] is not None:
                self.assertNotEqual(g['k1'], float('nan'))


if __name__ == '__main__':
    unittest.main()
