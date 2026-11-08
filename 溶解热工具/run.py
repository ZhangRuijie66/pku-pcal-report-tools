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


def _default_data_dir():
    """默认数据目录：**运行时推导**，不写死任何一台机器上的绝对路径。

    换台电脑（可移植包解压到别处）也能跑：套件根下的 数据/ → 课程原始数据
    目录（相对套件根）→ 工具目录里的 样例数据/ → 工具目录本身。最后一档
    一定存在，所以 --test 不会因为路径不存在而抛 FileNotFoundError。
    """
    suite = os.path.dirname(HERE)
    for cand in (os.path.join(suite, '数据'),
                 os.path.join(suite, '2 溶解热'),
                 os.path.join(HERE, '样例数据')):
        if os.path.isdir(cand):
            return cand
    return HERE


DATA_DIR = _default_data_dir()


def self_test():
    """无界面自检：用默认数据目录里的 csv 走完整流程并输出一份报告。"""
    # 封面字段从个人档案读：可移植包被别人解压后，自检报告不该印出作者的名字。
    # 没填就到入口页「个人档案」里补，这里留空也能跑通（只在报告里空着）。
    from pcal import profile as _profile
    _who, _missing = _profile.personal(required=('student_name', 'student_id'))
    if _missing:
        print('提示：个人档案里还没填 %s，自检报告的封面会是空的。'
              % '、'.join(_missing))
    from pcal import dissolution as ds
    from pcal import report as rpt
    from pcal.analysis import Analysis, default_config, default_round
    from pcal.server import TEMPLATE, OUT_DIR, _scan_dir, _software_summary

    data_dir = os.environ.get('PCAL_DATA_DIR') or DATA_DIR
    print('数据目录：', data_dir)
    files = _scan_dir(data_dir)
    software = _software_summary(data_dir)
    print('找到 %d 个溶解热数据文件，dissolution.csv 记录 %d 轮' %
          (len(files), len(software)))
    if not files:
        # 空目录是**正常**情形（别人刚解压可移植包、还没放自己的数据）。
        # 自检要报「装好了、但还没有数据」，而不是抛 SystemExit 退出非 0。
        print('\n⚠ 这个目录里没有数据文件（需要含 time(s),Delta_T(K) 表头的 csv）。')
        print('  把课程软件导出的 csv 放进上面的目录（或子目录 样例数据/），'
              '再跑一次 --test。')
        print('  本次跳过报告生成。')
        return 0

    cfg = default_config()
    cfg["student_name"] = _who["student_name"]
    cfg["student_id"] = _who["student_id"]
    cfg["group"] = _who["group"]
    cfg["group_no"] = _who["group_no"]
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
