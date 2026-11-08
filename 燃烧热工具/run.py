# -*- coding: utf-8 -*-
"""燃烧热实验报告一键生成 —— 启动入口。

    python run.py            启动本地网页界面
    python run.py --test     只做一次无界面自检（加载样例数据并生成一份报告）
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
                 os.path.join(suite, '1 燃烧热'),
                 os.path.join(HERE, '样例数据')):
        if os.path.isdir(cand):
            return cand
    return HERE


DATA_DIR = _default_data_dir()


def _csv_files(data_dir):
    """数据目录里含 time(s) 表头的 csv；目录不存在或读不动就当没有。"""
    out = []
    try:
        names = sorted(os.listdir(data_dir))
    except OSError:
        return out
    for fn in names:
        if not fn.lower().endswith('.csv'):
            continue
        try:
            with open(os.path.join(data_dir, fn), encoding='utf-8-sig',
                      errors='replace') as fh:
                head = fh.read(400)
        except OSError:
            continue
        if 'time(s)' in head.replace(' ', ''):
            out.append(fn)
    return out


def self_test():
    """无界面自检：用默认数据目录里的 csv 走完整流程并输出一份报告。"""
    # 封面字段从个人档案读：可移植包被别人解压后，自检报告不该印出作者的名字。
    # 没填就到入口页「个人档案」里补，这里留空也能跑通（只在报告里空着）。
    from pcal import profile as _profile
    _who, _missing = _profile.personal(required=('student_name', 'student_id'))
    if _missing:
        print('提示：个人档案里还没填 %s，自检报告的封面会是空的。'
              % '、'.join(_missing))
    from pcal import combustion as cb
    from pcal import report as rpt
    from pcal.analysis import Analysis, default_config, default_round
    from pcal.server import TEMPLATE, OUT_DIR, ASSETS

    data_dir = os.environ.get('PCAL_DATA_DIR') or DATA_DIR
    files = _csv_files(data_dir)
    print('数据目录：', data_dir)
    print('找到文件：', files)

    if len(files) < 2:
        # 空目录是**正常**情形（别人刚解压可移植包、还没放自己的数据）。
        # 自检要报「装好了、但还没有数据」，而不是抛异常退出 1。
        print('\n⚠ 只找到 %d 个数据文件，至少需要 2 个（苯甲酸 + 待测样品）。'
              % len(files))
        print('  把课程软件导出的 csv 放进上面的目录（或子目录 样例数据/），'
              '再跑一次 --test。')
        print('  本次跳过报告生成。')
        return 0

    cfg = default_config()
    cfg["student_name"] = _who["student_name"]
    cfg["student_id"] = _who["student_id"]
    cfg["group"] = _who["group"]
    cfg["group_no"] = _who["group_no"]
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
