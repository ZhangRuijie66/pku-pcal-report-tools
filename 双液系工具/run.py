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
    # 封面字段从个人档案读：可移植包被别人解压后，自检报告不该印出作者的名字。
    # 没填就到入口页「个人档案」里补，这里留空也能跑通（只在报告里空着）。
    from pcal import profile as _profile
    _who, _missing = _profile.personal(required=('student_name', 'student_id'))
    if _missing:
        print('提示：个人档案里还没填 %s，自检报告的封面会是空的。'
              % '、'.join(_missing))
    from pcal import phase
    from pcal.analysis import default_config
    from pcal import report as rpt
    from pcal.server import TEMPLATE, OUT_DIR

    cfg = default_config()
    cfg.update(student_name=_who["student_name"], student_id=_who["student_id"], group=_who["group"], group_no=_who["group_no"], date='2026/10/28',
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
