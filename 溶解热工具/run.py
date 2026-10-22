# -*- coding: utf-8 -*-
"""溶解热实验报告一键生成 —— 启动入口。

    python run.py                 启动本地网页界面
    python run.py --test          只做一次无界面自检（读默认数据目录并生成一份报告）
    python run.py --port 8742     指定端口
    python run.py --no-browser    不自动打开浏览器
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DATA_DIR = r'D:\北大\课程\26秋大三上\物理化学实验\2 溶解热'


def self_test():
    """无界面自检：用默认数据目录里的 csv 走完整流程并输出一份报告。"""
    from pcal import dissolution as ds
    from pcal import report as rpt
    from pcal.analysis import Analysis, default_config, default_round
    from pcal.server import TEMPLATE, OUT_DIR, _scan_dir, _software_summary

    print('数据目录：', DATA_DIR)
    files = _scan_dir(DATA_DIR)
    software = _software_summary(DATA_DIR)
    print('找到 %d 个溶解热数据文件，dissolution.csv 记录 %d 轮' %
          (len(files), len(software)))
    if not files:
        raise SystemExit('没有找到数据文件（需要含 time(s),Delta_T(K) 表头的 csv）。')

    cfg = default_config()
    cfg['student_name'] = '张瑞杰'
    cfg['student_id'] = '2400011877'
    cfg['group'] = '3'
    cfg['group_no'] = '8'
    cfg['date'] = '2026/09/23'
    cfg['pressure_kPa'] = 101.3

    datasets = {}
    rounds = []
    for i, f in enumerate(files):
        d = ds.load_dissolution_csv(f['path'])
        datasets[f['path']] = d
        r = default_round(i + 1)
        r['file'] = f['path']
        r['name'] = '第%d轮' % (i + 1)
        ref = software.get(os.path.splitext(f['name'])[0]) or {}
        if ref.get('points'):
            r['points'] = ref['points']
            r['ref_Q_kJ'] = ref.get('Q_kJ')
        rounds.append(r)
    cfg['rounds'] = rounds

    an = Analysis(cfg)
    an.run(datasets)
    for it in an.rounds:
        print('%-6s Q\'=%8.1f J  dT_d=%.4f K  dT_h=%.4f K  Q=%.4f kJ  (%s)  sigmaQ=%.4f kJ'
              % (it['name'], it['Q_elec'], it['dT_diss'], it['dT_heat'], it['Q'] / 1000,
                 '自动' if it['is_auto'] else '文件记录', it['sigma_Q'] / 1000))
        print('        m=%.4f g  n0=%8.3f  sumQ=%8.1f J  Qs=%.4f kJ/mol' %
              (it['solute_mass'], it['n0'], it['cum_Q'] * 1000, it['Qs']))
    fit = an.fit
    print('拟合：Qs0 = %.4f ± %.4f kJ/mol   a = %.6f ± %.6f   R^2 = %.6f'
          % (fit['Qs0'], fit['sigma_Qs0'], fit['a'], fit['sigma_a'], fit['r_square']))
    for i, n in enumerate(an.diff['n0']):
        print('   n0=%6.0f  Qs=%7.3f  Qs_n2=%7.3f kJ/mol  Qs_n0=%7.2f J/mol  Qd=%s'
              % (n, an.diff['Qs'][i], an.diff['Qs_n2'][i], an.diff['Qs_n0'][i],
                 ('%.2f' % an.diff['Qd'][i - 1]) if i else '—'))

    out = os.path.join(OUT_DIR, '自检报告（溶解热）', '自检报告.docx')
    rpt.build_report(an, cfg, out, os.path.join(OUT_DIR, '自检报告（溶解热）', 'figures'),
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
