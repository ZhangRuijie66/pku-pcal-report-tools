# -*- coding: utf-8 -*-
"""磁化率的测定实验报告一键生成 —— 启动入口。

    python run.py                 启动本地网页界面
    python run.py --test          无界面自检：用示例数据生成一份报告
    python run.py --port 8782     指定端口
    python run.py --no-browser    不自动打开浏览器

⚠ `--test` 必须走这里的 `self_test()`，不要再让它落进 `pcal.server.main()`：
那是「起服务」的分支，`--test` 传进去会被忽略、转而调用 `_export()`，
于是自检报告写到 `学号-姓名-磁化率\`（封面空时是 `未署名-未署名-磁化率\`），
和其它 10 个模块的 `自检报告（磁化率）\` 不一致，也会在输出目录里留下垃圾。
"""
from __future__ import annotations

import os
import sys


# GBK 控制台兜底：自检会打印 ⚠/·/Δ/α 这类字符，cp936 编不出来会抛
# UnicodeEncodeError 把整个 --test 打断（只影响打印，不该中止计算）。
def _safe_stdout():
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, 'encoding', '') or '').lower()
        if stream is None or 'utf' in enc:
            continue
        try:
            stream.reconfigure(errors='replace')
        except (AttributeError, ValueError, OSError):
            pass


_safe_stdout()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def self_test():
    from pcal import magnetic
    from pcal.analysis import run_analysis
    from pcal import report as rpt
    # 注意：磁化率的 default_config 在 server.py 里（其余模块多在 analysis.py）
    from pcal.server import TEMPLATE, OUT_DIR, default_config

    cfg = default_config()
    data = magnetic.sample_data()
    an = run_analysis(data)

    print('示例数据自检（莫尔盐标定口径）')
    print('  室温 %.1f ℃（%.2f K）' % (an['temperature_C'], an['temperature_K']))
    print('  χ_莫 = %.4e m³·kg⁻¹' % an['chi_std'])
    for name, s in an['samples'].items():
        if s.get('chi_m') is None:
            continue
        mu = s.get('mu')
        n = s.get('n')
        if mu is None:
            # 反磁性物质没有永久磁矩：μ、n 是 None，不能格式化
            print('  %-8s χ_m=%.3e  （反磁性，无永久磁矩）' % (name, s['chi_m']))
        else:
            print('  %-8s χ_m=%.3e  μ=%.3f μB  n=%.2f'
                  % (name, s['chi_m'], mu, n))

    out_dir = os.path.join(OUT_DIR, '自检报告（磁化率）')
    out = os.path.join(out_dir, '自检报告.docx')
    os.makedirs(out_dir, exist_ok=True)
    rpt.build_report(an, cfg, out, os.path.join(out_dir, 'figures'),
                     TEMPLATE, progress=lambda m: print('  ·', m))
    print('已生成：', out, os.path.getsize(out), 'bytes')


def main():
    if '--test' in sys.argv:
        self_test()
        return
    from pcal.server import main as serve
    serve()


if __name__ == '__main__':
    main()
