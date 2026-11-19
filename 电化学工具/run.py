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
    from pcal.analysis import Analysis, default_config
    from pcal import report as rpt
    from pcal.server import TEMPLATE, OUT_DIR

    data_dir = default_config()['data_dir']
    print('数据目录：', data_dir)
    cfg = default_config()
    cfg.update(student_name=_who["student_name"], student_id=_who["student_id"], group=_who["group"], group_no=_who["group_no"],
               date='2026/10/23', room_temp=22.0, pressure=101.3)
    an = Analysis(cfg).run()
    if an.warnings:
        for w in an.warnings:
            print('  ⚠', w)
    # `Analysis.run()` 在缺关键数据（如空白 CV）时会**优雅提前返回**，
    # 此时 esa/table1 都是空的。可移植包里按设计不带原始数据，所以
    # 「解压后跑 --test」必然走到这条路——不能直接解引用，
    # 要明确说清「缺数据、去哪儿补」，而不是抛 KeyError 让人以为包坏了。
    if not an.esa or not an.table1:
        print()
        print('无法自检：缺少电化学原始数据（CHI 导出的 txt）。')
        print('  数据目录：%s' % data_dir)
        print('  可移植包**不附带原始数据**，请把自己的数据放进去，')
        print('  再到网页界面「数据文件映射」里对应到槽位。')
        print('  这里只是自检，界面与服务本身可以正常启动。')
        return 1
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
