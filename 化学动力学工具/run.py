# -*- coding: utf-8 -*-
"""化学反应动力学实验报告一键生成 —— 启动入口。

    python run.py                 启动本地网页界面
    python run.py --test          无界面自检：用示例数据生成一份报告
    python run.py --port 8812     指定端口
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
    from pcal import kinetics
    from pcal.analysis import default_config
    from pcal import report as rpt
    from pcal.server import TEMPLATE, OUT_DIR

    cfg = default_config()
    cfg.update(student_name=_who["student_name"], student_id=_who["student_id"], group=_who["group"], group_no=_who["group_no"], date='2026/11/08',
               room_temp=20.0, pressure=101.6,
               alpha_inf_mode='measured', order_group='4M')
    an = kinetics.analyze(kinetics.sample_data(), cfg)
    print('示例数据自检（2025 年报告口径）')
    print('  标定：α = (%.2f±%.2f)c + (%.3f±%.3f)，R2=%.5f'
          % (an['calibration']['fit']['slope'],
             an['calibration']['fit']['sigma_slope'],
             an['calibration']['fit']['intercept'],
             an['calibration']['fit']['sigma_intercept'],
             an['calibration']['fit']['r2']))
    for g in an['groups']:
        print('  %-3s k1=%.6e±%.2e s-1  t1/2=%.1f±%.1f s  R2=%.5f'
              % (g['label'], g['k1'], g['sigma_k1'], g['t_half'],
                 g['sigma_t_half'], g['fits']['1']['r2']))
    if an['rate_law']:
        rl = an['rate_law']
        print('  k1–c(H+)：k0=%.3e  n=%.2f±%.2f  R2=%.5f'
              % (rl['k0'], rl['n'], rl['sigma_n'], rl['r2']))
    if an['loglog']:
        print('  lg–lg：n=%.2f±%.2f  R2=%.5f'
              % (an['loglog']['slope'], an['loglog']['sigma_slope'],
                 an['loglog']['r2']))
    print('  α∞：实验 %.2f°，理论 %.2f°'
          % (an['alpha_inf']['measured'], an['alpha_inf']['theory']))
    for w in an['warnings']:
        print('  ⚠', w)

    out_dir = os.path.join(OUT_DIR, '自检报告（化学动力学）')
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
