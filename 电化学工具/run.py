# -*- coding: utf-8 -*-
"""电化学（循环伏安法）实验报告一键生成 —— 启动入口。

    python run.py                 启动本地网页界面
    python run.py --test          无界面自检：读默认数据目录并生成一份报告
    python run.py --port 8801     指定端口
    python run.py --no-browser    不自动打开浏览器
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def self_test():
    from pcal.analysis import Analysis, default_config
    from pcal import report as rpt
    from pcal.server import TEMPLATE, OUT_DIR

    data_dir = default_config()['data_dir']
    print('数据目录：', data_dir)
    cfg = default_config()
    cfg.update(student_name='张瑞杰', student_id='2400011877',
               group='3', group_no='8',
               date='2026/10/23', room_temp=22.0, pressure=101.3)
    an = Analysis(cfg).run()
    if an.warnings:
        for w in an.warnings:
            print('  ⚠', w)
    print('表1（含氧物种脱附峰，CHI Segment 5 读数）：')
    for r in an.table1:
        print('  v=%.1f V/s  Ep=%.3f V  ip=%.4e A' % (r['v'], r['Ep'], r['ip']))
    esa = an.esa
    print('ESA: A=%.4e A·V  Q=%.4e C  S=%.3f mm² (基线 %.3f μA)'
          % (esa['A'], esa['Q'], esa['area_mm2'], esa['baseline'] / 1e-6))
    print('ORR: 还原支 %.3f V / 氧化支 %.3f V' % (an.orr['onset_red'],
                                                 an.orr['onset_ox']))
    print('MOR: %.3f V' % an.mor['onset'])
    d = an.dmfc
    if d:
        print('DMFC: 交点 E=%.3f V (I=%.3e A)  P_max=%.3e W @ E_cell=%.3f V'
              % (d['E_intersect'], d['I_intersect'], d['P_max'], d['E_at_Pmax']))

    out_dir = os.path.join(OUT_DIR, '自检报告（电化学）')
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
