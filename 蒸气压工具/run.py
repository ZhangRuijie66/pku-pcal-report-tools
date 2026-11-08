# -*- coding: utf-8 -*-
"""液体饱和蒸气压实验报告一键生成 —— 启动入口。

    python run.py                 启动本地网页界面
    python run.py --test          无界面自检：用示例数据生成一份报告
    python run.py --port 8762     指定端口
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
    from pcal import vapor
    from pcal.analysis import default_config
    from pcal import report as rpt
    from pcal.server import TEMPLATE, OUT_DIR

    cfg = default_config()
    cfg.update(student_name=_who["student_name"], student_id=_who["student_id"], group=_who["group"], group_no=_who["group_no"], date='2026/10/15',
               room_temp=25.9, pressure=101.5, shift_check=1.0)
    an = vapor.analyze(vapor.sample_data(), cfg)
    print('示例数据自检（蒸发热数据处理.xlsx 口径）')
    for key in ('water', 'cyclo'):
        m = an[key]
        f = m.get('fit')
        if not f:
            print('  %s：无数据/点数不足' % key)
            continue
        print('  %s：A=%.3f±%.3f ×1e3 K  B=%.3f±%.3f  R2=%.5f'
              % (key, f['A'] / 1e3, f['sigma_A'] / 1e3, f['B'],
                 f['sigma_B'], f['r2']))
        print('    T_b=%s K  ΔH=%s kJ/mol  ΔS=%s J/(mol·K)'
              % ('%.2f±%.2f' % (f['tb'], f['sigma_tb']),
                 '%.3f±%.3f' % (f['dh_kJ'], f['sigma_dh_kJ']),
                 '%.2f±%.2f' % (f['ds'], f['sigma_ds'])))
        print('    相对偏差：T_b %+.2f%%  ΔH %+.2f%%'
              % (m.get('rel_tb', float('nan')), m.get('rel_dh', float('nan'))))
        if m.get('shift'):
            print('    温度偏高 %.1f ℃ 复算：ΔH=%.3f kJ/mol'
                  % (m['shift']['shift'], m['shift']['fit']['dh_kJ']))
    for w in an['warnings']:
        print('  ⚠', w)

    out_dir = os.path.join(OUT_DIR, '自检报告（蒸气压）')
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
