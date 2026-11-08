# -*- coding: utf-8 -*-
"""稀溶液法偶极矩实验报告一键生成 —— 启动入口。

    python run.py                 启动本地网页界面
    python run.py --test          无界面自检：用示例数据生成一份报告
    python run.py --port 8832     指定端口
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
    from pcal import dipole
    from pcal.analysis import default_config
    from pcal import report as rpt
    from pcal.server import TEMPLATE, OUT_DIR

    cfg = default_config()
    cfg.update(student_name=_who["student_name"], student_id=_who["student_id"], group=_who["group"], group_no=_who["group_no"], date='2026/11/19',
               room_temp=20.7, pressure=102.2)
    an = dipole.analyze(dipole.sample_data(), cfg)
    print('示例数据自检（数据处理2.xlsx 口径）')
    print('  ε_环=%.4f  C_分=%.4f pF  C₀=%.4f pF' %
          (an['eps_cyc'], an['C_dist'], an['C0']))
    print('  ε 拟合: a=%.4f±%.4f  ε₁=%.4f±%.4f  R²=%.4f' %
          (an['a'], an['s_a'], an['eps1'], an['s_eps1'], an['eps_fit']['r2']))
    print('  ρ 拟合: b=%.5f±%.5f  ρ₁=%.5f±%.5f  R²=%.4f' %
          (an['b'], an['s_b'], an['rho1'], an['s_rho1'], an['rho_fit']['r2']))
    print('  P̄₂^∞=%.3f±%.3f cm³/mol  R=%.3f±%.3f cm³/mol' %
          (an['P_inf'], an['s_P'], an['R_molar'], an['s_R']))
    print('  μ=%.3f±%.3f D（文献 %.2f D）' %
          (an['mu'], an['s_mu'], an['lit_mu']))
    for w in an['warnings']:
        print('  ⚠', w)

    out_dir = os.path.join(OUT_DIR, '自检报告（偶极矩）')
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
