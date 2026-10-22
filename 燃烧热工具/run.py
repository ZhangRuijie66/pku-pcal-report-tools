# -*- coding: utf-8 -*-
"""燃烧热实验报告一键生成 —— 启动入口。

    python run.py            启动本地网页界面
    python run.py --test     只做一次无界面自检（加载样例数据并生成一份报告）
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def self_test():
    """无界面自检：用默认数据目录里的 csv 走完整流程并输出一份报告。"""
    from pcal import combustion as cb
    from pcal import report as rpt
    from pcal.analysis import Analysis, default_config, default_round
    from pcal.server import TEMPLATE, OUT_DIR, ASSETS

    data_dir = r'D:\北大\课程\26秋大三上\物理化学实验\1 燃烧热'
    files = [f for f in os.listdir(data_dir) if f.lower().endswith('.csv')
             and 'time(s)' in open(os.path.join(data_dir, f), encoding='utf-8-sig',
                                   errors='replace').read(400).replace(' ', '')]
    print('数据目录：', data_dir)
    print('找到文件：', files)

    cfg = default_config()
    cfg['student_name'] = '李晨曦'
    cfg['student_id'] = '2300012602'
    cfg['group'] = '20'
    cfg['group_no'] = '1'
    cfg['date'] = '2026/09/16'

    datasets = {}
    rounds = []
    for i, fn in enumerate(files):
        d = cb.load_combustion_csv(os.path.join(data_dir, fn))
        key = fn
        datasets[key] = d
        r = default_round(i + 1)
        r['file'] = key
        r['name'] = os.path.splitext(fn)[0]
        r['role'] = 'standard' if '苯甲酸' in fn else 'sample'
        rounds.append(r)
    cfg['rounds'] = rounds
    an = Analysis(cfg)
    an.run(datasets)
    for it in an.rounds:
        print('%-10s role=%-8s points=%s dT=%.4f K  m_sam=%.4f g  Σq=%.2f J' % (
            it['name'], it['role'], it['points'], it['dT'], it['sample_mass'], it['sum_q']))
        if it['role'] == 'standard':
            print('           W = %.1f ± %.0f J/K   Qv(benzoic) = %.1f J/g' % (
                it['W'], abs(it['sigma_W']), it['Qv_benzoic']))
        else:
            m = an.molar(it)
            print('           Qv = %.1f ± %.1f J/g   Qp = %.0f ± %.1f kJ/mol  (文献 %s)' % (
                it['Qv_per_gram'], it['sigma_Qv_per_gram'],
                m['Qp_kJ_per_mol'], m['sigma_kJ_per_mol'], m['literature']))

    out = os.path.join(OUT_DIR, '自检报告（燃烧热）', '自检报告.docx')
    intro = os.path.join(ASSETS, 'exp_principle.png')
    rpt.build_report(an, cfg, out, os.path.join(OUT_DIR, '自检报告（燃烧热）', 'figures'),
                     TEMPLATE, intro_image=intro if os.path.exists(intro) else None,
                     progress=lambda m: print('  ·', m))
    print('已生成：', out, os.path.getsize(out), 'bytes')


def main():
    if '--test' in sys.argv:
        self_test()
        return
    from pcal.server import main as serve
    serve()


if __name__ == '__main__':
    main()
