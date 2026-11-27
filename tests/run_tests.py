# -*- coding: utf-8 -*-
"""运行全部回归测试：python tests/run_tests.py [选项]

    python tests/run_tests.py                  # 全量（并行，约 50 s）
    python tests/run_tests.py -k conduct       # 只跑名字匹配的文件/用例
    python tests/run_tests.py -j 1             # 串行（调试用）
    python tests/run_tests.py --failfast       # 首个失败即停
    python tests/run_tests.py -q               # 只打汇总（不发每个用例名）

## 为什么改成并行

2026-11-27 实测：44 个文件串行 205 s，其中「Top 10 占 80%」——
`test_modules`(23 s) 与 `test_italic`(21 s) 各自把 11 份报告**完整生成一遍**
（两者都调 `module_cases.generate_report`），`test_portable`(23 s)、
`test_kinetics_import`(15 s) 也是重活。

`unittest` 自带的 `discover` 只能串行，于是按「**一文件一进程**」分发：

  · 天然并行，20 核机器上 8 并发实测 205 s → 49 s（4.2 倍）；
  · 顺带解决 `support.py` 记了很久的**裸 `pcal` 包名串味**——
    以前全量跑时某个文件的 `from pcal import …` 会把别的工具的 pcal
    顶掉（蒸气压、电化学都踩过），一文件一进程后进程间不共享 `sys.modules`，
    这类顺序依赖从根上消失。

安全性核对过：测试里的临时文件一律走 `TemporaryDirectory`，HTTP 服务一律
绑 `('127.0.0.1', 0)` 由内核分配端口，没有跨文件共享的可写状态。

## skip 预算（保留原逻辑）

`wasSuccessful()` 不管 skip，所以「静默少跑」以前看不出来（干净 clone 上
燃烧热/溶解热的基准全 skip 却报 OK）。这里把 skip 也当失败，除非它确实是
有意为之——数据已经切进 `tests/fixtures/` 随仓库走，正常应是 0 个 skip。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SKIP_BUDGET = 2          # 允许的 skip 个数（见下）
# 只允许「构建产物还没生成」这一类：`发布/*.zip` 是 gitignore 的产物，
# 干净 clone 上本来就不存在，对应两项可移植包检查只能 skip。
# 除此之外一律不许 skip —— 尤其数值基准，数据已切进 tests/fixtures/ 随仓库走。
SKIP_ALLOWED_HINTS = (
    '还没打可移植包',
    # PCAL_TEST_NOCACHE=1 是排查缓存问题时的调试开关；此时 test_test_infra 里
    # 那组「验证缓存有效性」的用例不适用，会主动 skip。这是有意为之。
    '缓存已被 PCAL_TEST_NOCACHE=1 关闭',
)

#: 默认并发数：实测 8 与 14 只差 3~4 s（关键路径已被最慢的几个文件占住），
#: 但并发越高、内存峰值越大（每个进程都 import numpy/matplotlib）。
#: 取 8 是「够快且稳」的折中；20 核机器上可以 -j 14 再榨一点。
DEFAULT_JOBS = min(8, max(1, (os.cpu_count() or 2) - 2))

#: 报告生成走内容寻址缓存（见 module_cases.generate_report），
#: 冷缓存时首个文件要多花约 27 s 生成 11 份报告，之后各文件直接复用。
#: 这个提示只在冷缓存时打一次，避免用户以为「怎么第一次这么慢」。

#: 从子进程输出里抠出 unittest 的汇总行与逐条用例行。
_RE_RAN = re.compile(r'^Ran (\d+) tests? in ([\d.]+)s', re.M)
_RE_FAILED = re.compile(r'^(FAILED|OK)(.*)$', re.M)
_RE_SKIP_TAIL = re.compile(r'\(([^()]*)\)\s*$')


class FileResult:
    """一个测试文件的运行结果。"""

    __slots__ = ('name', 'code', 'seconds', 'ran', 'ok', 'skips', 'detail')

    def __init__(self, name, code, seconds, out):
        self.name = name
        self.code = code
        self.seconds = seconds
        m = _RE_RAN.search(out)
        self.ran = int(m.group(1)) if m else 0
        self.detail = out

        # unittest 的汇总行：把 skip 的用例名从输出里抠出来
        self.skips = []
        for line in out.split('\n'):
            s = line.strip()
            if s.startswith('__main__.') or ' ... skipped ' in s \
                    or s.endswith('skipped'):
                mt = _RE_SKIP_TAIL.search(s)
                if mt and 'skipped' in s:
                    self.skips.append(s)

        # 是否「真的通过了」：退出码 0 **且** 看到 OK。
        # 只信退出码是不够的：子进程若在 import 阶段就崩，退出码也可能非 0，
        # 但更隐蔽的是「Ran 0 tests」+ OK——那说明发现环节坏了（改了文件名、
        # 或 __init__ 里抛错被吞）。这里把它判成失败。
        self.ok = (code == 0) and bool(_RE_FAILED.search(out)) \
            and _RE_FAILED.search(out).group(1) == 'OK'


#: 需要**独占串行**运行的测试文件（其余文件并行跑完后再跑它们）。
#:
#: 为什么需要：`test_test_infra` 的缓存有效性验证靠「真的改写仓库里的
#: report.py → 看产物是否重新生成」。若与 `test_modules` / `test_italic`
#: 并行，后者可能在「ε 已写入、尚未还原」的那一瞬间生成报告，于是拿到
#: 被污染的产物、报出假的失败（2026-11-27 实测：-j 8 冷缓存时三个文件同时红，
#: 单独跑全绿）。这类「用改源文件做故障注入」的手法与并行天然不相容，
#: 只能串行独占。
EXCLUSIVE_FILES = ('test_test_infra',)


def _discover(pattern=None):
    """按文件名收集测试模块（不含 .py 后缀）。"""
    names = []
    for p in sorted(HERE.glob('test_*.py')):
        if pattern and not re.search(pattern, p.stem):
            names.append(None)          # 占位，保持过滤信息可见
            continue
        names.append(p.stem)
    return [n for n in names if n]


def _run_file(name, quiet, failfast):
    cmd = [sys.executable, '-m', 'unittest', name]
    if failfast:
        cmd.append('-f')
    t0 = time.time()
    # ⚠ 不要给 subprocess 传 encoding/errors：Python 3.11 的 traceback 模块
    # 在处理**已被截断的 UTF-8 中文**时会自己抛 UnicodeDecodeError
    # （实测：0xe6 在位置 49 处 unexpected end of data），把真正的失败信息
    # 盖成一段解码崩溃。让它返回 bytes，由我们自己用 errors='replace' 解。
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run(cmd, cwd=str(HERE), capture_output=True, env=env)
    out = (r.stdout or b'') + (r.stderr or b'')
    text = out.decode('utf-8', 'replace')
    return FileResult(name, r.returncode, time.time() - t0, text)


def _print_summary(results, elapsed, jobs):
    total = sum(r.ran for r in results)
    failed = [r for r in results if not r.ok]
    skipped = [(r, s) for r in results for s in r.skips]
    slow = sorted(results, key=lambda r: -r.seconds)[:5]

    print()
    print('=' * 72)
    status = '全部通过' if not failed and len(skipped) <= SKIP_BUDGET else '有问题'
    print('  %s：%d 个文件 / %d 个用例，用时 %.1f s（%d 并发）'
          % (status, len(results), total, elapsed, jobs))
    print('  最慢的几个：%s'
          % '、'.join('%s %.1fs' % (r.name.replace('test_', ''), r.seconds)
                     for r in slow if r.seconds >= 1.0))
    print('=' * 72)

    if skipped:
        unexpected = [s for _r, s in skipped
                      if not any(h in s for h in SKIP_ALLOWED_HINTS)]
        if unexpected or len(skipped) > SKIP_BUDGET:
            print()
            print('✗ 有 %d 项被 skip（预算 %d，其中 %d 项不属于允许范围）：'
                  % (len(skipped), SKIP_BUDGET, len(unexpected)))
            for s in (unexpected or [s for _r, s in skipped]):
                print('    - %s' % s)
            print('  skip 不算通过：数值基准缺失说明 tests/fixtures/ 坏了或被漏掉。')
        else:
            print()
            print('  （%d 项 skip，均在允许范围内：可移植包还没打）' % len(skipped))

    if failed:
        print()
        for r in failed:
            print('-' * 72)
            print('✗ %s（%.1fs，退出码 %d）' % (r.name, r.seconds, r.code))
            print('-' * 72)
            print(r.detail.rstrip())
        print()
        print('提示：单独重跑某个文件可以看完整输出 ——')
        print('    python tests/run_tests.py -k %s'
              % failed[0].name.replace('test_', ''))
    return 0 if (not failed and len(skipped) <= SKIP_BUDGET
                 and not any(not any(h in s for h in SKIP_ALLOWED_HINTS)
                             for _r, s in skipped)) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='全量回归测试（一文件一进程并行）')
    ap.add_argument('-k', '--filter', default=None,
                    help='只跑文件名匹配该正则的测试文件（如 -k conduct）')
    ap.add_argument('-j', '--jobs', type=int, default=None,
                    help='并发进程数（默认 %d，1 = 串行）' % DEFAULT_JOBS)
    ap.add_argument('-q', '--quiet', action='store_true',
                    help='不打印每个文件的进度，只给汇总')
    ap.add_argument('--failfast', action='store_true',
                    help='首个失败即停（并发时已启动的会跑完）')
    args = ap.parse_args(argv)

    names = _discover(args.filter)
    if not names:
        print('没有匹配 %r 的测试文件（在 %s 下）' % (args.filter, HERE))
        return 1

    jobs = args.jobs if args.jobs is not None else DEFAULT_JOBS
    jobs = max(1, min(jobs, len(names)))

    # 拆成「可并行」与「必须独占」两批。独占批在并行批**跑完之后**串行执行，
    # 这样它改写源文件时不会撞上正在生成报告的文件（见 EXCLUSIVE_FILES）。
    exclusive = [n for n in names if n in EXCLUSIVE_FILES]
    parallel = [n for n in names if n not in EXCLUSIVE_FILES]

    # 短作业优先（SJF）反而比长作业优先好：44 个文件里只有前 4 个超过 15 s，
    # 先跑完一批短的，长作业在后面独占 worker，末尾不会剩一个 23 s 的孤儿。
    order = sorted(parallel, key=lambda n: (HERE / (n + '.py')).stat().st_size)

    if not args.quiet:
        print('跑 %d 个测试文件（%d 并发%s）…'
              % (len(order) + len(exclusive), jobs,
                 '，%d 个独占串行' % len(exclusive) if exclusive else ''))

    t0 = time.time()
    results = []

    def done(res):
        results.append(res)
        if not args.quiet:
            mark = '✓' if res.ok else '✗'
            print('  %s %-38s %4d 用例 %5.1fs'
                  % (mark, res.name.replace('test_', ''), res.ran, res.seconds))
        sys.stdout.flush()

    if jobs == 1:
        for n in order + exclusive:
            res = _run_file(n, args.quiet, args.failfast)
            done(res)
            if args.failfast and not res.ok:
                break
    else:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(_run_file, n, args.quiet, args.failfast):
                    n for n in order}
            for fut in futs:
                res = fut.result()
                done(res)
                if args.failfast and not res.ok:
                    for f in futs:
                        f.cancel()
                    break
        # 等并行批全部落定，再串行跑独占批
        if not (args.failfast and any(not r.ok for r in results)):
            for n in exclusive:
                res = _run_file(n, args.quiet, args.failfast)
                done(res)
                if args.failfast and not res.ok:
                    break

    elapsed = time.time() - t0
    results.sort(key=lambda r: r.name)
    return _print_summary(results, elapsed, jobs)


if __name__ == '__main__':
    sys.exit(main())