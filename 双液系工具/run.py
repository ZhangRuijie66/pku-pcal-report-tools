# -*- coding: utf-8 -*-
"""双液体系沸点-成分图实验报告一键生成 —— 启动入口。

    python run.py                 启动本地网页界面
    python run.py --test          无界面自检：用示例数据生成一份报告
    python run.py --port 8822     指定端口
    python run.py --no-browser    不自动打开浏览器
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def self_test():
    from pcal import phase
    from pcal.analysis import default_config
    from pcal import report as rpt
    from pcal.server import TEMPLATE, OUT_DIR

    cfg = default_config()
    cfg.update(student_name='张瑞杰', student_id='2400011877',
               group='3', group_no='8', date='2026/10/28',
               room_temp=20.0, pressure=101.6)

    data = phase.sample_data()
    for mode, expect in (('ratio', '参照报告口径'),
                         ('frac', '讲义字面口径（质量分数）')):
        cfg2 = dict(cfg, composition_mode=mode)
        an = phase.analyze(data, cfg2)
        fit = an['curve']['fit']
        azeo = an['azeotrope']
        print('示例数据自检（%s）' % expect)
        print('  工作曲线：n = (%s±%s)x² + (%s±%s)x + (%s±%s)，R2=%.5f'
              % (val_like(fit['A'], fit['se_A']), val_like(fit['se_A']),
                 val_like(fit['B'], fit['se_B']), val_like(fit['se_B']),
                 val_like(fit['C'], fit['se_C']), val_like(fit['se_C']),
                 fit['r2']))
        outliers = ', '.join('%d号点 r=%.2f' % (o['index'], o['r'])
                             for o in an['curve']['outliers']) or '无'
        print('  离群点（|r|>2）：%s；剔除：%s'
              % (outliers, an['curve']['removed'] or '无'))
        if azeo.get('ok'):
            print('  恒沸点：T=%.2f K  x=%.4f ± %.4f  文献 x=%.4f  偏差=%.1f%%'
                  % (azeo['T_K'], azeo['w'], azeo['sigma_w'],
                     an['lit_x'] or 0, (an['deviation'] or 0) * 100))
        for w in an['warnings']:
            print('  ⚠', w)

    cfg = dict(cfg, composition_mode='ratio')
    an = phase.analyze(data, cfg)
    out_dir = os.path.join(OUT_DIR, '自检报告（双液系）')
    out = os.path.join(out_dir, '自检报告.docx')
    rpt.build_report(an, cfg, out, os.path.join(out_dir, 'figures'),
                     TEMPLATE, progress=lambda m: print('  ·', m))
    print('已生成：', out, os.path.getsize(out), 'bytes')


def val_like(x, u=None):
    """自检输出用的快速末位对齐：给 u 时按 σ 末位取值，否则按 2 位有效数字。"""
    import decimal
    if u is None:
        d = decimal.Decimal(repr(float(x)))
        q = decimal.Decimal(1).scaleb(d.adjusted() - 1)
        return str(float(d.quantize(q, rounding=decimal.ROUND_HALF_EVEN)))
    exp = decimal.Decimal(repr(float(u))).adjusted() - 1
    q = decimal.Decimal(1).scaleb(exp)
    return str(float(decimal.Decimal(repr(float(x))).quantize(
        q, rounding=decimal.ROUND_HALF_EVEN)))


def main():
    if '--test' in sys.argv:
        self_test()
        return
    from pcal.server import main as serve
    serve()


if __name__ == '__main__':
    main()
