# -*- coding: utf-8 -*-
"""运行全部回归测试：python tests/run_tests.py

skip 预算：`wasSuccessful()` 不管 skip，所以「静默少跑」以前看不出来
（干净 clone 上燃烧热/溶解热的基准全 skip 却报 OK）。这里把 skip 也当失败，
除非它确实是有意为之——数据已经切进 tests/fixtures/ 随仓库走，正常情况下
应该是 0 个 skip。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SKIP_BUDGET = 2          # 允许的 skip 个数（见下）
# 只允许「构建产物还没生成」这一类：`发布/*.zip` 是 gitignore 的产物，
# 干净 clone 上本来就不存在，对应两项可移植包检查只能 skip。
# 除此之外一律不许 skip —— 尤其数值基准，数据已切进 tests/fixtures/ 随仓库走。
SKIP_ALLOWED_HINTS = ('还没打可移植包',)


def main():
    suite = unittest.TestLoader().discover(
        str(HERE), pattern='test_*.py', top_level_dir=str(HERE))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    skipped = list(result.skipped or [])
    ok = result.wasSuccessful()
    unexpected = [s for s in skipped
                  if not any(h in str(s[1]) for h in SKIP_ALLOWED_HINTS)]
    if unexpected or len(skipped) > SKIP_BUDGET:
        print()
        print('✗ 有 %d 项被 skip（预算 %d，其中 %d 项不属于允许范围）。'
              % (len(skipped), SKIP_BUDGET, len(unexpected)))
        for case, reason in (unexpected or skipped):
            print('    - %s：%s' % (case, reason))
        print('  skip 不算通过：数值基准缺失说明 tests/fixtures/ 坏了或被漏掉。')
        ok = False
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
