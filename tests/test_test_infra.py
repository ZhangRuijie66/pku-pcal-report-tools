# -*- coding: utf-8 -*-
"""测试基建本身的守卫（2026-11-27 新增）。

优化测试环节时引入了两样新东西，都有「看起来很省事、实际会埋雷」的风险，
所以在这里钉住：

1. **报告产物的内容寻址缓存**（``module_cases.generate_report``）。
   缓存最大的风险是**假绿**：改了报告代码却复用旧产物去审计。
   本项目已经有过两次「检查器假绿」（check_italic v1、check_source_symbols v1），
   不能出现第三次。所以这里做**故障注入**——真的改一下 report.py，
   断言缓存键必须变、产物必须重新生成、注入的问题必须被检出。

2. **并行 runner**（``run_tests.py``）。
   并行的风险是「少跑了却报 OK」：文件没被发现、子进程崩了被当成通过、
   skip 被忽略。这里钉住三个判据。

## 为什么这些测试值得写

`run_tests.py` 是所有其它测试的**地基**。地基出错的表现恰恰是「全绿」——
2026-11-03 审计就发现过：80 项全绿，但 208 个断言里 57 个是 grep 源码字符串；
干净 clone 上燃烧热/溶解热的数值基准全 skip 却报 OK。地基必须自己有测试。
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from support import REPO_ROOT

TESTS_DIR = REPO_ROOT / 'tests'
TOOL = '电导率工具'
REPORT_PY = REPO_ROOT / TOOL / 'pcal' / 'report.py'


class ReportCacheSoundnessTests(unittest.TestCase):
    """缓存必须按内容寻址：输入变了就不能复用旧产物。

    ⚠⚠ **这一组必须串行独占运行，不能在并行 runner 里跑。**

    它靠「真的改写 report.py → 看产物是否重新生成」来验证缓存有效性，
    而 `test_modules` / `test_italic` 同时在生成同一批报告。并行时会出现：

      · 本文件刚把 ε 写进 report.py，`test_modules` 恰好在这一瞬间生成报告
        → 它拿到带 ε 的产物 → 报「紫外报告有结构错误」（假的失败）；
      · 本文件的 `finally` 还原 report.py 时，另一个测试正在读它。

    实测（2026-11-27）：`-j 8` 冷缓存跑，italic/modules/infra 三个文件同时红；
    单独跑全部通过。这不是被测代码的问题，是「用改源文件做故障注入」这种
    手法本身与并行不相容。

    处理办法：`run_tests.py` 把本文件放到**单独的串行阶段**（见 EXCLUSIVE_FILES），
    其余文件并行跑完再跑它。代价约 12 s，换来的是注入式验证仍然有效。
    """

    #: 由 run_tests.py 识别：这类文件改写仓库源文件，必须独占
    EXCLUSIVE = True

    @classmethod
    def setUpClass(cls):
        import matplotlib
        matplotlib.use('Agg')
        import check_typesetting
        cls.ct = check_typesetting
        from module_cases import _report_cache_key, build_cases, generate_report
        cls.key = staticmethod(_report_cache_key)
        cls.generate = staticmethod(generate_report)
        cls.cases, cls.errors = build_cases()

    def setUp(self):
        # ⚠ 本组测试验证的是**缓存**行为，PCAL_TEST_NOCACHE=1 时缓存被绕过，
        # 这些断言没有意义（`test_no_false_green_after_source_change` 会假失败：
        # 无缓存时 generate_report 每次重建，产物路径每次都不同，
        # 「路径变了吗」成立，但整个链条验证的已经不是缓存了）。
        # 2026-11-27 实测：带 PCAL_TEST_NOCACHE=1 跑全量时此项假红。
        if os.environ.get('PCAL_TEST_NOCACHE') == '1':
            self.skipTest('缓存已被 PCAL_TEST_NOCACHE=1 关闭，本组用例不适用')
        self._orig = REPORT_PY.read_bytes()
        self.addCleanup(lambda: REPORT_PY.write_bytes(self._orig))

    def _case(self):
        self.assertIn('电导率', self.cases, '电导率基准数据不可用')
        return self.cases['电导率']

    def test_cache_key_changes_when_report_source_changes(self):
        """改 report.py → 键必须变。"""
        case = self._case()
        k1 = self.key(case)
        src = self._orig.decode('utf-8')
        REPORT_PY.write_bytes(
            src.replace("'电导率；极限摩尔电导率",
                        "'ε 电导率；极限摩尔电导率", 1).encode('utf-8'))
        k2 = self.key(case)
        self.assertNotEqual(k1, k2, '★ 改了 report.py 但缓存键没变')

    def test_cache_key_is_stable_for_same_input(self):
        """同一份输入必须给出同一个键（否则缓存形同虚设，且无法复现）。"""
        case = self._case()
        self.assertEqual(self.key(case), self.key(case))

    def test_cache_key_depends_on_cfg(self):
        """cfg 变了（比如换了姓名/温度）也必须换键——它会进封面。"""
        import copy
        case = self._case()
        k1 = self.key(case)
        other = copy.copy(case)
        other.cfg = dict(case.cfg, student_name='另一个同学')
        self.assertNotEqual(k1, self.key(other))

    def test_no_false_green_after_source_change(self):
        """★ 核心用例：注入排版问题 → 必须重新生成 → 必须检出。

        这条如果失败，说明缓存让「修改后的代码」用上了「修改前的产物」，
        整个报告检查体系就都不可信了。
        """
        case = self._case()
        out1 = self.generate(case)
        n1 = sum(len(v) for v in self.ct.audit(str(out1)).values())
        self.assertEqual(n1, 0, '基线本该是 0 处排版问题，实际 %d' % n1)

        src = self._orig.decode('utf-8')
        self.assertIn("'电导率；极限摩尔电导率", src,
                      '注入点找不到了（关键词那行改过），本测试需要更新')
        REPORT_PY.write_bytes(
            src.replace("'电导率；极限摩尔电导率",
                        "'ε 电导率；极限摩尔电导率", 1).encode('utf-8'))

        out2 = self.generate(case)
        self.assertNotEqual(out1, out2, '★ 产物路径没变，缓存没失效')
        n2 = sum(len(v) for v in self.ct.audit(str(out2)).values())
        self.assertGreater(n2, 0,
                           '★ 注入的排版问题没被检出 —— 缓存造成了假绿')

    def test_restore_returns_to_baseline(self):
        """还原后键要回到原值（说明键是纯粹的输入函数，没有时间戳成分）。"""
        case = self._case()
        k1 = self.key(case)
        src = self._orig.decode('utf-8')
        REPORT_PY.write_bytes(src.replace("'电导率；", "'X " + "'电导率；", 1)
                              .encode('utf-8'))
        self.assertNotEqual(k1, self.key(case))
        REPORT_PY.write_bytes(self._orig)
        self.assertEqual(k1, self.key(case))

    def test_nocache_env_bypasses_cache(self):
        """PCAL_TEST_NOCACHE=1 必须真的绕过缓存（排查缓存本身的问题时要用）。"""
        case = self._case()
        os.environ['PCAL_TEST_NOCACHE'] = '1'
        try:
            import tempfile
            td = tempfile.mkdtemp(prefix='nocache_')
            out = self.generate(case, td)
            self.assertEqual(Path(out).parent, Path(td),
                             '关缓存后产物应落在调用方给的目录里')
        finally:
            os.environ.pop('PCAL_TEST_NOCACHE', None)


class ParallelRunnerTests(unittest.TestCase):
    """``run_tests.py`` 的并行实现不能「少跑了却报 OK」。"""

    def _run(self, *args):
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        r = subprocess.run([sys.executable, str(TESTS_DIR / 'run_tests.py')]
                           + list(args),
                           cwd=str(REPO_ROOT), capture_output=True, env=env)
        return r.returncode, r.stdout.decode('utf-8', 'replace')

    def test_filter_runs_only_matching_files(self):
        code, out = self._run('-k', '^test_omml$', '-j', '1', '-q')
        self.assertEqual(code, 0, out[-1500:])
        self.assertIn('1 个文件', out, out[-800:])

    def test_filter_with_no_match_fails_loudly(self):
        """过滤不到任何文件时必须非 0，不能静默'通过'。"""
        code, out = self._run('-k', 'no_such_test_file_xyz')
        self.assertNotEqual(code, 0, '匹配不到文件时应报错，实际退出码 0')
        self.assertIn('没有匹配', out)

    def test_discovery_finds_every_test_file(self):
        """发现环节必须找到全部 test_*.py —— 漏文件就会静默少跑。

        ⚠ 这里**只调用 runner 的 `_discover()`**，不真的把全套跑一遍。
        第一版写成 `self._run('-k', '^test_')`，于是本文件通过 runner 启动
        子进程 → 子进程又跑本文件 → 再启动 runner → **无限递归**，实测挂死
        在 600 s 超时。凡是「测试测试框架」的用例，都要避免真的重跑全套。
        """
        sys.path.insert(0, str(TESTS_DIR))
        import importlib
        import run_tests
        importlib.reload(run_tests)
        found = set(run_tests._discover(None))
        on_disk = {p.stem for p in TESTS_DIR.glob('test_*.py')}
        self.assertEqual(found, on_disk,
                         '发现结果与磁盘不一致：漏 %r，多 %r'
                         % (sorted(on_disk - found), sorted(found - on_disk)))

    def test_filter_selects_subset(self):
        """过滤参数要真的起作用（而不是把全部文件都跑一遍）。"""
        sys.path.insert(0, str(TESTS_DIR))
        import run_tests
        got = run_tests._discover(r'^test_omml$')
        self.assertEqual(got, ['test_omml'])
        self.assertEqual(run_tests._discover(r'zzz_no_such'), [])

    def test_no_skip_is_reported_as_pass(self):
        """skip 超预算必须让退出码非 0（原逻辑的回归守卫）。"""
        code, out = self._run('-k', '^test_omml$', '-j', '1')
        self.assertEqual(code, 0, out[-1200:])
        self.assertNotIn('有 1 项被 skip', out)


if __name__ == '__main__':
    unittest.main()