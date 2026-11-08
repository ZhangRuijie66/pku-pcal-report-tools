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
    from pcal import adsorption
    from pcal.analysis import default_config
    from pcal import report as rpt
    from pcal.server import TEMPLATE, OUT_DIR

    cfg = default_config()
    cfg.update(student_name=_who["student_name"], student_id=_who["student_id"], group=_who["group"], group_no=_who["group_no"], date='2026/11/01',
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
