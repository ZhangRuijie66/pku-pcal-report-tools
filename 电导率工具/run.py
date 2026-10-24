# -*- coding: utf-8 -*-
"""电导率实验报告一键生成 —— 启动入口。

    python run.py                 启动本地网页界面
    python run.py --test          无界面自检：读默认数据并生成一份报告
    python run.py --port 8751     指定端口
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

    cfg = default_config()
    cfg.update(student_name='张瑞杰', student_id='2400011877',
               group='3', group_no='8',
               date='2026/10/16', room_temp=21.3, pressure=102.2)
    an = Analysis(cfg).run()
    print('数据文件：', an.data_path)
    if an.warnings:
        for w in an.warnings:
            print('  ⚠', w)
    for key in ('NaNO3', 'NaAc', 'HNO3'):
        f = an.fits[key]
        print('%s: Λm∞=(%.5f ± %.5f) S·m²·mol⁻¹  r=%.2f'
              % (key, f['lam_inf'], f['sigma_inf'], f['r']))
    print('Λm∞(HAc) = (%.5f ± %.5f) S·m²·mol⁻¹'
          % (an.esa['lam_inf'], an.esa['sigma']))
    km, kf = an.kmean, an.kfit
    print('K° 求平均法  = (%.4f ± %.4f)×10⁻⁵' % (km['mean'] * 1e5, km['sigma'] * 1e5))
    print('K° 拟合直线法 = (%.4f ± %.4f)×10⁻⁵  r=%.5f'
          % (kf['K'] * 1e5, kf['sigma_K'] * 1e5, kf['r']))
    print('Ka 文献 = %.4g' % __import__('pcal.conduct', fromlist=['x']).KA_HAC)

    out_dir = os.path.join(OUT_DIR, '自检报告（电导率）')
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
