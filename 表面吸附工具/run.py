# -*- coding: utf-8 -*-
"""溶液表面吸附实验报告一键生成 —— 启动入口。

    python run.py                 启动本地网页界面
    python run.py --test          无界面自检：用示例数据生成一份报告
    python run.py --port 8772     指定端口
    python run.py --no-browser    不自动打开浏览器
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def self_test():
    from pcal import adsorption
    from pcal.analysis import default_config
    from pcal import report as rpt
    from pcal.server import TEMPLATE, OUT_DIR

    cfg = default_config()
    cfg.update(student_name='张瑞杰', student_id='2400011877',
               group='3', group_no='8', date='2026/11/01',
               room_temp=21.0, pressure=101.5,
               zero_correction=False, conc_axis='lg')
    an = adsorption.analyze(adsorption.sample_data(), cfg)
    b, p = an['bubble'], an['plate']
    print('示例数据自检（2025 年报告口径，不扣零点）')
    print('  最大气泡压力法：T=%.2f ℃  Γ∞=%.4e mol/m2  q=%.4f nm2  R2=%.5f'
          % (b['temperature'], b['gamma_inf'], b['q'], b['fit']['r2']))
    print('  吊片法        ：T=%.1f ℃  Γ∞=%.4e mol/m2  q=%.4f nm2  R2=%.5f'
          % (p['temperature'], p['gamma_inf'], p['q'], p['fit']['r2']))
    if an['comparison']:
        print('  两法 Γ∞ 相对差：%.1f%%'
              % an['comparison']['rel_gamma'])
    for w in an['warnings']:
        print('  ⚠', w)

    out_dir = os.path.join(OUT_DIR, '自检报告（表面吸附）')
    out = os.path.join(out_dir, '自检报告.docx')
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
