# -*- coding: utf-8 -*-
"""紫外光谱实验报告一键生成 —— 启动入口。

    python run.py                 启动本地网页界面
    python run.py --test          无界面自检：读默认数据目录并生成一份报告
    python run.py --port 8792     指定端口
    python run.py --no-browser    不自动打开浏览器
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DATA_DIR = r'D:\北大\课程\26秋大三上\物理化学实验\3 紫外光谱搭建\数据'


def self_test():
    from pcal.analysis import Analysis, default_config
    from pcal import report as rpt
    from pcal.server import TEMPLATE, OUT_DIR

    print('数据目录：', DATA_DIR)
    cfg = default_config()
    cfg.update(student_name='张瑞杰', student_id='2400011877',
               group='3', group_no='8',
               date='2026/10/14 & 10/21',
               room_temp_1=22.0, room_temp_2=19.1,
               pressure_1=101.5, pressure_2=101.8,
               data_dir=DATA_DIR)
    an = Analysis(cfg).run()
    if an.warnings:
        for w in an.warnings:
            print('  ⚠', w)
    print('标定：')
    for key, c in an.cals.items():
        print('  %-9s a=%.7f±%.7f  b=%.3f±%.3f  R2=%.6f  %d~%d nm'
              % (key, c['a'], c['sigma_a'], c['b'], c['sigma_b'], c['r2'],
                 round(c['lam_lo']), round(c['lam_hi'])))
    print('分子：')
    for r in an.molecule_table:
        print('  %-3s c=%5.1f  lmax=%7.2f nm  A=%.4f  eps=%.3f e5'
              % (r['code'], r['conc'], r['lam'], r['A'], r['eps'] / 1e5))
    if an.beer and an.beer.get('fit'):
        f = an.beer['fit']
        print('Beer: k=%.5f b=%.4f R2=%.5f eps=%.4f e5'
              % (f['k'], f['b'], f['r2'], f['eps'] / 1e5))

    out_dir = os.path.join(OUT_DIR, '自检报告（紫外光谱）')
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
